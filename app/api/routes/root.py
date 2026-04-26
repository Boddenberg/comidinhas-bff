from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["root"])


@router.get("/", summary="Informacoes basicas do servico")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
    }

