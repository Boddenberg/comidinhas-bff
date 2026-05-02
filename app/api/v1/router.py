from fastapi import APIRouter

from app.api.v1.routes.chat import router as chat_router
from app.api.v1.routes.google_places import router as google_places_router
from app.api.v1.routes.guias import router as guias_router
from app.api.v1.routes.guias_ai import router as guias_ai_router
from app.api.v1.routes.groups import router as groups_router
from app.api.v1.routes.grupos import router as grupos_router
from app.api.v1.routes.hello import router as hello_router
from app.api.v1.routes.home import router as home_router
from app.api.v1.routes.ia import router as ia_router
from app.api.v1.routes.infobip import router as infobip_router
from app.api.v1.routes.lugares import router as lugares_router
from app.api.v1.routes.perfis import router as perfis_router
from app.api.v1.routes.places import router as places_router
from app.api.v1.routes.profiles import router as profiles_router
from app.api.v1.routes.recommendations import router as recommendations_router

router = APIRouter()
router.include_router(hello_router, tags=["hello"])
router.include_router(chat_router)
router.include_router(ia_router)
router.include_router(google_places_router)
router.include_router(infobip_router)
router.include_router(profiles_router)
router.include_router(groups_router)
router.include_router(places_router)
router.include_router(perfis_router)
router.include_router(grupos_router)
router.include_router(lugares_router)
router.include_router(guias_ai_router)
router.include_router(guias_router)
router.include_router(home_router)
router.include_router(recommendations_router)
