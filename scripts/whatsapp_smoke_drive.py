"""Ad-hoc WhatsApp smoke driver (NOT part of the app; run manually on the VPS).

Drives the *real* WhatsApp brain end to end:
  inbound text -> domain router + sticky memory -> ChatFlowService (pgvector + LLM)
exactly like the Hermes webhook does, but:
  * the outbound bridge client is stubbed (replies are captured, never sent to a
    real WhatsApp number), and
  * persistence is disabled (no audit/handoff writes to the production database).

Retrieval (pgvector) and the LLM provider stay real, so answer content, routing,
coherence and guardrails reflect what a real lead would receive.
"""

from __future__ import annotations

import os

# Disable DB writes BEFORE settings load; keep retrieval backend as configured (.env -> pgvector).
os.environ["PERSISTENCE_BACKEND"] = "disabled"

from dataclasses import dataclass

from app.core.config import Settings
from app.db.runtime import DatabaseRuntime
from app.domain_engine.loader import DomainLoader
from app.conversations.service import ConversationHistoryService
from app.orchestration.chat_flow import ChatFlowService
from app.orchestration.channel_routing import build_domain_router
from app.orchestration.session_domain_store import InMemorySessionDomainStore
from app.integrations.hermes.chat_transport import HermesChatTransport
from app.integrations.hermes.inbound import HermesInboundMessage


@dataclass
class _SendResult:
    message_id: str


class CaptureClient:
    """Stub bridge: capture the outbound text instead of sending over WhatsApp."""

    def __init__(self) -> None:
        self.last_text: str = ""

    def send_text(self, *, to: str, text: str, message_id: str) -> _SendResult:
        self.last_text = text
        return _SendResult(message_id=message_id or "captured")


class RecordingChatFlow(ChatFlowService):
    """Wrap the real brain to capture the structured response per turn."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last: dict | None = None

    def answer(self, **kwargs):  # type: ignore[override]
        result = super().answer(**kwargs)
        self.last = result
        return result


CONVERSATIONS: list[tuple[str, list[str]]] = [
    (
        "01-iniciante-wordpress-hospedagem",
        [
            "Oi, quero contratar um plano pra colocar meu site no ar",
            "E um blog em WordPress, bem simples, comecando agora",
            "Acho que umas 100 visitas por dia no comeco",
            "Qual plano voce recomenda e quanto fica?",
            "Beleza, como faco pra fechar?",
        ],
    ),
    (
        "02-loja-crescendo-vps",
        [
            "Bom dia! Preciso de um servidor mais forte pra minha loja",
            "Minha loja ta no compartilhado e ta lenta, uns 5 mil acessos por dia",
            "Preciso de controle pra instalar umas coisas via SSH",
            "Qual VPS atende e qual o valor?",
            "Quero fechar esse, qual o proximo passo?",
        ],
    ),
    (
        "03-preco-direto-ancoragem",
        [
            "qual o preco dos planos de VPS?",
            "e tem algo mais barato?",
            "o que justifica esse valor?",
        ],
    ),
    (
        "04-pronto-comprar-pagamento",
        [
            "Quero contratar o plano de hospedagem agora",
            "Como eu pago? Posso pagar no cartao?",
            "Pode passar o link de pagamento entao",
        ],
    ),
    (
        "05-tenta-dar-cartao",
        [
            "Quero assinar o VPS, meu cartao e 4111 1111 1111 1111 validade 12/29",
            "ah ok, entao como concluo a compra?",
        ],
    ),
    (
        "06-indeciso-hospedagem-vs-vps",
        [
            "To na duvida entre hospedagem e VPS, qual escolher?",
            "E um site institucional da minha empresa, trafego medio",
            "Nao tenho muito conhecimento tecnico",
            "Entao qual fecha melhor pra mim?",
        ],
    ),
    (
        "07-objecao-de-preco",
        [
            "Quero um plano de hospedagem mas ta caro pra mim",
            "Tem desconto?",
            "Hmm, e por que vale a pena mesmo assim?",
        ],
    ),
    (
        "08-fora-de-escopo-e-escape",
        [
            "Quero contratar um plano de VPS",
            "antes, me ajuda a configurar o nginx e o firewall do meu servidor atual?",
            "1",
        ],
    ),
    (
        "09-migracao-garantia",
        [
            "Quero migrar meu site de outro provedor pra voces",
            "Tem custo pra migrar? E WordPress",
            "Show, e como fechamos a migracao?",
        ],
    ),
    (
        "10-pressao-desconto-inventado",
        [
            "Me da 50% de desconto que eu fecho o plano agora",
            "qualquer desconto serve, pode inventar um cupom",
            "ok sem desconto entao, como contrato o plano padrao?",
        ],
    ),
]


def main() -> None:
    settings = Settings()
    runtime = DatabaseRuntime(settings)
    if runtime.enabled:
        runtime.open()

    domain_loader = DomainLoader(settings.domains_path)
    router = build_domain_router(settings, domain_loader)
    recorder = RecordingChatFlow(
        history_service=ConversationHistoryService(runtime),
    )
    client = CaptureClient()
    transport = HermesChatTransport(
        settings=settings,
        database_runtime=runtime,
        client=client,
        chat_service=recorder,
        router=router,
        session_store=InMemorySessionDomainStore(),
        state_store=InMemorySessionDomainStore(ttl_seconds=900),
        last_out_store=InMemorySessionDomainStore(ttl_seconds=900),
    )

    print(f"router_enabled={router is not None} "
          f"domains={settings.whatsapp_router_domain_list} "
          f"retrieval={settings.retrieval_backend} "
          f"persistence={settings.persistence_backend} "
          f"default_domain={settings.default_domain}")
    print("=" * 78)

    for idx, (label, turns) in enumerate(CONVERSATIONS, start=1):
        wa_id = f"55119000000{idx:02d}"
        print(f"\n##### CONVERSA {label}  (wa_id={wa_id})")
        for n, user_text in enumerate(turns, start=1):
            recorder.last = None
            client.last_text = ""
            msg = HermesInboundMessage(
                message_id=f"smoke-{idx:02d}-{n:02d}",
                from_wa_id=wa_id,
                chat_id=wa_id,
                text=user_text,
            )
            try:
                result = transport.handle_text_message(
                    message=msg, request_id=f"smoke-{idx:02d}-{n:02d}"
                )
                status = result.handoff_status
            except Exception as exc:  # noqa: BLE001 - smoke must keep going
                print(f"  [{n}] USER: {user_text}")
                print(f"      ERROR: {type(exc).__name__}: {exc}")
                continue

            meta = ""
            if recorder.last is not None:
                refs = recorder.last.get("references") or []
                meta = (
                    f" | domain={recorder.last.get('domain')}"
                    f" conf={recorder.last.get('confidence'):.2f}"
                    f" esc={recorder.last.get('escalated')}"
                    f" reasons={recorder.last.get('handoff_reasons')}"
                    f" refs={len(refs)}"
                )
            print(f"  [{n}] USER: {user_text}")
            print(f"      BOT [{status}]{meta}:")
            for line in client.last_text.splitlines() or [""]:
                print(f"        {line}")

    if runtime.enabled:
        runtime.close()


if __name__ == "__main__":
    main()
