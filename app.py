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
    await bot.set_webhook(webhook_url)
    logger.info("Webhook set to %s", webhook_url)


async def on_shutdown(bot: Bot):
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Webhook deleted")


async def main():
    settings = get_settings()

    bot = Bot(token=settings.bot_token)
    dp = build_dispatcher(settings)

    app = web.Application()

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    # вместо dp.startup.register(...)
    await on_startup(bot, dp, settings.webhook_url)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)
    await site.start()

    logger.info("Bot started on port %s", settings.port)

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await on_shutdown(bot)

if __name__ == "__main__":
    asyncio.run(main())
