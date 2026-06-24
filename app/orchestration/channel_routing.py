"""Shared domain routing + sticky memory for conversational channels.

Both the Meta WhatsApp transport and the temporary Hermes chat transport answer
more than one domain (support and sales) on a single number. This module holds the
channel-agnostic glue so the routing/stickiness rules live in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.domain_engine.loader import DomainLoader
from app.orchestration.domain_router import DomainRouter
from app.orchestration.session_domain_store import SessionDomainStore


@dataclass(frozen=True)
class RouteResolution:
    domain: str | None
    show_menu: bool = False
    selected: bool = False


def build_domain_router(
    settings: Settings,
    domain_loader: DomainLoader,
) -> DomainRouter | None:
    """Build the router from settings, or None when routing is disabled/single."""
    if not settings.enable_whatsapp_domain_router:
        return None
    configs = [
        config
        for name in settings.whatsapp_router_domain_list
        if (config := domain_loader.load(name)) is not None
    ]
    if len(configs) <= 1:
        return None
    return DomainRouter.from_domain_configs(
        configs,
        default_domain=settings.default_domain,
    )


def resolve_sticky_domain(
    *,
    router: DomainRouter | None,
    store: SessionDomainStore | None,
    default_domain: str,
    text: str,
    session_id: str,
) -> RouteResolution:
    """Decide how to handle an inbound message.

    Stickiness: a menu selection or keyword match (re)binds the session to that
    domain; a generic follow-up keeps the bound domain; a reset trigger drops the
    binding and shows the menu. A bare menu selection (e.g. "2") must NOT be fed to
    the brain — it is only a chooser — so it is flagged ``selected`` for a welcome.
    """
    if router is None:
        return RouteResolution(domain=default_domain)

    if store is not None and router.is_reset(text):
        store.clear(session_id)
        return RouteResolution(domain=None, show_menu=True)

    decision = router.route(text)
    intentful = {"menu_selection", "keyword_match", "single_domain"}
    if decision.domain is not None and decision.reason in intentful:
        if store is not None:
            store.set(session_id, decision.domain)
        return RouteResolution(
            domain=decision.domain,
            selected=decision.reason == "menu_selection",
        )

    if store is not None:
        sticky = store.get(session_id)
        if sticky is not None:
            return RouteResolution(domain=sticky)

    if decision.domain is None:
        return RouteResolution(domain=None, show_menu=True)
    return RouteResolution(domain=decision.domain)
