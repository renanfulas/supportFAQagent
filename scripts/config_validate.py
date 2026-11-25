"""Explain what an installation config is missing, without printing any value.

    python -m scripts.config_validate --env-file .env [--profile padrao] [--strict]
    docker compose -f docker-compose.prod.yml run --rm --no-deps -T app \
        python -m scripts.config_validate --env-file - < .env

Reads the .env without exporting anything, applies the rules of its profile
(CONFIG_PROFILE: minimo, padrao, completo) and the installation coherence rules,
and finally builds the app Settings with exactly those values, to catch what the
app would refuse at start. Every finding names variables and the reason, never
a value. Without --env-file it reads the process environment (inside the
container, the compose env_file), and unknown names are not checked.

Exit: 0 no errors, 1 errors (or warnings with --strict), 2 unreadable input.
Runbook: docs/runbooks/docker-install.md
"""

from __future__ import annotations

import argparse
import difflib
import io
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlsplit


EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNREADABLE = 2

PROFILES = ("minimo", "padrao", "completo")
PRIVATE_PLACEHOLDER = "<set-private-value>"
PROVIDER_PLACEHOLDER = "<set-provider-value>"
EXAMPLE_VALUES = {"your-openai-key-here", "your-anthropic-key-here"}
DEV_ENVS = {"development", "dev", "local"}
TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}

# Read by docker compose, deploy/install.sh or scripts/safe_start.py, not by Settings.
TOOL_VARS = frozenset(
    {
        "CONFIG_PROFILE",
        "COMPOSE_PROFILES",
        "CLIENT_PACK_DIR",
        "APP_PORT",
        "FORWARDED_ALLOW_IPS",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "SUPPORTFAQ_IMAGE",
        "SUPPORTFAQ_EXTRAS",
        "STARTUP_MIGRATIONS",
        "STARTUP_READINESS_TIMEOUT_SECONDS",
        "STARTUP_LOCK_TIMEOUT_SECONDS",
    }
)

# Secrets the installation generates itself: random, long and never shared.
GENERATED_SECRETS = (
    "API_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "PERSISTENCE_HASH_SECRET",
    "IDENTITY_HASH_SECRET",
    "OTP_DIGEST_SECRET",
    "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN",
    "OUTBOX_WEBHOOK_SECRET",
    "HERMES_WEBHOOK_SECRET",
    "HERMES_CHAT_FORWARD_SECRET",
)
MIN_SECRET_LENGTH = 24

# What each profile turns on. Turning a flag off is allowed (warning), since the
# person installing may postpone a channel; missing requirements are errors.
PROFILE_FLAGS: dict[str, tuple[str, ...]] = {
    "minimo": (),
    "padrao": ("ENABLE_PUBLIC_CHAT_UI", "ENABLE_SUPPORT_INBOX"),
    "completo": (
        "ENABLE_PUBLIC_CHAT_UI",
        "ENABLE_SUPPORT_INBOX",
        "ENABLE_SUPPORT_CONSOLE",
        "ENABLE_WEB_WHATSAPP_AUTH",
        "ENABLE_HANDOFF_CONSENT_GATE",
        "ENABLE_META_WHATSAPP_WEBHOOK",
        "ENABLE_META_WHATSAPP_CHAT",
    ),
}
PROFILE_REQUIRES_LLM = {"minimo": False, "padrao": True, "completo": True}

ERROR = "erro"
WARNING = "aviso"
INFO = "info"
LEVEL_LABEL = {ERROR: "ERRO ", WARNING: "AVISO", INFO: "INFO "}

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


@dataclass(frozen=True)
class Finding:
    level: str
    name: str
    message: str


@dataclass
class Context:
    values: dict[str, str]
    profile: str | None
    pack_dir: Path
    from_file: bool
    duplicates: dict[str, int] = field(default_factory=dict)
    domains: list[str] = field(default_factory=list)

    def get(self, name: str) -> str:
        return (self.values.get(name) or "").strip()

    def flag(self, name: str) -> bool:
        return self.get(name).lower() in TRUE_VALUES

    def has_placeholder(self, name: str) -> bool:
        value = self.get(name)
        return PRIVATE_PLACEHOLDER in value or PROVIDER_PLACEHOLDER in value

    @property
    def compose_profiles(self) -> set[str] | None:
        if "COMPOSE_PROFILES" not in self.values:
            return None
        return {item.strip() for item in self.get("COMPOSE_PROFILES").split(",") if item.strip()}

    @property
    def is_dev(self) -> bool:
        return (self.get("APP_ENV") or "development").lower() in DEV_ENVS


