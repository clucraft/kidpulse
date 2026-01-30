# KidPulse

Daily event scraper and notification system for Playground (tryplayground.com) childcare app.

## Features

- Scrapes daily events from Playground web portal:
  - Bottle feedings (milk type, ounces offered/consumed)
  - Diaper changes (wet/BM, notes)
  - Nap times (start, end, duration, position)
  - Fluids intake
  - Check-in/out times
- Sends daily summary notifications via:
  - NTFY (push notifications)
  - Telegram
- Supports multiple children
- Runs on a configurable schedule
- **Web dashboard** for viewing data
- **REST API** for integrations (Grafana, Home Assistant, etc.)
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
# Get from your Playground URL: https://app.tryplayground.com/app/YOUR_ORG_ID/parent/feed
PLAYGROUND_ORGANIZATION=YOUR_ORG_ID

NTFY_ENABLED=true
NTFY_TOPIC=your-unique-topic

TELEGRAM_ENABLED=false
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
| `PLAYGROUND_ORGANIZATION` | Organization ID from your Playground URL | Required |
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
| `WEB_PORT` | Web UI/API port | `8080` |
| `AI_ENABLED` | Use AI for parsing (more robust) | `false` |
| `AI_PROVIDER` | AI provider: `ollama` or `openai` | `ollama` |
| `OLLAMA_URL` | Ollama server URL | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | Ollama model to use | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API key (if using OpenAI) | - |
| `OPENAI_MODEL` | OpenAI model to use | `gpt-4o-mini` |

## AI-Powered Parsing

KidPulse supports using AI (LLM) to parse the feed instead of regex. This is more robust and handles UI changes automatically.

### Using Ollama (Local, Free)

1. Install [Ollama](https://ollama.ai)
2. Pull a model: `ollama pull qwen3:8b`
3. Enable in your `.env`:
   ```env
   AI_ENABLED=true
   AI_PROVIDER=ollama
   OLLAMA_URL=http://host.docker.internal:11434
   OLLAMA_MODEL=qwen3:8b
   ```

### Using OpenAI

1. Get an API key from [OpenAI](https://platform.openai.com)
2. Enable in your `.env`:
   ```env
   AI_ENABLED=true
   AI_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-4o-mini
   ```

## Web Dashboard

Access the web UI at `http://localhost:8080` (or your configured port).

Features:
- View today's summary for all children
- Browse historical data by date
- Trigger manual scrapes
- See scrape status and history

## REST API

All endpoints return JSON.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Scraper status, last run, next scheduled |
| `/api/summary/today` | GET | Today's summary data |
| `/api/summary/{date}` | GET | Summary for specific date (YYYY-MM-DD) |
| `/api/history` | GET | List of dates with available data |
| `/api/scrape-log` | GET | Recent scrape history |
| `/api/scrape` | POST | Trigger manual scrape |

### Example: Get today's data

```bash
curl http://localhost:8080/api/summary/today
```

### Example: Trigger scrape without notifications

```bash
curl -X POST "http://localhost:8080/api/scrape?notify=false"
```

## Notification Examples

### NTFY
```
=== Ezra ===

Arrived: 08:15 AM
Left: 03:58 PM

Bottles (2):
  11:35 AM - Breast milk: 3.5oz consumed
  02:18 PM - Breast milk: 3.6oz consumed
  Total: 7.1oz

Diapers (3):
  12:36 PM - BM - Very watery
  01:05 PM - Wet
  03:06 PM - Wet
  Summary: 2 wet, 1 BM

Naps (1):
  01:18 PM - 01:38 PM (20 min) - Back
  Total: 20 minutes
```

### Telegram
Includes emojis for bottles, diapers, naps, and attendance with formatted summaries.

## Setting Up Notifications

### NTFY

1. Install the NTFY app on your phone ([iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy))
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

Screenshots are saved to `session_data/` directory.

### Session Expired

Delete `session_data/storage_state.json` to force a fresh login.

### No Events Found

The scraper looks for events from today's date. If the Playground page structure changes, the CSS selectors in `src/scraper.py` may need to be updated.

## License

MIT
