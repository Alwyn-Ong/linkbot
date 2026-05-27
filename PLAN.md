# Implementation Plan

## Phase 1 — Core pipeline

- [ ] `bot.py` — Telegram bot entry point, long-polling handler
- [ ] `scraper.py` — Jina Reader fetch (`r.jina.ai/<url>`) → returns clean markdown text
- [ ] `extractor.py` — Gemini call to extract structured JSON from scraped text
  - Fields: name, type, address, hours, date, tags, price_range, description
  - Prompt handles restaurants, events, articles, and generic places
- [ ] `vault.py` — writes/reads Obsidian markdown notes with YAML frontmatter
- [ ] `.env.example` + `requirements.txt`

## Phase 2 — Confirmation flow

- [ ] After extraction, bot sends formatted preview to user
- [ ] User replies `ok` to save, or types corrections (e.g. "hours are 6pm-10pm")
- [ ] Second Gemini call merges correction into the extracted JSON
- [ ] Then saves to vault

## Phase 3 — Query

- [ ] Detect when incoming message is a query vs a URL
- [ ] Load all notes from vault as JSON
- [ ] Gemini call: system prompt with full dataset + user query → formatted response
- [ ] Return to Telegram chat

## Phase 4 — Polish

- [ ] Fallback for login-walled pages (Instagram/TikTok): extract from Open Graph meta only
- [ ] `/list` command — show last N saved entries
- [ ] `/delete <name>` command — remove a note
- [ ] Auto-start on Windows login via Task Scheduler (wsl python ~/code/linkbot/bot.py)
- [ ] Error handling for bad URLs, Jina failures, Gemini rate limits

## Key decisions

- **No always-on server required** — Telegram queues messages; bot processes on next start
- **Gemini free tier** — 1500 req/day, well above expected usage; keeps API billing separate from Claude Code subscription
- **Obsidian over SQLite** — human-readable, editable by hand, browsable on mobile via Obsidian app, already in user's workflow
- **Jina Reader over direct scraping** — handles JS-heavy pages, no browser dependency, free
