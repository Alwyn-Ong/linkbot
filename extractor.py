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
_LOCATION = os.environ.get("LINKBOT_LOCATION") or "Singapore"

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
- setting: string — one of: indoor, outdoor, both (e.g. a rooftop bar or a place with indoor and outdoor seating); null if unclear or an article
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

_MERGE_IMAGE_PROMPT = """\
You have extracted structured data about a place/event. The user has sent an image as a correction \
or additional context (e.g. a photo of the venue, signage, menu, or opening hours).
Update the JSON using information visible in the image. Only change fields the image clearly adds to \
or contradicts — preserve all other fields as-is.
{caption_section}
Current data:
{current}

Return ONLY the updated JSON object."""

_PLAN_PROMPT = """\
You are a date planner. Build a concise itinerary using only entries from the user's saved places.

User preferences:
- Meal starting point: {meal}
- Date: {date}
- Area preference: {area}
- Budget: {budget}
- Additional comments: {comments}

Rules:
- Include 2-4 stops ordered logically by time and proximity
- Only include places whose opening hours fit the planned time
- For events, only include if the date matches or overlaps
- Prefer unvisited places (visited: false or missing)
- Prefer places in or near the requested area
- Take the additional comments into account when choosing and describing stops
- For each stop include: name, suggested time, why it fits
- If not enough matching entries exist, say so and suggest what types to save

Today's date: {today}

Saved places:
{dataset}"""

_TEXT_EXTRACT_PROMPT = """\
Extract structured information from the following Telegram message (e.g. an event, freebie, or activity announcement).
Return ONLY a valid JSON object with these fields (use null for missing fields):
- name: string — title or name of the event/place/freebie
- type: string — one of: restaurant, event, article, place
- address: string — physical location or venue
- hours: string — daily operating hours if stated (e.g. "11AM - 9PM")
- date: string — event date range or deadline (e.g. "Now till 26 Jul", "1–3 Aug 2025")
- tags: array of 2-5 concise tags — e.g. "freebie", "family", "kids", area name (e.g. "changi", "orchard"); never use country names or broad regions; ignore hashtags from the source
- price_range: string — e.g. $, $$, $$$, or "free"; null if unknown
- setting: string — one of: indoor, outdoor, both (e.g. a rooftop bar or a place with indoor and outdoor seating); null if unclear or an article
- description: string — 1-3 sentence summary of what it is

Message:
{text}"""

_IMAGE_EXTRACT_PROMPT = """\
Extract structured information from the attached image (e.g. an event poster, flyer, ticket, or social media screenshot).
Return ONLY a valid JSON object with these fields (use null for missing fields):
- name: string — title or name of the event/place
- type: string — one of: restaurant, event, article, place
- address: string — physical location or venue
- hours: string — opening hours or event time, if shown (e.g. "11AM - 9PM")
- date: string — event date range or deadline (e.g. "Now till 26 Jul", "1-3 Aug 2025")
- tags: array of 2-5 concise tags — e.g. "freebie", "family", "kids", area name; never use country names or broad regions
- price_range: string — e.g. $, $$, $$$, or "free"; null if unknown
- setting: string — one of: indoor, outdoor, both (e.g. a rooftop bar or a place with indoor and outdoor seating); null if unclear or an article
- description: string — 1-3 sentence summary of what it is
{caption_section}"""

