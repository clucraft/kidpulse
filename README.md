# KidPulse

Daily event scraper and notification system for Playground (tryplayground.com) childcare app.

## Features

- Scrapes daily events from Playground web portal
- Sends daily summary notifications via:
  - NTFY (push notifications)
  - Telegram
- Runs on a configurable schedule
- Docker support for easy deployment (Unraid compatible)
- Persistent session to minimize logins

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/clucraft/kidpulse.git
cd kidpulse
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
PLAYGROUND_EMAIL=your-email@example.com
PLAYGROUND_PASSWORD=your-password

NTFY_ENABLED=true
NTFY_TOPIC=your-unique-topic

TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id

SUMMARY_TIME=17:00
TZ=America/New_York
```

### 3. Run with Docker Compose

```bash
docker-compose up -d
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `PLAYGROUND_EMAIL` | Your Playground login email | Required |
| `PLAYGROUND_PASSWORD` | Your Playground password | Required |
| `NTFY_ENABLED` | Enable NTFY notifications | `true` |
| `NTFY_SERVER` | NTFY server URL | `https://ntfy.sh` |
| `NTFY_TOPIC` | NTFY topic name | `kidpulse` |
| `TELEGRAM_ENABLED` | Enable Telegram notifications | `false` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Required if enabled |
| `TELEGRAM_CHAT_ID` | Telegram chat ID | Required if enabled |
| `SUMMARY_TIME` | Time to send daily summary (24h) | `17:00` |
| `SCRAPE_INTERVAL` | Scrape interval in minutes | `30` |
| `TZ` | Timezone | `America/New_York` |
| `RUN_ON_STARTUP` | Run scrape immediately on start | `false` |
| `DEBUG` | Enable debug logging | `false` |

## Setting Up Notifications

### NTFY

1. Install the NTFY app on your phone
2. Subscribe to your topic (e.g., `kidpulse`)
3. Set `NTFY_TOPIC` in your `.env` file

### Telegram

1. Create a bot via [@BotFather](https://t.me/botfather)
2. Get your chat ID via [@userinfobot](https://t.me/userinfobot)
3. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your `.env` file

## Unraid Deployment

1. Copy the files to your Unraid appdata folder
2. Create a docker-compose stack or use the Community Applications
3. Configure environment variables via Unraid UI
4. Mount `./session_data` to persist login sessions

## Development

### Local Setup

```bash
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
playwright install chromium
```

### Run Locally

```bash
python -m src.main
```

## Troubleshooting

### Login Issues

If scraping fails, the page structure may have changed. Enable debug mode and check the screenshots:

```env
DEBUG=true
```

### Session Expired

Delete `session_data/storage_state.json` to force a fresh login.

## License

MIT
