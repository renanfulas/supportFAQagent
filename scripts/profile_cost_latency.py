"""Profile retrieval latency and estimate token cost per domain.

Roda offline e deterministico (backend ``lexical``, sem chave de provider) sobre
os casos de eval de cada dominio e produz um perfil sanitizado de latencia e
custo por request. A intencao e responder, com numeros reais e reprodutiveis,
"por que o bot esta rapido e barato" e quanto isso muda ao subir para pgvector.

O que e medido de fato (real):
- ``retrieval_ms`` por caso, cronometrando ``RetrievalService.retrieve``.
- ``total_ms`` do pipeline, via ``ChatFlowService.answer`` (offline).
- numero de tokens de entrada do prompt realmente montado (``build_prompt``).
- fracao de casos que chegam ao LLM (os demais sao atalhos sem custo de modelo:
  checkout, bloqueio de seguranca ou ausencia de contexto).

O que e estimado (configuravel):
- tokens de saida por chamada (orcamento assumido, ``--output-tokens``).
- custo em USD, a partir da tabela ``MODEL_PRICES_USD_PER_1M`` abaixo.

Privacidade: a saida agrega metricas e nunca inclui o texto das perguntas. Com
``--per-case`` mostra apenas ``case_id`` + metricas, nunca o enunciado.

Tabela de precos: valores de referencia para 2026-06; confirme a tabela vigente
do provedor antes de usar os numeros em decisao financeira.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

# Backend lexical garante execucao offline/deterministica e sem custo de
# embeddings; precisa estar setado antes de importar a config (lru_cache).
os.environ.setdefault("RETRIEVAL_BACKEND", "lexical")

from app.core.config import get_settings  # noqa: E402
from app.domain_engine.loader import DomainLoader  # noqa: E402
from app.domain_engine.models import DomainConfig  # noqa: E402
from app.evals.loader import EvalSuiteLoader  # noqa: E402
from app.core.errors import ProviderError  # noqa: E402
from app.handoff.service import HandoffService  # noqa: E402
from app.llm.service import LLMService  # noqa: E402
from app.orchestration.chat_flow import ChatFlowService, _normalize  # noqa: E402
from app.orchestration.prompt_builder import build_prompt  # noqa: E402
from app.retrieval.service import RetrievalService  # noqa: E402


# Precos de referencia (USD por 1M de tokens), 2026-06. Edite conforme a tabela
# vigente do provedor. Modelos ausentes caem em custo "nao estimado".
MODEL_PRICES_USD_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
}

# Dominios vivos com provider real por padrao. ``suporte-vps`` usa provider mock
# (sem custo de modelo) e fica de fora salvo se pedido explicitamente.
DEFAULT_DOMAINS = ["vendas", "suporte-vps-whatsapp", "suporte-hospedagem"]


def _estimate_tokens(text: str) -> int:
    """Conta tokens com tiktoken quando disponivel; senao heuristica chars/4.

    tiktoken nao e dependencia do projeto, entao o fallback heuristico (boa
    aproximacao para pt-BR) e o caminho normal. A heuristica e suficiente para
    comparar dominios e dimensionar custo, nao para faturamento exato.
    """
    if not text:
        return 0
    try:  # pragma: no cover - depende de dependencia opcional
        import tiktoken

        encoding = tiktoken.get_encoding("o200k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, round(len(text) / 4))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (pct / 100) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    interpolated = ordered[low] + (ordered[high] - ordered[low]) * (rank - low)
    return round(interpolated, 3)


def _price_for(model: str, kind: str) -> float | None:
    entry = MODEL_PRICES_USD_PER_1M.get(model)
    if entry is None:
        return None
    return entry.get(kind)


@dataclass
class CaseMetrics:
    case_id: str
    pipeline_overhead_ms: float
    retrieval_ms: float
    input_tokens: int
    query_tokens: int
    llm_eligible: bool
    short_circuit: str | None  # checkout | blocked | no_context | None
    llm_ms: float | None = None  # so preenchido em modo --live
    output_tokens: int | None = None  # so preenchido em modo --live


@dataclass
class DomainProfile:
    domain: str
    model: str
    embedding_model: str
    cases: list[CaseMetrics] = field(default_factory=list)


def _classify_short_circuit(
    domain: DomainConfig,
    question: str,
    handoff_service: HandoffService,
    chunks_count: int,
) -> str | None:
    """Identifica atalhos que evitam o LLM, espelhando o ChatFlowService.

    Retorna o tipo de atalho (``checkout``, ``blocked``, ``no_context``) ou
    ``None`` quando o caso de fato gastaria uma chamada de modelo.
    """
    text = _normalize(question)
    checkout = getattr(domain, "checkout", None)
    if checkout is not None and checkout.enabled and checkout.payment_link and text:
        declines = [*checkout.decline_phrases, *domain.handoff.explicit_human_phrases]
        declined = any(_normalize(p) in text for p in declines if p.strip())
        intent = any(_normalize(p) in text for p in checkout.intent_phrases if p.strip())
        if intent and not declined:
            return "checkout"

    reasons = handoff_service.inspect_question(domain, question)
    if any(reason in ChatFlowService.BLOCKING_REASONS for reason in reasons):
        return "blocked"

    if chunks_count == 0:
        return "no_context"
    return None


def _mock_domain(domain: DomainConfig) -> DomainConfig:
    """Copia o dominio forcando provider ``mock`` para a medicao offline.

    Garante que a medicao do pipeline nunca chame um provider real (sem rede,
    sem custo, deterministico), mesmo quando a ``.env`` local tem chave real.
    """
    mock_llm = domain.llm.model_copy(update={"provider": "mock"})
    return domain.model_copy(update={"llm": mock_llm})


def profile_domain(
    domain: DomainConfig,
    eval_file: str,
    repeats: int,
    live_sample: int,
) -> DomainProfile | None:
    loader = EvalSuiteLoader()
    suite = loader.load(domain.root_path / Path(eval_file))
    if suite is None:
        return None

    retrieval_service = RetrievalService()
    handoff_service = HandoffService()
    flow = ChatFlowService()
    mock_domain = _mock_domain(domain)
    live_provider = None
    if live_sample > 0:
        try:
            live_provider = LLMService().get_provider(domain)
        except ProviderError as exc:
            print(
                f"--live indisponivel para {domain.name}: {exc.error_code}",
                file=sys.stderr,
            )

    profile = DomainProfile(
        domain=domain.name,
        model=domain.llm.model,
        embedding_model=domain.embedding.model,
    )

    live_done = 0
    for case in suite.cases:
        question = case.question

        # Latencia real de retrieval, melhor de ``repeats`` execucoes para
        # reduzir ruido de I/O frio (a ingestao le arquivos do dominio).
        retrieval_samples: list[float] = []
        chunks = []
        for _ in range(repeats):
            started = perf_counter()
            chunks = retrieval_service.retrieve(domain, question)
            retrieval_samples.append((perf_counter() - started) * 1000)
        retrieval_ms = min(retrieval_samples)

        # Overhead real de orquestracao (retrieval + handoff + confidence +
        # montagem do prompt), com provider mock: SEM rede e SEM custo.
        overhead_started = perf_counter()
        flow.answer(mock_domain, question)
        pipeline_overhead_ms = (perf_counter() - overhead_started) * 1000

        prompt = build_prompt(domain=domain, question=question, chunks=chunks, history=[])
        input_tokens = _estimate_tokens(prompt)
        query_tokens = _estimate_tokens(question)

        short_circuit = _classify_short_circuit(
            domain, question, handoff_service, len(chunks)
        )

        llm_ms = None
        output_tokens = None
        if (
            live_provider is not None
            and short_circuit is None
            and live_done < live_sample
        ):
            try:
                llm_started = perf_counter()
                answer = live_provider.generate_answer(prompt)
                llm_ms = round((perf_counter() - llm_started) * 1000, 3)
                output_tokens = _estimate_tokens(answer)
                live_done += 1
            except ProviderError:
                llm_ms = None
                output_tokens = None

        profile.cases.append(
            CaseMetrics(
                case_id=case.id,
                pipeline_overhead_ms=round(pipeline_overhead_ms, 3),
                retrieval_ms=round(retrieval_ms, 3),
                input_tokens=input_tokens,
                query_tokens=query_tokens,
                llm_eligible=short_circuit is None,
                short_circuit=short_circuit,
                llm_ms=llm_ms,
                output_tokens=output_tokens,
            )
        )

    return profile


def summarize(
    profile: DomainProfile,
    output_tokens: int,
    include_embedding: bool,
) -> dict[str, object]:
    cases = profile.cases
    total = len(cases)
    eligible = [c for c in cases if c.llm_eligible]
    eligible_count = len(eligible)
    eligible_share = (eligible_count / total) if total else 0.0

    retrieval_values = [c.retrieval_ms for c in cases]
    overhead_values = [c.pipeline_overhead_ms for c in cases]
    avg_input = (
        sum(c.input_tokens for c in eligible) / eligible_count if eligible_count else 0.0
    )
    avg_query = (sum(c.query_tokens for c in cases) / total) if total else 0.0

    # Medicoes reais de LLM, quando houve modo --live.
    live_llm_ms = [c.llm_ms for c in cases if c.llm_ms is not None]
    live_out_tokens = [c.output_tokens for c in cases if c.output_tokens is not None]
    measured_output = (
        sum(live_out_tokens) / len(live_out_tokens) if live_out_tokens else None
    )
    effective_output = measured_output if measured_output is not None else output_tokens

    price_in = _price_for(profile.model, "input")
    price_out = _price_for(profile.model, "output")
    price_embed = _price_for(profile.embedding_model, "input")

    cost_per_llm_call = None
    if price_in is not None and price_out is not None:
        cost_per_llm_call = (avg_input * price_in + effective_output * price_out) / 1_000_000

    # Custo medio por request leva em conta que so a fracao elegivel gasta LLM.
    cost_per_request = None
    if cost_per_llm_call is not None:
        cost_per_request = cost_per_llm_call * eligible_share

    embedding_cost_per_request = None
    if include_embedding and price_embed is not None:
        # No pgvector, toda request elegivel paga o embedding da query.
        embedding_cost_per_request = (avg_query * price_embed / 1_000_000) * eligible_share
        if cost_per_request is not None:
            cost_per_request = cost_per_request + embedding_cost_per_request

    short_circuits: dict[str, int] = {}
    for case in cases:
        if case.short_circuit:
            short_circuits[case.short_circuit] = short_circuits.get(case.short_circuit, 0) + 1

    return {
        "domain": profile.domain,
        "model": profile.model,
        "embedding_model": profile.embedding_model,
        "cases": total,
        "llm_eligible_cases": eligible_count,
        "llm_eligible_share": round(eligible_share, 4),
        "short_circuit_breakdown": short_circuits,
        "retrieval_ms": {
            "avg": round(sum(retrieval_values) / total, 3) if total else 0.0,
            "p50": _percentile(retrieval_values, 50),
            "p95": _percentile(retrieval_values, 95),
            "max": round(max(retrieval_values), 3) if total else 0.0,
        },
        "pipeline_overhead_ms": {
            "avg": round(sum(overhead_values) / total, 3) if total else 0.0,
            "p50": _percentile(overhead_values, 50),
            "p95": _percentile(overhead_values, 95),
            "note": "orquestracao sem LLM (provider mock); nao inclui round-trip do modelo",
        },
        "live_llm_ms": (
            {
                "samples": len(live_llm_ms),
                "avg": round(sum(live_llm_ms) / len(live_llm_ms), 3),
                "p50": _percentile(live_llm_ms, 50),
                "p95": _percentile(live_llm_ms, 95),
            }
            if live_llm_ms
            else None
        ),
        "avg_input_tokens_per_llm_call": round(avg_input, 1),
        "output_tokens_per_llm_call": round(effective_output, 1),
        "output_tokens_source": "measured" if measured_output is not None else "assumed",
        "avg_query_tokens": round(avg_query, 1),
        "cost_usd": {
            "per_llm_call": _round_money(cost_per_llm_call),
            "embedding_per_request": _round_money(embedding_cost_per_request),
            "per_request_effective": _round_money(cost_per_request),
            "per_1k_requests": _round_money(
                cost_per_request * 1000 if cost_per_request is not None else None
            ),
        },
    }


def _round_money(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "domains",
        nargs="*",
        default=DEFAULT_DOMAINS,
        help=f"Dominios a perfilar (default: {', '.join(DEFAULT_DOMAINS)}).",
    )
    parser.add_argument(
        "--file",
        default="evals/cases.yaml",
        help="Arquivo de eval relativo a raiz do dominio (default: evals/cases.yaml).",
    )
    parser.add_argument(
        "--output-tokens",
        type=int,
        default=220,
        help="Orcamento assumido de tokens de saida por chamada de LLM.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Repeticoes de retrieval por caso (usa o melhor tempo).",
    )
    parser.add_argument(
        "--live",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Mede latencia/tokens reais do LLM nos primeiros N casos elegiveis por "
            "dominio. Requer chave de provider e GERA CUSTO real. Default 0 (offline)."
        ),
    )
    parser.add_argument(
        "--embedding-cost",
        action="store_true",
        help="Inclui custo de embedding da query (cenario pgvector).",
    )
    parser.add_argument(
        "--per-case",
        action="store_true",
        help="Inclui metricas por caso (apenas case_id, nunca o enunciado).",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Imprime tambem uma tabela markdown resumida.",
    )
    args = parser.parse_args()

    settings = get_settings()
    domain_loader = DomainLoader(settings.domains_path)

    summaries: list[dict[str, object]] = []
    per_case_output: dict[str, list[dict[str, object]]] = {}
    for name in args.domains:
        domain = domain_loader.load(name)
        if domain is None:
            print(f"domain not found: {name}", file=sys.stderr)
            continue
        profile = profile_domain(domain, args.file, args.repeats, args.live)
        if profile is None:
            print(f"eval suite not found for {name}: {args.file}", file=sys.stderr)
            continue
        summaries.append(summarize(profile, args.output_tokens, args.embedding_cost))
        if args.per_case:
            per_case_output[name] = [
                {
                    "case_id": c.case_id,
                    "retrieval_ms": c.retrieval_ms,
                    "pipeline_overhead_ms": c.pipeline_overhead_ms,
                    "input_tokens": c.input_tokens,
                    "llm_eligible": c.llm_eligible,
                    "short_circuit": c.short_circuit,
                    "llm_ms": c.llm_ms,
                    "output_tokens": c.output_tokens,
                }
                for c in profile.cases
            ]

    report: dict[str, object] = {
        "retrieval_backend": settings.retrieval_backend,
        "output_tokens_assumption": args.output_tokens,
        "embedding_cost_included": args.embedding_cost,
        "price_table_usd_per_1m": MODEL_PRICES_USD_PER_1M,
        "domains": summaries,
    }
    if args.per_case:
        report["per_case"] = per_case_output

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.markdown:
        _print_markdown(summaries)
    return 0


def _print_markdown(summaries: list[dict[str, object]]) -> None:
    print("\n| Dominio | Modelo | retrieval avg/p95 (ms) | tokens in | % LLM | USD/1k req |")
    print("| --- | --- | --- | --- | --- | --- |")
    for item in summaries:
        retrieval = item["retrieval_ms"]
        cost = item["cost_usd"]
        per_1k = cost["per_1k_requests"]
        per_1k_text = f"${per_1k:.4f}" if isinstance(per_1k, (int, float)) else "n/d"
        print(
            f"| {item['domain']} | {item['model']} | "
            f"{retrieval['avg']:.2f} / {retrieval['p95']:.2f} | "
            f"{item['avg_input_tokens_per_llm_call']:.0f} | "
            f"{item['llm_eligible_share'] * 100:.0f}% | {per_1k_text} |"
        )


if __name__ == "__main__":
    raise SystemExit(main())