@dataclass
class Result:
    profile: str | None
    variable_count: int
    domains: list[str]
    findings: list[Finding]

    def count(self, level: str) -> int:
        return sum(1 for finding in self.findings if finding.level == level)

    def exit_code(self, *, strict: bool = False) -> int:
        if self.count(ERROR) or (strict and self.count(WARNING)):
            return EXIT_INVALID
        return EXIT_OK


# --- reading ----------------------------------------------------------------------


def parse_env_text(text: str) -> tuple[dict[str, str], dict[str, int]]:
    """Return the values of an env file (last one wins) and the repeated names."""
    from dotenv import dotenv_values

    parsed = dotenv_values(stream=io.StringIO(text))
    values = {name: value or "" for name, value in parsed.items()}
    seen: dict[str, int] = {}
    for line in text.splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            seen[match.group(1)] = seen.get(match.group(1), 0) + 1
    return values, {name: count for name, count in seen.items() if count > 1}


def known_names() -> set[str]:
    from app.core.config import Settings

    return {field.alias for field in Settings.model_fields.values() if field.alias} | TOOL_VARS


def environment_values(environ: Mapping[str, str]) -> dict[str, str]:
    names = known_names()
    return {name: value for name, value in environ.items() if name in names}


def resolve_pack_dir(
    values: Mapping[str, str],
    environ: Mapping[str, str],
    override: str | None = None,
) -> Path:
    # Same precedence as the runtime: inside the container compose sets
    # DOMAINS_PATH to the mounted pack; on the host the pack is CLIENT_PACK_DIR.
    for candidate in (
        override,
        environ.get("DOMAINS_PATH"),
        values.get("CLIENT_PACK_DIR"),
        values.get("DOMAINS_PATH"),
    ):
        if candidate and candidate.strip():
            return Path(candidate.strip())
    return Path("domains")


# --- rules ------------------------------------------------------------------------


def check_profile(ctx: Context) -> Iterable[Finding]:
    if ctx.profile is None:
        yield Finding(INFO, "CONFIG_PROFILE", "sem perfil; validando so a coerencia da configuracao")
    elif ctx.profile not in PROFILES:
        yield Finding(ERROR, "CONFIG_PROFILE", f"perfil desconhecido; use um de: {', '.join(PROFILES)}")
        return
    if ctx.profile and ctx.is_dev:
        yield Finding(
            ERROR,
            "APP_ENV",
            "instalacao com ambiente de desenvolvimento: sem API key obrigatoria nem cookie Secure; use production",
        )


def check_placeholders(ctx: Context) -> Iterable[Finding]:
    for name in sorted(ctx.values):
        value = ctx.get(name)
        if PROVIDER_PLACEHOLDER in value:
            yield Finding(ERROR, name, f"ainda tem {PROVIDER_PLACEHOLDER}; cole o valor do fornecedor")
        elif PRIVATE_PLACEHOLDER in value:
            yield Finding(
                ERROR,
                name,
                f"ainda tem {PRIVATE_PLACEHOLDER}; o install.sh gera, ou use um valor aleatorio",
            )
        elif value in EXAMPLE_VALUES:
            yield Finding(ERROR, name, "valor de exemplo do .env.example; cole a chave real ou deixe vazio")


def check_secrets(ctx: Context) -> Iterable[Finding]:
    present = [
        name
        for name in GENERATED_SECRETS
        if ctx.get(name) and not ctx.has_placeholder(name)
    ]
    for name in present:
        if len(ctx.get(name)) < MIN_SECRET_LENGTH and not ctx.is_dev:
            yield Finding(
                ERROR,
                name,
                f"segredo curto (menos de {MIN_SECRET_LENGTH} caracteres); gere um valor aleatorio",
            )
    for index, name in enumerate(present):
        for other in present[index + 1 :]:
            if ctx.get(name) == ctx.get(other):
                yield Finding(ERROR, name, f"mesmo valor que {other}; cada segredo precisa ser unico")


