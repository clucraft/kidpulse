<p align="center">
  <img src="src/web/static/icon.svg" alt="KidPulse Logo" width="120" height="120">
</p>

<h1 align="center">KidPulse</h1>

<p align="center">
  Daily event scraper and notification system for Playground (tryplayground.com) childcare app.
</p>

## Features

### Event Tracking
- **Bottle feedings** - milk type, ounces offered/consumed
- **Diaper changes** - wet/BM, notes
- **Nap times** - start, end, duration, sleep position
- **Fluids intake** - ounces, meal association
- **Meals** - food items, meal type (breakfast/lunch/snack)
- **Check-in/out times** - arrival and departure

### Notifications
- **NTFY** - lightweight push notifications
- **Telegram** - rich formatted messages with emojis
- Daily summary at configurable time
- Manual scrapes are silent by default

### Web Dashboard
- View daily summaries for all children
- **Date picker** with Today/Yesterday quick buttons
- **Trends charts** (last 14 days):
  - Nap duration over time
  - Diaper counts (wet vs BM)
  - Bottle & fluid intake
  - Meal counts
- Switch between children with tabs
- Trigger manual scrapes
- View scrape history and status

### REST API
- Full JSON API for integrations
- Works with Grafana, Home Assistant, etc.
- Historical data access

### Multi-Child Support
- Handles multiple children automatically
- Classroom-based event filtering (Infant, Toddler, Older, etc.)
- Separate data tracking per child

### Deployment
- Docker support (Unraid compatible)
- Persistent sessions to minimize logins
- Configurable timezone support
- SQLite database for historical data

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

Access the dashboard at `http://localhost:8080`

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
| `AUTH_ENABLED` | Enable dashboard login protection | `false` |
| `AUTH_USERNAME` | Dashboard login username | `admin` |
| `AUTH_PASSWORD` | Dashboard login password | Required if auth enabled |
| `AUTH_SECRET` | Secret key for signing tokens (auto-generated if not set) | - |
| `BASE_URL` | Public URL for magic links in notifications | `http://localhost:8080` |
| `SUMMARY_TIME` | Time to send daily summary (24h format) | `17:00` |
| `SCRAPE_INTERVAL` | Minutes between scrapes (0 to disable) | `30` |
| `TZ` | Timezone (e.g., `America/Indiana/Indianapolis`) | `America/New_York` |
| `RUN_ON_STARTUP` | Run scrape immediately on start | `false` |
| `DEBUG` | Enable debug logging | `false` |
| `WEB_PORT` | Web UI/API port | `8080` |
| `AI_ENABLED` | Use AI for parsing (experimental) | `false` |
| `AI_PROVIDER` | AI provider: `ollama` or `openai` | `ollama` |
| `OLLAMA_URL` | Ollama server URL | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | Ollama model to use | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API key (if using OpenAI) | - |
| `OPENAI_MODEL` | OpenAI model to use | `gpt-4o-mini` |

## Web Dashboard

Access at `http://localhost:8080` (or your configured port).

### Daily View
- Summary cards for each child
- Sign in/out times
- All events with timestamps
- Totals for bottles, diapers, nap minutes, meals

### Date Navigation
- **Today** / **Yesterday** quick buttons
- Date picker for any historical date
- Data persists in SQLite database

### Trends Section
- **Nap Duration** - Line chart of daily sleep totals
- **Diapers** - Stacked bar chart (wet vs BM)
- **Bottles & Fluids** - Line chart of daily intake (oz)
- **Meals** - Bar chart of meals per day
- Switch between children with tabs

## REST API

All endpoints return JSON.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Scraper status, last run, next scheduled |
| `/api/summary/today` | GET | Today's summary data |
| `/api/summary/{date}` | GET | Summary for specific date (YYYY-MM-DD) |
| `/api/history` | GET | List of dates with available data |
| `/api/scrape-log` | GET | Recent scrape history |
| `/api/scrape` | POST | Trigger manual scrape (silent by default) |
| `/api/children` | GET | List of all children |
| `/api/stats/{child_name}` | GET | Historical stats for charts (14 days) |

### Examples

```bash
# Get today's data
curl http://localhost:8080/api/summary/today

# Get specific date
curl http://localhost:8080/api/summary/2026-01-29

# Trigger scrape with notifications
curl -X POST "http://localhost:8080/api/scrape?notify=true"

# Get child stats for charts
curl http://localhost:8080/api/stats/Ezra%20Aschenberg?days=14
```

## AI-Powered Parsing (Experimental)

KidPulse can use AI (LLM) to parse the feed instead of regex. This may be more robust for handling UI changes.

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
Includes emojis for bottles, diapers, naps, meals, and attendance with formatted summaries.

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
4. Mount `./session_data` to persist login sessions and database

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

- Ensure the timezone is set correctly (`TZ` variable)
- Check that the Playground feed shows events for the expected date
- The scraper saves events under their actual date from the event timestamp

### Wrong Child Data

Events are filtered by classroom. The scraper looks for "Recorded by [Classroom]" to match events to children. If your children are in different classrooms (e.g., Infant vs Older), events are automatically separated.

## License

MIT
