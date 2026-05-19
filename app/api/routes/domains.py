from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.security import verify_api_key
from app.domain_engine.loader import DomainLoader


router = APIRouter()


@router.get("")
def list_domains(_: str = Depends(verify_api_key)) -> dict[str, list[str]]:
    settings = get_settings()
    loader = DomainLoader(settings.domains_path)
    return {"domains": loader.list_domains()}