def check_database(ctx: Context) -> Iterable[Finding]:
    url = ctx.get("DATABASE_URL")
    profiles = ctx.compose_profiles
    if not url or ctx.has_placeholder("DATABASE_URL") or profiles is None:
        return
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        yield Finding(ERROR, "DATABASE_URL", "URL invalida; formato postgresql://usuario:senha@host:5432/banco")
        return
    if host == "postgres":
        if "db" not in profiles:
            yield Finding(
                ERROR,
                "DATABASE_URL",
                'aponta para o servico "postgres", mas o perfil "db" esta fora do COMPOSE_PROFILES',
            )
            return
        if not ctx.has_placeholder("POSTGRES_PASSWORD"):
            if unquote(parts.password or "") != ctx.get("POSTGRES_PASSWORD"):
                yield Finding(ERROR, "DATABASE_URL", "a senha nao confere com POSTGRES_PASSWORD")
        user = ctx.get("POSTGRES_USER") or "supportfaq"
        if unquote(parts.username or "") != user:
            yield Finding(ERROR, "DATABASE_URL", "o usuario nao confere com POSTGRES_USER")
        database = ctx.get("POSTGRES_DB") or "supportfaq"
        if parts.path.lstrip("/") != database:
            yield Finding(ERROR, "DATABASE_URL", "o banco nao confere com POSTGRES_DB")
    elif "db" in profiles:
        yield Finding(
            WARNING,
            "COMPOSE_PROFILES",
            'o perfil "db" sobe o Postgres embarcado, mas DATABASE_URL aponta para outro banco',
        )


def check_redis(ctx: Context) -> Iterable[Finding]:
    profiles = ctx.compose_profiles
    backend = ctx.get("SESSION_STATE_BACKEND").lower() or "memory"
    if profiles is None:
        return
    url = ctx.get("SESSION_STATE_REDIS_URL")
    host = ""
    if url:
        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            host = ""
    if backend == "redis" and host == "redis" and "redis" not in profiles:
        yield Finding(
            ERROR,
            "SESSION_STATE_REDIS_URL",
            'aponta para o servico "redis", mas o perfil "redis" esta fora do COMPOSE_PROFILES',
        )
    if "redis" in profiles and backend != "redis":
        yield Finding(
            WARNING,
            "COMPOSE_PROFILES",
            'o perfil "redis" sobe o cache, mas SESSION_STATE_BACKEND nao usa redis',
        )


