"""Main entry point for KidPulse."""

import asyncio
import logging
import signal
import sys
from datetime import datetime

import schedule

from .config import Config
from .scraper import PlaygroundScraper
from .notifiers import NtfyNotifier, TelegramNotifier, NotificationManager

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


async def run_scrape_and_notify(config: Config, notification_manager: NotificationManager) -> None:
    """Run the scraper and send notifications."""
    try:
        async with PlaygroundScraper(config.playground) as scraper:
            # Login
            if not await scraper.login():
                logger.error("Failed to login to Playground")
                await notification_manager.send_raw(
                    "Failed to login to Playground. Please check credentials.",
                    title="KidPulse Error"
                )
                return

            # Get today's events
            summary = await scraper.get_daily_events()

            if summary.event_count == 0:
                logger.info("No events found for today")
                return

            # Send notifications
            results = await notification_manager.send_summary(summary)
            for notifier, success in results.items():
                if success:
                    logger.info(f"Successfully sent notification via {notifier}")
                else:
                    logger.error(f"Failed to send notification via {notifier}")

    except Exception as e:
        logger.exception(f"Error during scrape and notify: {e}")
        await notification_manager.send_raw(
            f"Error: {str(e)}",
            title="KidPulse Error"
        )


def run_scheduled_job(config: Config, notification_manager: NotificationManager) -> None:
    """Wrapper to run async job from sync scheduler."""
    asyncio.run(run_scrape_and_notify(config, notification_manager))


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
    logger.info(f"Scrape interval: {config.scrape_interval} minutes")
    logger.info(f"NTFY enabled: {config.ntfy.enabled}")
    logger.info(f"Telegram enabled: {config.telegram.enabled}")

    # Set up notifiers
    ntfy = NtfyNotifier(config.ntfy) if config.ntfy.enabled else None
    telegram = TelegramNotifier(config.telegram) if config.telegram.enabled else None
    notification_manager = NotificationManager(ntfy=ntfy, telegram=telegram)

    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Send startup notification
    await notification_manager.send_raw(
        f"KidPulse started. Will send daily summary at {config.summary_time}.",
        title="KidPulse Started"
    )

    # Schedule daily summary
    schedule.every().day.at(config.summary_time).do(
        run_scheduled_job, config, notification_manager
    )

    # Also run immediately on startup if requested via environment
    import os
    if os.getenv("RUN_ON_STARTUP", "false").lower() == "true":
        logger.info("Running initial scrape on startup...")
        await run_scrape_and_notify(config, notification_manager)

    # Main loop
    logger.info("Entering main loop...")
    while not shutdown_requested:
        schedule.run_pending()
        await asyncio.sleep(60)  # Check every minute

    # Graceful shutdown
    logger.info("Shutting down...")
    await notification_manager.send_raw("KidPulse shutting down.", title="KidPulse")


def cli() -> None:
    """CLI entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