_ENRICH_PROMPT = """\
You have partial structured data about a place or event in {location}, but some fields are missing.
Search the results below and fill in ONLY these missing fields: {fields}.
Only use information that clearly refers to the {location} location/branch of "{name}" — if the search \
results describe a different country or a different branch, leave that field null rather than guessing.
Return ONLY a JSON object with exactly these keys: {fields}. Use null for any field still not found or \
not clearly about the {location} location.

Name: {name}
Known info: {current}
{image_section}
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


def _generate(prompt: str | list) -> str:
    try:
        return _model.generate_content(prompt).text
    except ResourceExhausted:
        logger.warning("gemini-2.5-flash rate limited, falling back to gemini-3.1-flash-lite")
        return _fallback_model.generate_content(prompt).text


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


_ENRICHABLE_FIELDS = ("address", "hours", "date", "price_range")


def _enrich_via_search(entry: dict, image_bytes: bytes | None = None, mime_type: str = "image/jpeg") -> dict:
    """Fill in any missing address/hours/date/price_range via a web search + Gemini pass.

    If the entry was extracted from an image, that image is passed along too so Gemini
    can cross-check search results against what's actually shown (e.g. confirm it's the
    local branch, not a same-named place elsewhere).
    """
    if entry.get("type") not in ("restaurant", "place", "event"):
        return entry
    missing = [f for f in _ENRICHABLE_FIELDS if not entry.get(f)]
    name = entry.get("name")
    if not missing or not name:
        return entry

    import scraper
    try:
        search_name = name.replace("&", "and")
        search_url = "https://html.duckduckgo.com/html/?" + urlencode({"q": f"{search_name} {_LOCATION}"})
        text = scraper.fetch(search_url)
        logger.info("Enriching missing fields (%s) via search for: %s", ", ".join(missing), name)
        known = {k: entry.get(k) for k in ("type", "address", "hours", "date", "price_range")}
        image_section = (
            "\nAn image of the place/event is attached — use it to verify the search results "
            "actually match (e.g. same branch/location), not just the same name.\n"
            if image_bytes else ""
        )
        prompt = _ENRICH_PROMPT.format(
            fields=", ".join(missing),
            location=_LOCATION,
            name=name,
            current=json.dumps(known, ensure_ascii=False),
            image_section=image_section,
            text=text[:4000],
        )
        parts = [prompt, {"mime_type": mime_type, "data": image_bytes}] if image_bytes else prompt
        result = _parse_json(_generate(parts))
        for field in missing:
            if result.get(field):
                entry[field] = result[field]
    except Exception as e:
        logger.warning("Enrichment failed for %s: %s", name, e)
    return entry


def extract_from_text(message: str) -> dict:
    prompt = _TEXT_EXTRACT_PROMPT.format(text=message[:4000])
    entry = _parse_json(_generate(prompt))
    return _enrich_via_search(entry)


def extract_from_image(image_bytes: bytes, caption: str = "", mime_type: str = "image/jpeg") -> dict:
    image_bytes = bytes(image_bytes)
    caption_section = f"\nMessage caption (additional context):\n{caption[:2000]}" if caption else ""
    prompt = _IMAGE_EXTRACT_PROMPT.format(caption_section=caption_section)
    parts = [prompt, {"mime_type": mime_type, "data": image_bytes}]
    entry = _parse_json(_generate(parts))
    return _enrich_via_search(entry, image_bytes=image_bytes, mime_type=mime_type)


def extract(text: str, url: str) -> dict:
    prompt = _EXTRACT_PROMPT.format(url=url, text=text[:8000])
    entry = _parse_json(_generate(prompt))
    return _enrich_via_search(entry)


def merge_correction(existing: dict, correction: str) -> dict:
    prompt = _MERGE_PROMPT.format(
        current=json.dumps(existing, indent=2, ensure_ascii=False),
        correction=correction,
    )
    return _parse_json(_generate(prompt))


def merge_correction_from_image(existing: dict, image_bytes: bytes, caption: str = "", mime_type: str = "image/jpeg") -> dict:
    caption_section = f"\nMessage caption (additional context):\n{caption[:2000]}\n" if caption else ""
    prompt = _MERGE_IMAGE_PROMPT.format(
        caption_section=caption_section,
        current=json.dumps(existing, indent=2, ensure_ascii=False),
    )
    parts = [prompt, {"mime_type": mime_type, "data": bytes(image_bytes)}]
    return _parse_json(_generate(parts))


def plan(entries: list, meal: str, date: str, area: str, budget: str, comments: str = "") -> str:
    from datetime import date as date_mod
    dataset = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))[:12000]
    prompt = _PLAN_PROMPT.format(
        meal=meal,
        date=date,
        area=area,
        budget=budget,
        comments=comments or "none",
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