def check_llm(ctx: Context) -> Iterable[Finding]:
    has_key = any(
        ctx.get(name) and not ctx.has_placeholder(name) and ctx.get(name) not in EXAMPLE_VALUES
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    )
    placeholder = any(ctx.has_placeholder(name) for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"))
    if has_key or placeholder:
        return
    if ctx.profile and PROFILE_REQUIRES_LLM.get(ctx.profile):
        yield Finding(
            ERROR,
            "OPENAI_API_KEY",
            f"o perfil {ctx.profile} precisa de uma chave de LLM (OPENAI_API_KEY ou ANTHROPIC_API_KEY)",
        )
    else:
        yield Finding(INFO, "OPENAI_API_KEY", "sem chave de LLM: o chat responde com fallback seguro")


def check_retrieval(ctx: Context) -> Iterable[Finding]:
    has_key = bool(ctx.get("OPENAI_API_KEY")) and not ctx.has_placeholder("OPENAI_API_KEY")
    if ctx.get("RETRIEVAL_BACKEND").lower() != "pgvector":
        if has_key:
            yield Finding(
                INFO,
                "RETRIEVAL_BACKEND",
                "busca lexical; bash deploy/install.sh --pgvector ingere os dominios e liga a busca vetorial",
            )
        return
    if not has_key:
        yield Finding(ERROR, "RETRIEVAL_BACKEND", "pgvector usa embeddings da OpenAI; falta OPENAI_API_KEY")
    yield Finding(
        WARNING,
        "RETRIEVAL_BACKEND",
        "com pgvector o readiness barra o start ate os dominios serem ingeridos; "
        "num banco novo, instale com lexical e rode install.sh --pgvector",
    )


def check_otp_delivery(ctx: Context) -> Iterable[Finding]:
    transport = ctx.get("WEB_AUTH_OTP_DELIVERY_TRANSPORT").lower() or "memory"
    if transport != "memory" or ctx.is_dev:
        return
    for name in ("ENABLE_SUPPORT_CONSOLE", "ENABLE_WEB_WHATSAPP_AUTH"):
        if ctx.flag(name):
            yield Finding(
                ERROR,
                "WEB_AUTH_OTP_DELIVERY_TRANSPORT",
                f"{name} ligado com entrega de OTP em memoria: o codigo nunca chega; use meta ou hermes",
            )


def check_profile_flags(ctx: Context) -> Iterable[Finding]:
    for name in PROFILE_FLAGS.get(ctx.profile or "", ()):
        if not ctx.flag(name):
            yield Finding(WARNING, name, f"o perfil {ctx.profile} liga este recurso; aqui esta desligado")


def check_public_surface(ctx: Context) -> Iterable[Finding]:
    if ctx.compose_profiles is None:
        return
    public = [
        name for name in ("ENABLE_PUBLIC_CHAT_UI", "ENABLE_META_WHATSAPP_WEBHOOK") if ctx.flag(name)
    ]
    if not public:
        return
    if ctx.get("FORWARDED_ALLOW_IPS") in {"", "127.0.0.1"}:
        yield Finding(
            WARNING,
            "FORWARDED_ALLOW_IPS",
            "rota publica ligada com o proxy em 127.0.0.1: atras de um proxy no host, use o gateway "
            "da rede Docker, senao todos os clientes dividem o mesmo rate limit",
        )
    yield Finding(
        INFO,
        public[0],
        "rota publica: exponha so por reverse proxy HTTPS; a API continua presa em 127.0.0.1",
    )


def check_tool_values(ctx: Context) -> Iterable[Finding]:
    mode = ctx.get("STARTUP_MIGRATIONS").lower()
    if mode and mode not in {"auto", "off"}:
        yield Finding(ERROR, "STARTUP_MIGRATIONS", "use auto ou off")
    for name in ("STARTUP_READINESS_TIMEOUT_SECONDS", "STARTUP_LOCK_TIMEOUT_SECONDS"):
        raw = ctx.get(name)
        if raw:
            try:
                ok = float(raw) > 0
            except ValueError:
                ok = False
            if not ok:
                yield Finding(ERROR, name, "precisa ser um numero positivo de segundos")
    port = ctx.get("APP_PORT")
    if port and not (port.isdigit() and 0 < int(port) < 65536):
        yield Finding(ERROR, "APP_PORT", "precisa ser uma porta entre 1 e 65535")


def check_names(ctx: Context) -> Iterable[Finding]:
    for name, count in sorted(ctx.duplicates.items()):
        yield Finding(WARNING, name, f"definida {count} vezes; vale a ultima")
    if not ctx.from_file:
        return
    names = known_names()
    for name in sorted(set(ctx.values) - names):
        close = difflib.get_close_matches(name, names, n=1, cutoff=0.8)
        hint = f"; quis dizer {close[0]}?" if close else ""
        yield Finding(WARNING, name, f"variavel desconhecida, o app ignora{hint}")


def check_pack(ctx: Context) -> Iterable[Finding]:
    from app.domain_engine.loader import DomainLoader

    if not ctx.pack_dir.is_dir():
        yield Finding(ERROR, "CLIENT_PACK_DIR", "pasta do pacote do cliente nao encontrada")
        return
    domains = ctx.domains = DomainLoader(ctx.pack_dir).list_domains()
    if not domains:
        yield Finding(ERROR, "CLIENT_PACK_DIR", "o pacote nao tem nenhum dominio valido (domain.yaml)")
        return
    default = ctx.get("DEFAULT_DOMAIN") or "suporte-vps-whatsapp"
    if default not in domains:
        yield Finding(ERROR, "DEFAULT_DOMAIN", "o dominio padrao nao existe no pacote do cliente")
    if ctx.flag("ENABLE_WHATSAPP_DOMAIN_ROUTER") or ctx.flag("ENABLE_WEB_DOMAIN_ROUTER"):
        routed = [item.strip() for item in ctx.get("WHATSAPP_ROUTER_DOMAINS").split(",") if item.strip()]
        missing = [name for name in routed if name not in domains]
        if missing:
            yield Finding(
                ERROR,
                "WHATSAPP_ROUTER_DOMAINS",
                f"{len(missing)} dominio(s) do roteador nao existem no pacote",
            )


def check_settings(ctx: Context) -> Iterable[Finding]:
    """Build the app Settings with exactly these values, isolated from the process env."""
    from pydantic import ValidationError

    from app.core.config import Settings

    class _IsolatedSettings(Settings):
        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, *_args, **_kwargs):
            return (init_settings,)

    names = known_names() - TOOL_VARS
    values = {
        # Placeholders are already reported; a unique stand-in per name keeps
        # them from tripping "must be different" and hides nothing else.
        name: value.replace(PRIVATE_PLACEHOLDER, f"pending-{name}-{'x' * MIN_SECRET_LENGTH}").replace(
            PROVIDER_PLACEHOLDER, f"pending-{name}"
        )
        for name, value in ctx.values.items()
        if name in names
    }
    values["DOMAINS_PATH"] = str(ctx.pack_dir)
    try:
        _IsolatedSettings(**values)
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg", "invalid")).removeprefix("Value error, ")
            yield Finding(ERROR, location or "Settings", f"o app recusaria iniciar: {message}")
    except Exception as exc:  # pragma: no cover - defensive, never echo the value
        yield Finding(ERROR, "Settings", f"o app recusaria iniciar ({type(exc).__name__})")


