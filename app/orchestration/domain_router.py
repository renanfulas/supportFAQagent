"""Channel domain routing by keyword and natural greeting.

Selects which domain should answer an inbound conversational message when a single
channel (for example one WhatsApp number) serves more than one domain, such as
``suporte-vps-whatsapp`` and ``vendas``.

This is a pure, deterministic, stateless seam:

- an explicit selection (a number or an option name, kept as hidden shortcuts)
  picks that domain;
- otherwise the message is scored against each domain's routing keywords and the
  unique best match wins;
- when nothing matches (greeting, ambiguous, or a tie) the caller is told to send
  the fallback text: the institutional greeting on first contact, or the
  clarification question when the conversation is already past the greeting
  (see ``fallback_routing_text`` in ``channel_routing``).

Stateless on purpose: it does not remember a previous choice across messages.
Sticky session memory (remember the chosen domain per conversation) is a follow-up
that needs conversation persistence and is intentionally out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.casefold().strip()


@dataclass(frozen=True)
class RoutableDomain:
    name: str
    display_name: str
    keywords: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    welcome: str = ""

    @classmethod
    def from_config(cls, config: object) -> "RoutableDomain":
        name = str(getattr(config, "name"))
        display_name = str(getattr(config, "display_name", name))
        routing = getattr(config, "routing", None)
        keywords = tuple(getattr(routing, "keywords", []) or [])
        response = getattr(config, "response", None)
        welcome = (getattr(response, "welcome_message", None) or "").strip()
        return cls(
            name=name,
            display_name=display_name,
            keywords=keywords,
            welcome=welcome,
        )

    def _alias_tokens(self, position: int) -> set[str]:
        # Conservative on purpose: only the menu position number, the leading word
        # of the display name (e.g. "suporte", "vendas") and any explicit aliases.
        # Generic display words like "vps" or "whatsapp" must NOT become selectors,
        # otherwise they would hijack keyword routing.
        tokens: set[str] = {str(position)}
        display_lead = re.split(r"[\s\-]+", _normalize(self.display_name))
        if display_lead and len(display_lead[0]) >= 3:
            tokens.add(display_lead[0])
        for alias in self.aliases:
            normalized = _normalize(alias)
            if len(normalized) >= 2:
                tokens.add(normalized)
        return tokens


@dataclass(frozen=True)
class RouteDecision:
    domain: str | None
    show_menu: bool
    reason: str


def _join_options(options: list[str]) -> str:
    """Join display names in pt-BR: "A", "A ou B", "A, B ou C"."""
    if not options:
        return "o atendimento"
    if len(options) == 1:
        return options[0]
    return f"{', '.join(options[:-1])} ou {options[-1]}"


def neutral_greeting_text(domains: tuple["RoutableDomain", ...], brand_name: str | None) -> str:
    """Brand-neutral institutional greeting built from the routable domains.

    Used when the installation does not configure its own greeting, so a fresh
    install never introduces itself as another company. Listing the display names
    steers the user toward routable vocabulary.
    """
    who = f"o assistente virtual de {brand_name}" if brand_name else "o assistente virtual"
    options = _join_options([domain.display_name for domain in domains])
    return (
        f"Olá! Sou {who}.\n\n"
        f"Posso te ajudar com {options}. Se precisar, também te encaminho para um "
        "atendente humano.\n\n"
        "Como posso te ajudar?"
    )


def neutral_clarification_text(domains: tuple["RoutableDomain", ...]) -> str:
    options = _join_options([domain.display_name for domain in domains])
    return f"Para eu te direcionar certo: você quer falar sobre {options}?"


@dataclass(frozen=True)
class DomainRouter:
    domains: tuple[RoutableDomain, ...]
    default_domain: str
    # Customer-facing fallback texts for unrouted turns. The greeting introduces
    # the installation and steers toward routable vocabulary; the clarification
    # re-asks without repeating the intro. Numbered selection ("1", "2") keeps
    # working as a hidden shortcut even though the texts show no numbered menu.
    # None = brand-neutral default built from the domains; an installation sets
    # its own copy in ``<DOMAINS_PATH>/installation.yaml`` (never in the core).
    greeting: str | None = None
    clarification: str | None = None
    brand_name: str | None = None

    RESET_TRIGGERS = ("menu", "trocar", "voltar", "recomecar")

    def is_reset(self, text: str) -> bool:
        """True only for a short, explicit navigation command.

        Must not fire when a trigger word merely appears inside a normal sentence
        (e.g. "Quais opcoes voce tem?" is a question, not a menu command).
        """
        normalized = _normalize(text)
        if not normalized:
            return False
        tokens = [token for token in re.split(r"[\s\-]+", normalized) if token]
        if len(tokens) > 3:
            return False
        return any(token in self.RESET_TRIGGERS for token in tokens)

    @classmethod
    def from_domain_configs(
        cls,
        configs: list[object],
        *,
        default_domain: str,
        greeting: str | None = None,
        clarification: str | None = None,
        brand_name: str | None = None,
    ) -> "DomainRouter":
        routable = tuple(RoutableDomain.from_config(c) for c in configs)
        return cls(
            domains=routable,
            default_domain=default_domain,
            greeting=(greeting or "").strip() or None,
            clarification=(clarification or "").strip() or None,
            brand_name=(brand_name or "").strip() or None,
        )

    def route(self, text: str) -> RouteDecision:
        if len(self.domains) <= 1:
            target = self.domains[0].name if self.domains else self.default_domain
            return RouteDecision(domain=target, show_menu=False, reason="single_domain")

        normalized = _normalize(text)
        if not normalized:
            return RouteDecision(domain=None, show_menu=True, reason="menu_prompt")

        selection = self._match_menu_selection(normalized)
        if selection is not None:
            return RouteDecision(domain=selection, show_menu=False, reason="menu_selection")

        keyword_match = self._match_keywords(normalized)
        if keyword_match is not None:
            return RouteDecision(domain=keyword_match, show_menu=False, reason="keyword_match")

        return RouteDecision(domain=None, show_menu=True, reason="menu_prompt")

    def greeting_text(self) -> str:
        return self.greeting or neutral_greeting_text(self.domains, self.brand_name)

    def clarification_text(self) -> str:
        return self.clarification or neutral_clarification_text(self.domains)

    def welcome_text(self, domain_name: str) -> str:
        domain = next((d for d in self.domains if d.name == domain_name), None)
        if domain is not None and domain.welcome:
            return domain.welcome
        display = domain.display_name if domain is not None else domain_name
        return f"Perfeito! Você está no atendimento de {display}. Como posso te ajudar?"

    def _match_menu_selection(self, normalized: str) -> str | None:
        tokens = set(re.split(r"[\s\-]+", normalized))
        for position, domain in enumerate(self.domains, start=1):
            alias_tokens = domain._alias_tokens(position)
            if normalized in alias_tokens or tokens & alias_tokens:
                return domain.name
        return None

    def _shared_keywords(self) -> set[str]:
        """Normalized keywords owned by two or more distinct domains.

        Shared vocabulary (e.g. ``vps`` across the VPS support and sales domains)
        is ambient, not discriminating: counting it only produces ties that bounce
        to the menu and blocks two domains that share a base vocabulary from ever
        routing. Routing ignores it so the domain-specific keywords decide.

        This is router-only. The same shared term stays a valid in-scope signal
        inside an already-selected domain (``HandoffService._has_domain_signal``),
        which is computed independently and is intentionally not changed here.
        """
        owners: dict[str, set[str]] = {}
        for domain in self.domains:
            # dedupe within a domain so a keyword listed twice in one config does
            # not look "shared"; ownership is counted per distinct domain name.
            for keyword in {_normalize(k) for k in domain.keywords}:
                if keyword:
                    owners.setdefault(keyword, set()).add(domain.name)
        return {keyword for keyword, names in owners.items() if len(names) >= 2}

    def _match_keywords(self, normalized: str) -> str | None:
        shared = self._shared_keywords()
        scores: list[tuple[int, str]] = []
        for domain in self.domains:
            score = sum(
                1
                for keyword in domain.keywords
                if (normalized_keyword := _normalize(keyword)) not in shared
                and self._contains_word(normalized, normalized_keyword)
            )
            scores.append((score, domain.name))

        scores.sort(reverse=True)
        if not scores or scores[0][0] == 0:
            return None
        if len(scores) > 1 and scores[0][0] == scores[1][0]:
            return None
        return scores[0][1]

    @staticmethod
    def _contains_word(text: str, keyword: str) -> bool:
        if not keyword:
            return False
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
