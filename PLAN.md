# Implementation Plan

## Phase 1 — Core pipeline

- [x] `bot.py` — Telegram bot entry point, long-polling handler
- [x] `scraper.py` — Jina Reader fetch (`r.jina.ai/<url>`) → returns clean markdown text
- [x] `extractor.py` — Gemini call to extract structured JSON from scraped text
  - Fields: name, type, address, hours, date, tags, price_range, description
  - Prompt handles restaurants, events, articles, and generic places
- [x] `vault.py` — writes/reads Obsidian markdown notes with YAML frontmatter
- [x] `.env.example` + `requirements.txt`

## Phase 2 — Confirmation flow

- [x] After extraction, bot sends formatted preview to user
- [x] User replies `ok` to save, or types corrections (e.g. "hours are 6pm-10pm")
- [x] Second Gemini call merges correction into the extracted JSON
- [x] Then saves to vault

## Phase 3 — Query

- [x] Detect when incoming message is a query vs a URL
- [x] Load all notes from vault as JSON
- [x] Gemini call: system prompt with full dataset + user query → formatted response
- [x] Return to Telegram chat

## Phase 4 — Polish

- [ ] Fallback for login-walled pages (Instagram/TikTok): extract from Open Graph meta only
- [x] `/list` command — show last N saved entries
- [x] `/delete <name>` command — remove a note
- [ ] Auto-start on Windows login via Task Scheduler (wsl python ~/code/linkbot/bot.py)
- [x] Error handling for bad URLs, Jina failures, Gemini rate limits

## Phase 5 — Extras (added during implementation)

- [x] User ID allowlist — only authorised Telegram user can interact with bot
- [x] Notes split into subfolders by type (restaurant, event, article, place)
- [x] `visited` field on every note (default false)
- [x] Duplicate detection — warns if entry already exists
- [x] Hours enrichment — DuckDuckGo search fallback when hours are missing
- [x] Gemini model fallback — auto-switches to `gemini-3.1-flash-lite` (500 RPD) on rate limit
- [x] `/plan` command — multi-turn date planner (meal, date, area, budget → itinerary)
- [x] Query prioritisation — unvisited places first; ongoing events first
- [x] Proper YAML serialisation via PyYAML (fixes colon-in-value corruption)

## Key decisions

- **No always-on server required** — Telegram queues messages; bot processes on next start
- **Gemini free tier** — `gemini-2.5-flash` primary, `gemini-3.1-flash-lite` fallback (500 RPD)
- **Obsidian over SQLite** — human-readable, editable by hand, browsable on mobile via Obsidian app, already in user's workflow
- **Jina Reader over direct scraping** — handles JS-heavy pages, no browser dependency, free