RULES: tuple[Callable[[Context], Iterable[Finding]], ...] = (
    check_profile,
    check_placeholders,
    check_secrets,
    check_database,
    check_redis,
    check_llm,
    check_retrieval,
    check_otp_delivery,
    check_profile_flags,
    check_public_surface,
    check_tool_values,
    check_names,
    check_pack,
    check_settings,
)


def validate(
    values: Mapping[str, str],
    *,
    pack_dir: Path,
    profile: str | None = None,
    from_file: bool = True,
    duplicates: Mapping[str, int] | None = None,
) -> Result:
    resolved_profile = (profile or values.get("CONFIG_PROFILE") or "").strip().lower() or None
    ctx = Context(
        values=dict(values),
        profile=resolved_profile,
        pack_dir=pack_dir,
        from_file=from_file,
        duplicates=dict(duplicates or {}),
    )
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(ctx))
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    findings.sort(key=lambda finding: order[finding.level])
    return Result(
        profile=resolved_profile,
        variable_count=len(values),
        domains=ctx.domains,
        findings=findings,
    )


# --- output -----------------------------------------------------------------------


def render(result: Result, *, source: str) -> str:
    profile = result.profile or "sem perfil"
    lines = [
        f"config validate: {source}, perfil {profile}, {result.variable_count} variavel(is), "
        f"{len(result.domains)} dominio(s) no pacote",
    ]
    for finding in result.findings:
        lines.append(f"{LEVEL_LABEL[finding.level]} {finding.name}: {finding.message}")
    errors, warnings = result.count(ERROR), result.count(WARNING)
    if errors:
        verdict = "corrija os erros e rode de novo"
    elif warnings:
        verdict = "pode subir; revise os avisos"
    else:
        verdict = "configuracao pronta"
    lines.append(f"resultado: {errors} erro(s), {warnings} aviso(s); {verdict}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, *, stdin: io.TextIOBase | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.config_validate",
        description="Explica o que falta na configuracao, sem imprimir valores.",
    )
    parser.add_argument("--env-file", help="arquivo .env a validar; '-' le da entrada padrao")
    parser.add_argument("--profile", choices=PROFILES, help="perfil a cobrar (padrao: CONFIG_PROFILE)")
    parser.add_argument("--domains-path", help="pasta do pacote do cliente, se nao for a do .env")
    parser.add_argument("--strict", action="store_true", help="avisos tambem falham (saida 1)")
    args = parser.parse_args(argv)

    duplicates: dict[str, int] = {}
    if args.env_file:
        try:
            if args.env_file == "-":
                text = (stdin or sys.stdin).read()
                source = "entrada padrao"
            else:
                text = Path(args.env_file).read_text(encoding="utf-8")
                source = args.env_file
        except (OSError, UnicodeDecodeError):
            print(f"config validate: nao consegui ler {args.env_file}", file=sys.stderr)
            return EXIT_UNREADABLE
        values, duplicates = parse_env_text(text)
        from_file = True
    else:
        values = environment_values(os.environ)
        source = "ambiente do processo"
        from_file = False

    result = validate(
        values,
        pack_dir=resolve_pack_dir(values, os.environ, args.domains_path),
        profile=args.profile,
        from_file=from_file,
        duplicates=duplicates,
    )
    sys.stdout.write(render(result, source=source))
    return result.exit_code(strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
