from aiogram import Router

from handlers.speakers import router as speakers_router
from handlers.moderation import router as moderation_router

router = Router()
router.include_router(speakers_router)
router.include_router(moderation_router)

__all__ = ["router"]
