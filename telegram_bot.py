#!/usr/bin/env python3
"""
Samarkand Bakery — Telegram Bot Agent
Intelligent assistant with voice support, powered by Claude.

Setup:
  1. pip install python-telegram-bot anthropic openai
  2. Create a bot via @BotFather, get the token
  3. Find your Telegram user ID via @userinfobot
  4. Set environment variables:
       TELEGRAM_BOT_TOKEN   = your bot token
       ANTHROPIC_API_KEY    = your Anthropic API key
       OPENAI_API_KEY       = your OpenAI key (for voice transcription, optional)
       TELEGRAM_ALLOWED_IDS = comma-separated user IDs allowed to use the bot
  5. Run: python3 telegram_bot.py

The bot understands natural language in English, Arabic, and French.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from datetime import date, timedelta

# ── Make sure database.py is importable ──────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from database import (
    get_orders, get_orders_by_date, get_order,
    update_order_status as db_update_order_status,
    create_expense, get_expenses,
    get_customers,
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY      = os.environ.get("OPENAI_API_KEY", "")
ALLOWED_IDS_RAW     = os.environ.get("TELEGRAM_ALLOWED_IDS", "")
ALLOWED_USER_IDS    = {int(x) for x in ALLOWED_IDS_RAW.split(",") if x.strip().isdigit()}

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MAX_HISTORY = 20   # messages kept per chat session

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("samarkand-bot")

# ── ANTHROPIC CLIENT ─────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── PER-CHAT CONVERSATION HISTORY ────────────────────────────────────────────
chat_histories: dict = {}


# ── TOOLS SCHEMA ─────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "get_today_orders",
        "description": (
            "Get all active orders for today. Returns orders where preferred_date "
            "is today plus orders placed today. Use this for 'what are today's orders?'"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_orders_for_date",
        "description": "Get orders for a specific date (by preferred delivery/pickup date).",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                }
            },
            "required": ["date"],
        },
    },
    {
        "name": "get_orders_range",
        "description": "Get orders placed within a date range (by creation date). Useful for revenue stats.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date":   {"type": "string", "description": "YYYY-MM-DD"},
                "status":     {"type": "string", "description": "Filter by status: pending/confirmed/completed/cancelled"},
            },
            "required": [],
        },
    },
    {
        "name": "search_orders",
        "description": (
            "Search orders by customer name or by product/item name. "
            "Use for 'who ordered X?' or 'find orders from Ahmed'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Partial customer name to search"},
                "item_name":     {"type": "string", "description": "Partial product name to search"},
                "days_back":     {"type": "integer", "description": "How many days back to search (default 30)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_order_stats",
        "description": "Get revenue, profit, and order counts for a period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "7d", "30d", "month", "all"],
                    "description": "Predefined period, or use start_date/end_date instead",
                },
                "start_date": {"type": "string", "description": "YYYY-MM-DD (overrides period)"},
                "end_date":   {"type": "string", "description": "YYYY-MM-DD (overrides period)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_expenses_summary",
        "description": "Get expense records for a date range, with totals by category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date":   {"type": "string", "description": "YYYY-MM-DD"},
                "category":   {"type": "string", "description": "Filter by category name"},
            },
            "required": [],
        },
    },
    {
        "name": "add_expense",
        "description": (
            "Add a new business expense to the database. "
            "Always confirm with the user before calling this unless they explicitly said 'yes' or 'confirm'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["Ingredients", "Packaging", "Utilities", "Equipment",
                             "Marketing", "Rent", "Staff", "Other"],
                },
                "description": {"type": "string", "description": "What was purchased/paid"},
                "amount":      {"type": "number", "description": "Amount in MAD"},
                "date":        {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
            },
            "required": ["category", "description", "amount"],
        },
    },
    {
        "name": "change_order_status",
        "description": (
            "Change an order's status (pending → confirmed → completed, or cancelled). "
            "Always confirm with the user before calling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "status":   {
                    "type": "string",
                    "enum": ["pending", "confirmed", "completed", "cancelled"],
                },
            },
            "required": ["order_id", "status"],
        },
    },
    {
        "name": "get_menu",
        "description": "Get all available menu items with names and prices.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_top_customers",
        "description": "Get top customers by total spend.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many customers to return (default 5)"},
            },
            "required": [],
        },
    },
]


# ── TOOL EXECUTION ────────────────────────────────────────────────────────────
def execute_tool(name, inputs):
    today_str = date.today().isoformat()

    if name == "get_today_orders":
        by_preferred = get_orders_by_date(today_str)
        by_created = get_orders(start_date=today_str, end_date=today_str, limit=200)
        seen = set()
        combined = []
        for o in by_preferred + by_created:
            if o["id"] not in seen:
                seen.add(o["id"])
                combined.append(_slim_order(o))
        return {"orders": combined, "count": len(combined), "date": today_str}

    if name == "get_orders_for_date":
        d = inputs.get("date", today_str)
        orders = get_orders_by_date(d)
        return {"orders": [_slim_order(o) for o in orders], "count": len(orders), "date": d}

    if name == "get_orders_range":
        start = inputs.get("start_date")
        end = inputs.get("end_date", today_str)
        status = inputs.get("status")
        orders = get_orders(status=status, start_date=start, end_date=end, limit=500)
        return {"orders": [_slim_order(o) for o in orders], "count": len(orders)}

    if name == "search_orders":
        days = int(inputs.get("days_back", 30))
        start = (date.today() - timedelta(days=days)).isoformat()
        all_orders = get_orders(start_date=start, end_date=today_str, limit=500)
        customer_q = (inputs.get("customer_name") or "").lower()
        item_q = (inputs.get("item_name") or "").lower()
        results = []
        for o in all_orders:
            name_match = customer_q and customer_q in o["customer_name"].lower()
            item_match = item_q and any(
                item_q in item.get("name", "").lower() for item in o.get("items", [])
            )
            if name_match or item_match:
                results.append(_slim_order(o))
        return {"orders": results, "count": len(results)}

    if name == "get_order_stats":
        start = inputs.get("start_date")
        end = inputs.get("end_date", today_str)
        if not start:
            today = date.today()
            period = inputs.get("period", "30d")
            if period == "today":
                start = today_str; end = today_str
            elif period == "7d":
                start = (today - timedelta(days=6)).isoformat()
            elif period == "30d":
                start = (today - timedelta(days=29)).isoformat()
            elif period == "month":
                start = today.replace(day=1).isoformat()
            else:
                start = None
        orders = get_orders(start_date=start, end_date=end if start else None, limit=500)
        active = [o for o in orders if o["status"] != "cancelled"]
        return {
            "period": inputs.get("period", "custom"),
            "start_date": start,
            "end_date": end,
            "total_orders": len(orders),
            "active_orders": len(active),
            "cancelled": len(orders) - len(active),
            "revenue_mad": round(sum(o.get("total_price") or 0 for o in active), 2),
            "cost_mad":    round(sum(o.get("total_cost") or 0  for o in active), 2),
            "profit_mad":  round(sum(o.get("total_profit") or 0 for o in active), 2),
            "pending":     sum(1 for o in active if o["status"] == "pending"),
            "confirmed":   sum(1 for o in active if o["status"] == "confirmed"),
            "completed":   sum(1 for o in active if o["status"] == "completed"),
        }

    if name == "get_expenses_summary":
        start = inputs.get("start_date")
        end = inputs.get("end_date")
        cat_filter = (inputs.get("category") or "").lower()
        expenses = get_expenses(start_date=start, end_date=end)
        if cat_filter:
            expenses = [e for e in expenses if e["category"].lower() == cat_filter]
        by_cat = {}
        for e in expenses:
            by_cat[e["category"]] = round(by_cat.get(e["category"], 0) + e["amount"], 2)
        return {
            "total_mad": round(sum(e["amount"] for e in expenses), 2),
            "count": len(expenses),
            "by_category": by_cat,
            "entries": expenses[:50],  # cap to avoid huge payloads
        }

    if name == "add_expense":
        category = inputs.get("category", "Other")
        description = inputs.get("description", "")
        amount = float(inputs.get("amount", 0))
        expense_date = inputs.get("date", today_str)
        expense_id = create_expense(category, description, amount, expense_date)
        return {
            "success": True,
            "id": expense_id,
            "message": "Expense added: {} — {} — {:.2f} MAD on {}".format(
                category, description, amount, expense_date
            ),
        }

    if name == "change_order_status":
        order_id = int(inputs.get("order_id"))
        status = inputs.get("status")
        order = get_order(order_id)
        if not order:
            return {"success": False, "error": "Order #{} not found".format(order_id)}
        db_update_order_status(order_id, status)
        return {
            "success": True,
            "message": "Order #{} ({}) → {}".format(order_id, order["customer_name"], status),
        }

    if name == "get_menu":
        try:
            with open(os.path.join(DATA_DIR, "menu.json"), encoding="utf-8") as f:
                menu_data = json.load(f)
            items = []
            for key, val in menu_data.items():
                if isinstance(val, dict) and "name" in val:
                    items.append({
                        "key": key,
                        "name": val.get("name", key),
                        "price": val.get("price", 0),
                        "category": val.get("category", ""),
                        "available": val.get("available", True),
                    })
            return {"menu": items, "count": len(items)}
        except Exception as e:
            return {"error": str(e)}

    if name == "get_top_customers":
        limit = int(inputs.get("limit", 5))
        customers = get_customers()[:limit]
        return {"customers": customers, "count": len(customers)}

    return {"error": "Unknown tool: {}".format(name)}


def _slim_order(order):
    """Return a smaller order dict to keep tool payloads manageable."""
    return {
        "id":             order.get("id"),
        "customer":       order.get("customer_name"),
        "phone":          order.get("customer_phone"),
        "status":         order.get("status"),
        "delivery_type":  order.get("delivery_type"),
        "preferred_date": order.get("preferred_date"),
        "pickup_time":    order.get("pickup_time"),
        "total_price":    order.get("total_price"),
        "total_profit":   order.get("total_profit"),
        "payment_method": order.get("payment_method"),
        "payment_status": order.get("payment_status"),
        "notes":          order.get("notes"),
        "items":          [
            {"name": i.get("name"), "quantity": i.get("quantity"), "subtotal": i.get("subtotal")}
            for i in (order.get("items") or [])
        ],
        "created_at": order.get("created_at"),
    }


def _content_to_dicts(content):
    """Convert anthropic response content blocks to plain dicts for history storage."""
    result = []
    for block in content:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({
                "type":  "tool_use",
                "id":    block.id,
                "name":  block.name,
                "input": block.input,
            })
    return result


# ── CLAUDE AGENT LOOP ─────────────────────────────────────────────────────────
def run_agent(chat_id, user_message):
    """Synchronous agent loop (run in executor to avoid blocking event loop)."""
    history = chat_histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_message})

    today = date.today()
    today_str = today.strftime("%A %d %B %Y") + " (" + today.isoformat() + ")"
    upcoming = ", ".join(
        (today + timedelta(days=i)).strftime("%A %d %b (%Y-%m-%d)")
        for i in range(1, 8)
    )
    system_prompt = (
        "You are the smart business assistant for Samarkand Bakery, an Uzbek/Turkish bakery "
        "in Tetouan, Morocco. Today is " + today_str + ".\n"
        "Next 7 days: " + upcoming + ".\n"
        "ALWAYS use this list to resolve day names like 'Saturday' or 'next Friday' — do NOT calculate dates yourself.\n\n"
        "You help the owner manage orders, expenses, and business stats via Telegram.\n"
        "Currency is MAD (Moroccan Dirham). Be concise — this is a chat, not a report.\n\n"
        "Rules:\n"
        "- For write actions (add_expense, change_order_status): ask for confirmation first "
        "  unless the user already said 'yes', 'confirm', 'go ahead', or similar.\n"
        "- Format order lists clearly: one order per line with ID, customer, items, total.\n"
        "- Use *bold* for important numbers. Keep responses under ~300 words.\n"
        "- Understand English, Arabic, and French naturally.\n"
        "- If asked for a summary, give the key numbers first, then details.\n"
    )

    for _ in range(10):  # max 10 tool-call rounds
        messages = history[-MAX_HISTORY:]

        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        content_dicts = _content_to_dicts(response.content)
        tool_uses = [b for b in response.content if b.type == "tool_use"]

        if not tool_uses:
            # Final text response
            text = next(
                (b.text for b in response.content if b.type == "text"), "Done."
            )
            history.append({"role": "assistant", "content": content_dicts})
            # Trim history
            if len(history) > MAX_HISTORY:
                chat_histories[chat_id] = history[-MAX_HISTORY:]
            return text

        # Execute tools and loop
        history.append({"role": "assistant", "content": content_dicts})

        tool_results = []
        for tu in tool_uses:
            try:
                result = execute_tool(tu.name, tu.input)
            except Exception as e:
                result = {"error": str(e)}
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tu.id,
                "content":     json.dumps(result, default=str),
            })

        history.append({"role": "user", "content": tool_results})

    return "Sorry, I couldn't complete that request. Please try again."


# ── VOICE TRANSCRIPTION ────────────────────────────────────────────────────────
async def transcribe_voice(file_path):
    """Transcribe a voice file using OpenAI Whisper."""
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with open(file_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )
        return transcript.text
    except Exception as e:
        logger.error("Voice transcription failed: %s", e)
        return None


# ── TELEGRAM HANDLERS ──────────────────────────────────────────────────────────
def _is_allowed(update):
    uid = update.effective_user.id if update.effective_user else None
    return (not ALLOWED_USER_IDS) or (uid in ALLOWED_USER_IDS)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text(
        "Samarkand Bakery Assistant\n\n"
        "Ask me anything about your orders or business. Voice messages work too.\n\n"
        "Examples:\n"
        "  What are today's orders?\n"
        "  Show this month's revenue\n"
        "  Who ordered baklava this week?\n"
        "  Add flour expense 45 MAD\n"
        "  Confirm order #12\n"
        "  How much did we spend on ingredients this month?"
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear conversation history for this chat."""
    if not _is_allowed(update):
        return
    chat_id = update.effective_chat.id
    chat_histories.pop(chat_id, None)
    await update.message.reply_text("Conversation history cleared.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""
    if not user_text.strip():
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        response = await asyncio.to_thread(run_agent, chat_id, user_text)
        # Split long messages (Telegram max = 4096 chars)
        for chunk in _split_message(response):
            await update.message.reply_text(chunk, parse_mode="Markdown")
    except Exception as e:
        logger.error("handle_text error: %s", e)
        await update.message.reply_text("Something went wrong. Please try again.")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    chat_id = update.effective_chat.id

    if not OPENAI_API_KEY:
        await update.message.reply_text(
            "Voice messages are not configured (OPENAI_API_KEY missing). Please type your message."
        )
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    tmp_path = None
    try:
        voice = update.message.voice
        tg_file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(tmp_path)

        transcribed = await transcribe_voice(tmp_path)

        if not transcribed:
            await update.message.reply_text(
                "Sorry, I couldn't understand that voice message. Please try typing."
            )
            return

        await update.message.reply_text("_{}_".format(transcribed), parse_mode="Markdown")
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        response = await asyncio.to_thread(run_agent, chat_id, transcribed)
        for chunk in _split_message(response):
            await update.message.reply_text(chunk, parse_mode="Markdown")

    except Exception as e:
        logger.error("handle_voice error: %s", e)
        await update.message.reply_text("Voice processing failed. Please type your message.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _split_message(text, max_len=4000):
    """Split text into chunks that fit Telegram's message limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


# ── STARTUP CHECKS ─────────────────────────────────────────────────────────────
def check_config():
    errors = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is not set")
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY is not set")
    if errors:
        for e in errors:
            logger.error("Config error: %s", e)
        sys.exit(1)
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set — voice transcription disabled")
    if not ALLOWED_USER_IDS:
        logger.warning("TELEGRAM_ALLOWED_IDS not set — bot is open to ALL users!")


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    check_config()
    logger.info("Starting Samarkand Bakery Telegram Bot...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
