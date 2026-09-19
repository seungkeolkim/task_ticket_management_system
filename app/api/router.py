from fastapi import APIRouter

from app.api.routes import auth, health
from app.api.routes.administration import router as administration_router
from app.api.routes.projects import router as projects_router

api_router = APIRouter()
api_router.include_router(administration_router)
api_router.include_router(projects_router)
api_router.include_router(health.router)
api_router.include_router(auth.router)
