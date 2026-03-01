import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config.settings import get_settings
from handlers import router


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_dispatcher(settings):
    dp = Dispatcher()
    dp.include_router(router)
    dp.workflow_data["settings"] = settings
    return dp


async def on_startup(bot: Bot, dp: Dispatcher, webhook_url: str):
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info("Webhook set to %s", webhook_url)


async def on_shutdown(bot: Bot):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Webhook deleted")


async def run_webhook(bot: Bot, dp: Dispatcher, webhook_url: str, port: int) -> None:
    app = web.Application()

    async def health_handler(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/health", health_handler)

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    await on_startup(bot, dp, webhook_url)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    logger.info("Webhook server started on port %s", port)

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await on_shutdown(bot)


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    logger.warning("Running in polling mode")
    await dp.start_polling(bot)


async def main():
    settings = get_settings()

    bot = Bot(token=settings.bot_token)
    dp = build_dispatcher(settings)

    logger.info("Starting bot. Webhook URL: %s", settings.webhook_url or "<empty>")

    if not settings.webhook_url:
        await run_polling(bot, dp)
        return

    try:
        await run_webhook(bot, dp, settings.webhook_url, settings.port)
    except Exception:
        logger.exception("Webhook failed, falling back to polling")
        await run_polling(bot, dp)

if __name__ == "__main__":
    asyncio.run(main())
