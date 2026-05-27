# Considered Alternatives

## Input method

| Option | Reason considered | Reason not chosen |
|---|---|---|
| **Google Keep** | User's original idea; easy mobile sharing | No official API; unofficial `gkeepapi` library is fragile and breaks periodically |
| **Google Sheets** | Good API, familiar UI | Less natural share-sheet flow; querying is awkward |
| **Email (dedicated Gmail)** | Simple, universal | Slower feedback loop; more complex inbox parsing |
| **Notion** | Good API, mobile share extension, rich UI | Heavier setup; adds another subscription surface |
| ✅ **Telegram bot** | Native share sheet on iOS/Android; same app for input and query; messages queue when bot is offline | — |

## Storage / query layer

| Option | Reason considered | Reason not chosen |
|---|---|---|
| **SQLite** | Simple, fast, no dependencies | No visual browsing; no mobile access without extra tooling |
| **Notion database** | Rich UI, filters, mobile app | Adds another app; data lives in a third-party cloud |
| **Google Sheets** | Familiar, filterable | Poor natural language query experience |
| ✅ **Obsidian vault** | Already in user's workflow; human-readable files; Dataview for visual queries; mobile app; editable by hand | — |

## LLM for extraction and querying

| Option | Reason considered | Reason not chosen |
|---|---|---|
| **Claude API (Anthropic)** | Best reasoning quality | Separate billing from claude.ai subscription; ~$0.50/mo but adds another billing relationship |
| **Claude Code subprocess** (`claude -p`) | Uses existing Claude Code subscription; zero extra cost | Subprocess overhead; shares rate limits with interactive coding usage; feels like a hack |
| **Local model (Ollama)** | Free, offline, private | Unreliable at structured JSON extraction at small model sizes (3B); 7B+ occupies 5-6GB RAM constantly; setup complexity not worth saving ~$0.50/mo |
| ✅ **Gemini 2.0 Flash (free tier)** | Free, dedicated quota (1500 req/day), reliable at structured extraction, clean API, doesn't interfere with Claude Code usage | — |

## Scraping approach

| Option | Reason considered | Reason not chosen |
|---|---|---|
| **Direct HTML scraping (BeautifulSoup)** | Simple, no external dependency | Breaks on JS-heavy pages; Instagram/TikTok block it entirely |
| **Playwright/Puppeteer** | Handles JS rendering | Heavy dependency; overkill; still blocked by Instagram/TikTok login walls |
| ✅ **Jina Reader** (`r.jina.ai/<url>`) | Free, no key needed, handles JS pages, returns clean markdown | Login-walled pages (Instagram, TikTok) still return partial data — falls back to Open Graph metadata |

## Hosting / runtime

| Option | Reason considered | Reason not chosen |
|---|---|---|
| **Always-on VPS** (~$5/mo, e.g. Hetzner/DigitalOcean) | Bot always responsive; no dependency on local machine | Extra cost and maintenance; unnecessary given Telegram's message queuing |
| **Raspberry Pi** | One-time cost (~$35), low power, always-on at home | More setup than needed for initial version |
| ✅ **Local machine (run when computer is on)** | Zero extra cost or setup; Telegram queues messages when offline; query unavailable when machine is off but acceptable | — |
