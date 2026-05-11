from fastapi import APIRouter

from app.core.config import get_settings
from app.domain_engine.loader import DomainLoader


router = APIRouter()


@router.get("")
def list_domains() -> dict[str, list[str]]:
    settings = get_settings()
    loader = DomainLoader(settings.domains_path)
    return {"domains": loader.list_domains()}
