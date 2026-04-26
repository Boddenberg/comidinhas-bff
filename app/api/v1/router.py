from fastapi import APIRouter

from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.google_places import router as google_places_router
from app.api.v1.routes.grupos import router as grupos_router
from app.api.v1.routes.hello import router as hello_router
from app.api.v1.routes.home import router as home_router
from app.api.v1.routes.lugares import router as lugares_router

router = APIRouter()
router.include_router(hello_router, tags=["hello"])
router.include_router(chat_router)
router.include_router(google_places_router)
router.include_router(grupos_router)
router.include_router(lugares_router)
router.include_router(home_router)
