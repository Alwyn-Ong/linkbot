# linkbot

A Telegram bot that saves links from mobile (Instagram, TikTok, web articles), extracts structured data using an LLM, stores entries in Obsidian, and answers natural language queries.

## What it does

1. **Save**: Share any link from mobile via Telegram's share sheet → bot scrapes and extracts structured info
2. **Confirm**: Bot shows extracted data for review before saving; user can correct fields inline
3. **Store**: Each entry is saved as a markdown note with YAML frontmatter in an Obsidian vault
4. **Query**: Ask the bot natural language questions ("Japanese restaurants", "free events this weekend") → bot returns matching entries

## Architecture

```
mobile share sheet
      ↓
Telegram bot (Python, long-polling)
      ↓
Jina Reader (r.jina.ai/<url>) — page → clean markdown
      ↓
Gemini API (gemini-2.0-flash) — extract structured JSON
      ↓
Obsidian vault — one .md note per entry, YAML frontmatter
      ↑
Telegram query — bot reads vault files → Gemini → formatted response
```

## Note schema

Each entry is a markdown file under `vault/Links/` with frontmatter:

```yaml
---
name: Sushi Jiro
type: restaurant          # restaurant | event | article | place
address: 123 Orchard Rd
hours: 6pm–10pm
date:                     # for events
tags: [japanese, omakase]
price_range: $$
source: https://...
saved: 2026-05-27
---
Free-text notes or description here.
```

## Stack

- **Bot framework**: python-telegram-bot
- **Scraping**: Jina Reader API (free, no key needed)
- **LLM**: Gemini 2.0 Flash via Google AI Studio (free tier)
- **Storage**: Obsidian vault (markdown files)
- **Runtime**: local machine (runs when computer is on; Telegram queues messages when offline)

## Setup

```bash
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN and GEMINI_API_KEY

pip install -r requirements.txt
python bot.py
```

## Environment variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather on Telegram |
| `GEMINI_API_KEY` | From aistudio.google.com |
| `OBSIDIAN_VAULT_PATH` | Absolute path to your Obsidian vault |
| `OBSIDIAN_LINKS_FOLDER` | Subfolder within vault for link notes (default: `Links`) |
