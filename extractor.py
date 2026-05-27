import json
import logging
import os

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


def extract(text: str, url: str) -> dict:
    prompt = _EXTRACT_PROMPT.format(url=url, text=text[:8000])
    return _parse_json(_generate(prompt))


def merge_correction(existing: dict, correction: str) -> dict:
    prompt = _MERGE_PROMPT.format(
        current=json.dumps(existing, indent=2, ensure_ascii=False),
        correction=correction,
    )
    return _parse_json(_generate(prompt))


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
