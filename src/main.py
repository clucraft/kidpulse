"""Main entry point for KidPulse."""

import asyncio
import logging
import signal
import sys
import os
from datetime import datetime
from contextlib import asynccontextmanager

import uvicorn
import schedule

from .config import Config
from .scraper import PlaygroundScraper
from .notifiers import NtfyNotifier, TelegramNotifier, NotificationManager
from .web import storage
from .web.api import app, set_config, set_next_scrape_time, run_scrape

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global shutdown_requested
    logger.info("Shutdown requested...")
    shutdown_requested = True


async def run_scheduled_scrape(config: Config, notify: bool = True) -> None:
    """Run the scheduled scrape task."""
    logger.info(f"Running scheduled scrape (notify={notify})...")
    await run_scrape(notify=notify)


async def scheduler_loop(config: Config) -> None:
    """Run the scheduler loop."""
    global shutdown_requested

    # Schedule daily summary (with notifications)
    schedule.every().day.at(config.summary_time).do(
        lambda: asyncio.create_task(run_scheduled_scrape(config, notify=True))
    )

    # Schedule interval scrapes (silent - no notifications)
    if config.scrape_interval > 0:
        schedule.every(config.scrape_interval).minutes.do(
            lambda: asyncio.create_task(run_scheduled_scrape(config, notify=False))
        )
        logger.info(f"Scheduler started. Scraping every {config.scrape_interval} minutes, daily summary at {config.summary_time}")
        set_next_scrape_time(f"Every {config.scrape_interval}min, summary at {config.summary_time}")
    else:
        logger.info(f"Scheduler started. Daily summary at {config.summary_time} (interval scraping disabled)")
        set_next_scrape_time(config.summary_time)

    # Run immediately on startup if requested
    if os.getenv("RUN_ON_STARTUP", "false").lower() == "true":
        logger.info("Running initial scrape on startup...")
        await run_scrape(notify=False)

    # Main scheduler loop
    while not shutdown_requested:
        schedule.run_pending()
        await asyncio.sleep(60)  # Check every minute


async def main() -> None:
    """Main entry point."""
    global shutdown_requested

    # Load and validate config
    config = Config.from_env()
    errors = config.validate()

    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        sys.exit(1)

    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("KidPulse starting up...")
    logger.info(f"Summary time: {config.summary_time}")
    logger.info(f"Scrape interval: {config.scrape_interval} minutes" if config.scrape_interval > 0 else "Scrape interval: disabled")
    logger.info(f"Auth enabled: {config.auth.enabled} (raw env: AUTH_ENABLED={os.getenv('AUTH_ENABLED', 'NOT SET')})")
    logger.info(f"NTFY enabled: {config.ntfy.enabled}")
    logger.info(f"Telegram enabled: {config.telegram.enabled}")

    # Initialize database
    await storage.init_db()

    # Set config for web API
    set_config(config)

    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Always use port 8080 inside container (WEB_PORT only controls host mapping)
    web_port = 8080

    # Create uvicorn server
    uvicorn_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=web_port,
        log_level="info" if not config.debug else "debug",
    )
    server = uvicorn.Server(uvicorn_config)

    # Send startup notification
    ntfy = NtfyNotifier(config.ntfy) if config.ntfy.enabled else None
    telegram = TelegramNotifier(config.telegram) if config.telegram.enabled else None
    notification_manager = NotificationManager(ntfy=ntfy, telegram=telegram)

    interval_msg = f"Scraping every {config.scrape_interval} min\n" if config.scrape_interval > 0 else ""
    await notification_manager.send_raw(
        f"KidPulse started.\n{interval_msg}Daily summary at {config.summary_time}\nWeb UI: http://localhost:{web_port}",
        title="KidPulse Started"
    )

    logger.info(f"Web UI available at http://localhost:{web_port}")

    # Run both scheduler and web server
    try:
        await asyncio.gather(
            scheduler_loop(config),
            server.serve(),
        )
    except asyncio.CancelledError:
        pass

    # Graceful shutdown
    logger.info("Shutting down...")
    await notification_manager.send_raw("KidPulse shutting down.", title="KidPulse")


def cli() -> None:
    """CLI entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
