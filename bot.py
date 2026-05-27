import logging
import os
import re

from dotenv import load_dotenv

load_dotenv()

from telegram import BotCommand, Update
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
PLAN_MEAL, PLAN_DATE, PLAN_AREA, PLAN_BUDGET = 2, 3, 4, 5
URL_RE = re.compile(r"https?://\S+")

_ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID")
_allowed_filter = (
    filters.User(user_id=int(_ALLOWED_USER_ID)) if _ALLOWED_USER_ID else filters.ALL
)


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

    await update.message.reply_text("Fetching...")
    try:
        text = scraper.fetch(url)
    except Exception as e:
        await update.message.reply_text(f"Fetch failed: {e}")
        return ConversationHandler.END

    await update.message.reply_text("Extracting...")
    try:
        entry = extractor.extract(text, url)
    except Exception as e:
        await update.message.reply_text(f"Extraction failed: {e}")
        return ConversationHandler.END

    entry["source"] = url
    context.user_data["pending"] = entry
    await update.message.reply_text(_format_preview(entry))
    return WAITING_CONFIRMATION


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    entry = context.user_data.get("pending", {})

    if text.lower() == "ok":
        try:
            _, duplicate = vault.save(entry)
        except Exception as e:
            await update.message.reply_text(f"Save failed: {e}")
            return WAITING_CONFIRMATION
        context.user_data.pop("pending", None)
        name = entry.get("name", "entry")
        msg = f"Updated existing entry: {name}" if duplicate else f"Saved: {name}"
        await update.message.reply_text(msg)
        return ConversationHandler.END

    # Treat message as a correction
    await update.message.reply_text("Applying correction...")
    try:
        source = entry.get("source", "")
        entry = extractor.merge_correction(entry, text)
        entry.setdefault("source", source)
        context.user_data["pending"] = entry
    except Exception as e:
        await update.message.reply_text(f"Could not apply correction: {e}")
        return WAITING_CONFIRMATION

    await update.message.reply_text(_format_preview(entry))
    return WAITING_CONFIRMATION


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Message from user_id=%s", update.effective_user.id)
    entries = vault.load_all()
    if not entries:
        await update.message.reply_text("No saved entries yet.")
        return
    try:
        answer = extractor.query(entries, update.message.text)
        await update.message.reply_text(answer)
    except Exception as e:
        await update.message.reply_text(f"Query failed: {e}")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    entries = vault.list_recent(10)
    if not entries:
        await update.message.reply_text("No saved entries.")
        return
    lines = [f"• {e.get('name', '?')} ({e.get('type', '?')})" for e in entries]
    await update.message.reply_text("\n".join(lines))


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /delete <name>")
        return
    name = " ".join(context.args)
    if vault.delete(name):
        await update.message.reply_text(f"Deleted: {name}")
    else:
        await update.message.reply_text(f"Not found: {name}")


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"] = {}
    await update.message.reply_text("Lunch or dinner onwards? (default: dinner)")
    return PLAN_MEAL


async def plan_meal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    context.user_data["plan"]["meal"] = text if text not in ("skip", "default") else "dinner"
    await update.message.reply_text("Which date? (e.g. today, tomorrow, or a date)")
    return PLAN_DATE


async def plan_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["date"] = update.message.text.strip()
    await update.message.reply_text("Any area preference? (e.g. orchard, cbd — or 'anywhere')")
    return PLAN_AREA


async def plan_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["plan"]["area"] = update.message.text.strip()
    await update.message.reply_text("Budget? (default: $ and $$)")
    return PLAN_BUDGET


async def plan_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    p = context.user_data.get("plan", {})
    p["budget"] = text if text not in ("skip", "default") else "$ and $$"

    entries = vault.load_all()
    if not entries:
        await update.message.reply_text("No saved entries yet — save some places first.")
        return ConversationHandler.END

    await update.message.reply_text("Planning...")
    try:
        result = extractor.plan(
            entries,
            meal=p.get("meal", "dinner"),
            date=p.get("date", "today"),
            area=p.get("area", "anywhere"),
            budget=p.get("budget", "$ and $$"),
        )
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Plan failed: {e}")

    context.user_data.pop("plan", None)
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("pending", None)
    context.user_data.pop("plan", None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


def main() -> None:
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND & filters.Regex(URL_RE), handle_url),
            CommandHandler("plan", cmd_plan, filters=_allowed_filter),
        ],
        states={
            WAITING_CONFIRMATION: [
                MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, handle_confirmation),
            ],
            PLAN_MEAL:   [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_meal)],
            PLAN_DATE:   [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_date)],
            PLAN_AREA:   [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_area)],
            PLAN_BUDGET: [MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, plan_budget)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("list", cmd_list, filters=_allowed_filter))
    app.add_handler(CommandHandler("delete", cmd_delete, filters=_allowed_filter))
    app.add_handler(MessageHandler(_allowed_filter & filters.TEXT & ~filters.COMMAND, handle_query))

    async def post_init(app: Application) -> None:
        await app.bot.set_my_commands([
            BotCommand("plan", "Plan a date itinerary from saved places"),
            BotCommand("list", "Show last 10 saved entries"),
            BotCommand("delete", "Delete an entry by name"),
            BotCommand("cancel", "Cancel current operation"),
        ])

    app.post_init = post_init
    logger.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
