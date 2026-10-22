import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from telegram import BotCommand, Update
from telegram.error import NetworkError
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import extractor
import scraper
import vault

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_CONFIRMATION = 1
PLAN_MEAL, PLAN_DATE, PLAN_AREA, PLAN_BUDGET, PLAN_COMMENTS = 2, 3, 4, 5, 7
WAITING_TIKTOK_CAPTION = 6
URL_RE = re.compile(r"https?://\S+")
_BARE_URL_RE = re.compile(r"\b\w[\w.-]+\.\w{2,}/\S*")
_EVENT_MARKERS = re.compile(r"[📅📍⏰🗓️]|\bNow till\b|\btill \d|\b\d+[AP]M\b", re.IGNORECASE)
_TIKTOK_HOSTS = ("tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com")

_ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID")
_allowed_filter = (
    filters.User(user_id=int(_ALLOWED_USER_ID)) if _ALLOWED_USER_ID else filters.ALL
)

_bot_start_time: float = 0.0


def _is_catchup(update: Update) -> bool:
    return bool(_bot_start_time and update.message.date.timestamp() < _bot_start_time)


def _is_forwarded(message) -> bool:
    """A forwarded message is a new item to ingest, not a correction to the pending one."""
    return getattr(message, "forward_origin", None) is not None


_REPLY_ATTEMPTS = 3
_REPLY_BACKOFF = 2.0


async def _reply(update: Update, text: str) -> None:
    """Send a reply, retrying transient network failures.

    Telegram sends time out on a flaky connection. A failed reply must not abort the
    handler: whatever it reports on (a vault save, a queued item) has already happened,
    and raising here would leave the conversation in a stale state.
    """
    for attempt in range(1, _REPLY_ATTEMPTS + 1):
        try:
            await update.message.reply_text(text)
            return
        except NetworkError as e:
            if attempt == _REPLY_ATTEMPTS:
                logger.error("Reply failed after %d attempts: %s", _REPLY_ATTEMPTS, e)
                return
            logger.warning("Reply attempt %d failed (%s), retrying", attempt, e)
            await asyncio.sleep(_REPLY_BACKOFF * attempt)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception while processing update", exc_info=context.error)
    message = getattr(update, "message", None)
    if message is None or isinstance(context.error, NetworkError):
        return
    try:
        await message.reply_text(f"Something went wrong: {context.error}")
    except NetworkError:
        pass


def _format_preview(entry: dict) -> str:
    tags = ", ".join(entry.get("tags") or []) or "—"
    lines = [
        f"Name:        {entry.get('name') or '—'}",
        f"Type:        {entry.get('type') or '—'}",
        f"Address:     {entry.get('address') or '—'}",
        f"Hours:       {entry.get('hours') or '—'}",
        f"Date:        {entry.get('date') or '—'}",
        f"Tags:        {tags}",
        f"Price:       {entry.get('price_range') or '—'}",
        f"Setting:     {entry.get('setting') or '—'}",
        "",
        entry.get("description") or "",
        "",
        "Reply 'ok' to save, or type a correction.",
    ]
    return "\n".join(lines)


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Message from user_id=%s", update.effective_user.id)
    match = URL_RE.search(update.message.text)
    if not match:
        return ConversationHandler.END
    url = match.group(0)
    catchup = _is_catchup(update)

    from urllib.parse import urlparse
    is_tiktok = urlparse(url).hostname in _TIKTOK_HOSTS

    await _reply(update, "[catch-up] Processing..." if catchup else "Fetching...")
    try:
        text = scraper.fetch(url)
    except Exception as e:
        if is_tiktok:
            context.user_data["pending_tiktok_url"] = url
            await _reply(update, f"Couldn't auto-fetch TikTok ({e}). Paste the caption and I'll extract from that.")
            return WAITING_TIKTOK_CAPTION
        await _reply(update, f"Fetch failed: {e}")
        return ConversationHandler.END

    try:
        entry = extractor.extract(text, url)
    except Exception as e:
        await _reply(update, f"Extraction failed: {e}")
        return ConversationHandler.END

    entry["source"] = url
    context.user_data["pending"] = entry
    prefix = "[catch-up] " if catchup else ""
    await _reply(update, prefix + _format_preview(entry))
    return WAITING_CONFIRMATION


