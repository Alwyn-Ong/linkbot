import json
import logging
import os
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
_model = genai.GenerativeModel("gemini-2.5-flash")
_fallback_model = genai.GenerativeModel("gemini-3.1-flash-lite")

_EXTRACT_PROMPT = """\
Extract structured information from the following web page content.
Return ONLY a valid JSON object with these fields (use null for missing fields):
- name: string — title or name of the place/event/article
- type: string — one of: restaurant, event, article, place
- address: string
- hours: string — opening hours
- date: string — for events, the date(s); null otherwise
- tags: array of 2-5 concise tags — use specific, useful categories like cuisine type (e.g. "japanese", "omakase"), meal type (e.g. "brunch", "supper"), vibe (e.g. "date-spot", "casual"), or neighbourhood (e.g. "orchard", "cbd"); never use country names or broad regions; ignore hashtags from the source post
- price_range: string — e.g. $, $$, $$$; null if unknown
- description: string — 1-3 sentence summary

Source URL: {url}

Page content:
{text}"""

_MERGE_PROMPT = """\
You have extracted structured data from a web page. The user has provided a correction.
Apply the correction to the JSON and return the updated JSON only. If the correction implies a completely different entry, replace all relevant fields. Only preserve fields the correction clearly doesn't contradict.

Current data:
{current}

User correction: {correction}

Return ONLY the updated JSON object."""

_PLAN_PROMPT = """\
You are a date planner. Build a concise itinerary using only entries from the user's saved places.

User preferences:
- Meal starting point: {meal}
- Date: {date}
- Area preference: {area}
- Budget: {budget}

Rules:
- Include 2-4 stops ordered logically by time and proximity
- Only include places whose opening hours fit the planned time
- For events, only include if the date matches or overlaps
- Prefer unvisited places (visited: false or missing)
- Prefer places in or near the requested area
- For each stop include: name, suggested time, why it fits
- If not enough matching entries exist, say so and suggest what types to save

Today's date: {today}

Saved places:
{dataset}"""

_HOURS_PROMPT = """\
Extract only the opening hours for "{name}" from the search results below.
Return a single plain string (e.g. "Mon–Fri 11am–10pm, Sat–Sun 10am–11pm").
If no opening hours are found, return null.

Search results:
{text}"""

_QUERY_PROMPT = """\
You are a personal assistant with access to the user's saved links database.
Answer the user's query based on the data below. Be concise and helpful.
If nothing matches, say so plainly.
Only include the source URL in your response if the user explicitly asks for it or for the link.

Prioritisation rules:
- For places (restaurants, cafes, etc.): prefer entries where visited is false or missing.
- For events: prefer entries where the date is ongoing or upcoming relative to today ({today}); \
deprioritise past events.

Database:
{dataset}

User query: {query}"""


def _generate(prompt: str) -> str:
    try:
        return _model.generate_content(prompt).text
    except ResourceExhausted:
        logger.warning("gemini-2.5-flash rate limited, falling back to gemini-2.5-flash-lite")
        return _fallback_model.generate_content(prompt).text


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


def _enrich_hours(name: str) -> str | None:
    import scraper
    try:
        search_name = name.replace("&", "and")
        search_url = "https://html.duckduckgo.com/html/?" + urlencode({"q": f"{search_name} opening hours singapore"})
        text = scraper.fetch(search_url)
        result = _generate(_HOURS_PROMPT.format(name=name, text=text[:4000])).strip()
        return None if result.lower() in ("null", "none", "") else result
    except Exception as e:
        logger.warning("Hours enrichment failed for %s: %s", name, e)
        return None


def extract(text: str, url: str) -> dict:
    prompt = _EXTRACT_PROMPT.format(url=url, text=text[:8000])
    entry = _parse_json(_generate(prompt))
    if not entry.get("hours") and entry.get("type") in ("restaurant", "place"):
        logger.info("Hours missing, enriching via search for: %s", entry.get("name"))
        hours = _enrich_hours(entry["name"])
        if hours:
            entry["hours"] = hours
    return entry


def merge_correction(existing: dict, correction: str) -> dict:
    prompt = _MERGE_PROMPT.format(
        current=json.dumps(existing, indent=2, ensure_ascii=False),
        correction=correction,
    )
    return _parse_json(_generate(prompt))


def plan(entries: list, meal: str, date: str, area: str, budget: str) -> str:
    from datetime import date as date_mod
    dataset = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))[:12000]
    prompt = _PLAN_PROMPT.format(
        meal=meal,
        date=date,
        area=area,
        budget=budget,
        today=date_mod.today().isoformat(),
        dataset=dataset,
    )
    return _generate(prompt)


def query(entries: list, user_query: str) -> str:
    from datetime import date

    skip = {"source", "saved"}
    compact = []
    for e in entries:
        row = {k: v for k, v in e.items() if k not in skip and v not in (None, "", "null", [])}
        if "description" in row and isinstance(row["description"], str):
            row["description"] = row["description"][:100]
        compact.append(row)

    dataset = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))[:12000]
    prompt = _QUERY_PROMPT.format(dataset=dataset, query=user_query, today=date.today().isoformat())
    return _generate(prompt)
