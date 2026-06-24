"""Channel domain routing by keyword and initial menu.

Selects which domain should answer an inbound conversational message when a single
channel (for example one WhatsApp number) serves more than one domain, such as
``suporte-vps-whatsapp`` and ``vendas``.

This is a pure, deterministic, stateless seam:

- an explicit menu selection (a number or an option name) picks that domain;
- otherwise the message is scored against each domain's routing keywords and the
  unique best match wins;
- when nothing matches (greeting, ambiguous, or a tie) the caller is told to show
  the menu.

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

    @classmethod
    def from_config(cls, config: object) -> "RoutableDomain":
        name = str(getattr(config, "name"))
        display_name = str(getattr(config, "display_name", name))
        routing = getattr(config, "routing", None)
        keywords = tuple(getattr(routing, "keywords", []) or [])
        return cls(name=name, display_name=display_name, keywords=keywords)

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


@dataclass(frozen=True)
class DomainRouter:
    domains: tuple[RoutableDomain, ...]
    default_domain: str
    menu_intro: str = "Ola! Posso te ajudar com:"
    menu_outro: str = "Responda com o numero ou o nome da opcao."

    MENU_TRIGGERS = ("menu", "opcoes", "opcao", "ajuda", "oi", "ola", "inicio")

    @classmethod
    def from_domain_configs(
        cls,
        configs: list[object],
        *,
        default_domain: str,
        menu_intro: str | None = None,
        menu_outro: str | None = None,
    ) -> "DomainRouter":
        routable = tuple(RoutableDomain.from_config(c) for c in configs)
        kwargs: dict[str, object] = {"domains": routable, "default_domain": default_domain}
        if menu_intro is not None:
            kwargs["menu_intro"] = menu_intro
        if menu_outro is not None:
            kwargs["menu_outro"] = menu_outro
        return cls(**kwargs)  # type: ignore[arg-type]

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

    def menu_text(self) -> str:
        lines = [self.menu_intro]
        for position, domain in enumerate(self.domains, start=1):
            lines.append(f"{position}) {domain.display_name}")
        lines.append(self.menu_outro)
        return "\n".join(lines)

    def _match_menu_selection(self, normalized: str) -> str | None:
        tokens = set(re.split(r"[\s\-]+", normalized))
        for position, domain in enumerate(self.domains, start=1):
            alias_tokens = domain._alias_tokens(position)
            if normalized in alias_tokens or tokens & alias_tokens:
                return domain.name
        return None

    def _match_keywords(self, normalized: str) -> str | None:
        scores: list[tuple[int, str]] = []
        for domain in self.domains:
            score = sum(
                1
                for keyword in domain.keywords
                if self._contains_word(normalized, _normalize(keyword))
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