async def handle_tiktok_caption(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    url = context.user_data.pop("pending_tiktok_url", "")
    await _reply(update, "Extracting...")
    try:
        entry = extractor.extract_from_text(update.message.text)
    except Exception as e:
        await _reply(update, f"Extraction failed: {e}")
        return ConversationHandler.END
    if url:
        entry["source"] = url
    context.user_data["pending"] = entry
    await _reply(update, _format_preview(entry))
    return WAITING_CONFIRMATION


_SPARSE_FIELDS = ("name", "date", "address", "description")


def _extract_source_url(text: str) -> str:
    full_url_match = URL_RE.search(text)
    if full_url_match:
        return full_url_match.group(0)
    bare_match = _BARE_URL_RE.search(text)
    if bare_match:
        return "https://" + bare_match.group(0)
    return ""


async def _enrich_from_source(entry: dict, source_url: str, catchup: bool, update: Update) -> None:
    missing = [f for f in _SPARSE_FIELDS if not entry.get(f)]
    if not (missing and source_url):
        return
    if not catchup:
        await _reply(update, f"Fields missing ({', '.join(missing)}), fetching URL...")
    try:
        page_text = scraper.fetch(source_url)
        url_entry = extractor.extract(page_text, source_url)
        for field in missing:
            if url_entry.get(field):
                entry[field] = url_entry[field]
    except Exception as e:
        logger.warning("URL enrichment failed: %s", e)


async def handle_text_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Text event from user_id=%s", update.effective_user.id)
    message = update.message.text
    catchup = _is_catchup(update)
    source_url = _extract_source_url(message)

    await _reply(update, "[catch-up] Processing..." if catchup else "Extracting...")
    try:
        entry = extractor.extract_from_text(message)
    except Exception as e:
        await _reply(update, f"Extraction failed: {e}")
        return ConversationHandler.END

    await _enrich_from_source(entry, source_url, catchup, update)

    if source_url:
        entry["source"] = source_url
    context.user_data["pending"] = entry
    prefix = "[catch-up] " if catchup else ""
    await _reply(update, prefix + _format_preview(entry))
    return WAITING_CONFIRMATION


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("Photo from user_id=%s", update.effective_user.id)
    catchup = _is_catchup(update)
    caption = update.message.caption or ""
    source_url = _extract_source_url(caption)

    await _reply(update, "[catch-up] Processing..." if catchup else "Reading image...")
    photo = update.message.photo[-1]
    file = await photo.get_file()
    image_bytes = bytes(await file.download_as_bytearray())

    try:
        entry = extractor.extract_from_image(image_bytes, caption)
    except Exception as e:
        await _reply(update, f"Extraction failed: {e}")
        return ConversationHandler.END

    await _enrich_from_source(entry, source_url, catchup, update)

    if source_url:
        entry["source"] = source_url
    context.user_data["pending"] = entry
    prefix = "[catch-up] " if catchup else ""
    await _reply(update, prefix + _format_preview(entry))
    return WAITING_CONFIRMATION


async def _extract_queued(item: dict, update: Update) -> dict:
    """Re-run extraction for a queued (forwarded) item. May raise on fetch/extract failure."""
    if item["kind"] == "photo":
        caption = item.get("caption", "")
        source_url = _extract_source_url(caption)
        entry = extractor.extract_from_image(item["image"], caption)
        await _enrich_from_source(entry, source_url, True, update)
        if source_url:
            entry["source"] = source_url
        return entry

    text = item["text"]
    url_match = URL_RE.search(text)
    if url_match:
        url = url_match.group(0)
        page_text = scraper.fetch(url)
        entry = extractor.extract(page_text, url)
        entry["source"] = url
        return entry

    source_url = _extract_source_url(text)
    entry = extractor.extract_from_text(text)
    await _enrich_from_source(entry, source_url, True, update)
    if source_url:
        entry["source"] = source_url
    return entry


async def _advance_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pop the next queued item, show its preview, and wait for confirmation. Ends if empty."""
    queue = context.user_data.get("queue") or []
    while queue:
        item = queue.pop(0)
        await _reply(update, "Processing next...")
        try:
            entry = await _extract_queued(item, update)
        except Exception as e:
            await _reply(update, f"Skipped one (failed: {e})")
            continue
        context.user_data["pending"] = entry
        remaining = len(queue)
        suffix = f"\n\n({remaining} more queued)" if remaining else ""
        await _reply(update, _format_preview(entry) + suffix)
        return WAITING_CONFIRMATION

    context.user_data.pop("queue", None)
    return ConversationHandler.END


async def _enqueue(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict) -> int:
    queue = context.user_data.setdefault("queue", [])
    queue.append(item)
    await _reply(update, 
        f"Queued — {len(queue)} waiting. Finish this one first (reply 'ok' or a correction)."
    )
    return WAITING_CONFIRMATION


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if _is_forwarded(update.message):
        return await _enqueue(update, context, {"kind": "text", "text": update.message.text})

    text = update.message.text.strip()
    entry = context.user_data.get("pending", {})

    if text.lower() == "ok":
        try:
            _, duplicate = vault.save(entry)
        except Exception as e:
            await _reply(update, f"Save failed: {e}")
            return WAITING_CONFIRMATION
        context.user_data.pop("pending", None)
        name = entry.get("name", "entry")
        msg = f"Updated existing entry: {name}" if duplicate else f"Saved: {name}"
        await _reply(update, msg)
        return await _advance_queue(update, context)

    # Treat message as a correction
    await _reply(update, "Applying correction...")
    try:
        source = entry.get("source", "")
        entry = extractor.merge_correction(entry, text)
        entry.setdefault("source", source)
        context.user_data["pending"] = entry
    except Exception as e:
        await _reply(update, f"Could not apply correction: {e}")
        return WAITING_CONFIRMATION

    await _reply(update, _format_preview(entry))
    return WAITING_CONFIRMATION


async def handle_confirmation_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    entry = context.user_data.get("pending", {})
    caption = update.message.caption or ""

    photo = update.message.photo[-1]
    file = await photo.get_file()
    image_bytes = bytes(await file.download_as_bytearray())

    if _is_forwarded(update.message):
        return await _enqueue(update, context, {"kind": "photo", "image": image_bytes, "caption": caption})

    await _reply(update, "Applying correction from image...")

    try:
        source = entry.get("source", "")
        entry = extractor.merge_correction_from_image(entry, image_bytes, caption)
        entry.setdefault("source", source)
        context.user_data["pending"] = entry
    except Exception as e:
        await _reply(update, f"Could not apply correction: {e}")
        return WAITING_CONFIRMATION

    await _reply(update, _format_preview(entry))
    return WAITING_CONFIRMATION


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Message from user_id=%s", update.effective_user.id)
    entries = vault.load_all()
    if not entries:
        await _reply(update, "No saved entries yet.")
        return
    try:
        answer = extractor.query(entries, update.message.text)
        await _reply(update, answer)
    except Exception as e:
        await _reply(update, f"Query failed: {e}")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entries = vault.list_recent(10)
    if not entries:
        await _reply(update, "No saved entries.")
        return
    lines = [f"• {e.get('name', '?')} ({e.get('type', '?')})" for e in entries]
    await _reply(update, "\n".join(lines))


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _reply(update, "Usage: /delete <name>")
        return
    name = " ".join(context.args)
    if vault.delete(name):
        await _reply(update, f"Deleted: {name}")
    else:
        await _reply(update, f"Not found: {name}")


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"] = {}
    await _reply(update, "Lunch or dinner onwards? (default: dinner)")
    return PLAN_MEAL


async def plan_meal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    context.user_data["plan"]["meal"] = text if text not in ("skip", "default") else "dinner"
    await _reply(update, "Which date? (e.g. today, tomorrow, or a date)")
    return PLAN_DATE


async def plan_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["date"] = update.message.text.strip()
    await _reply(update, "Any area preference? (e.g. orchard, cbd — or 'anywhere')")
    return PLAN_AREA


async def plan_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["area"] = update.message.text.strip()
    await _reply(update, "Budget? (default: $ and $$)")
    return PLAN_BUDGET


async def plan_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    p = context.user_data.get("plan", {})
    p["budget"] = text if text not in ("skip", "default") else "$ and $$"
    await _reply(update, "Any other preferences? (e.g. 'no seafood', 'celebrating anniversary' — or 'skip')")
    return PLAN_COMMENTS


async def plan_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    p = context.user_data.get("plan", {})
    p["comments"] = "" if text.lower() in ("skip", "default", "none") else text

    entries = vault.load_all()
    if not entries:
        await _reply(update, "No saved entries yet — save some places first.")
        context.user_data.pop("plan", None)
        return ConversationHandler.END

    await _reply(update, "Planning...")
    try:
        result = extractor.plan(
            entries,
            meal=p.get("meal", "dinner"),
            date=p.get("date", "today"),
            area=p.get("area", "anywhere"),
            budget=p.get("budget", "$ and $$"),
            comments=p.get("comments", ""),
        )
        await _reply(update, result)
    except Exception as e:
        await _reply(update, f"Plan failed: {e}")

    context.user_data.pop("plan", None)
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("pending", None)
    context.user_data.pop("plan", None)
    context.user_data.pop("queue", None)
    await _reply(update, "Cancelled.")
    return ConversationHandler.END


def main() -> None:
    if not _ALLOWED_USER_ID:
        raise SystemExit("ALLOWED_USER_ID is not set: refusing to start, since anyone who finds this bot could use it and spend your Gemini quota")
    app = (
        Application.builder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        .connect_timeout(20.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(20.0)
        .get_updates_connect_timeout(20.0)
        .get_updates_read_timeout(30.0)
        .build()
    )

    _event_filter = filters.Regex(_EVENT_MARKERS) & ~filters.Regex(URL_RE)

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND & filters.Regex(URL_RE), handle_url),
            MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND & _event_filter, handle_text_event),
            MessageHandler(_allowed_filter & filters.PHOTO, handle_photo),
            CommandHandler("plan", cmd_plan, filters=_allowed_filter),
        ],
        states={
            WAITING_TIKTOK_CAPTION: [
                MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, handle_tiktok_caption),
            ],
            WAITING_CONFIRMATION: [
                MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, handle_confirmation),
                MessageHandler(_allowed_filter & filters.PHOTO, handle_confirmation_photo),
            ],
            PLAN_MEAL:   [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_meal)],
            PLAN_DATE:   [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_date)],
            PLAN_AREA:   [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_area)],
            PLAN_BUDGET: [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_budget)],
            PLAN_COMMENTS: [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_comments)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("list", cmd_list, filters=_allowed_filter))
    app.add_handler(CommandHandler("delete", cmd_delete, filters=_allowed_filter))
    app.add_handler(MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, handle_query))
    app.add_error_handler(on_error)

    async def post_init(app: Application) -> None:
        global _bot_start_time
        _bot_start_time = datetime.now(timezone.utc).timestamp()
        await app.bot.set_my_commands([
            BotCommand("plan", "Plan a date itinerary from saved places"),
            BotCommand("list", "Show last 10 saved entries"),
            BotCommand("delete", "Delete an entry by name"),
            BotCommand("cancel", "Cancel current operation"),
        ])

    app.post_init = post_init
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
