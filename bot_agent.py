"""
Samarkand Bakery — Telegram Bot Agent (webhook / server version)
Uses stdlib only (urllib) — no extra packages needed on cPanel.
Imported by app.py to handle /telegram/webhook requests.
"""

import json
import logging
import os
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (
    get_orders, get_orders_by_date, get_order,
    update_order_status as db_update_order_status,
    create_expense, get_expenses,
    get_customers,
)

logger = logging.getLogger("samarkand-bot")

# ── CONFIG (set as env vars in cPanel Python App settings) ───────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ALLOWED_IDS_RAW = os.environ.get("TELEGRAM_ALLOWED_IDS", "")
ALLOWED_USER_IDS = {int(x) for x in ALLOWED_IDS_RAW.split(",") if x.strip().isdigit()}

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MAX_HISTORY = 20

# In-memory conversation history per chat
chat_histories: dict = {}


# ── TOOLS SCHEMA ─────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "get_today_orders",
        "description": (
            "Get orders due TODAY — only use when user specifically asks about today's orders or today's schedule. "
            "Do NOT use for general 'show me orders' or 'how many orders' questions."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_all_recent_orders",
        "description": (
            "Get all orders from the past 90 days. Use this for general questions like "
            "'show me orders', 'how many orders do we have', 'list recent orders', 'what orders are pending'. "
            "This is the default tool for any general order query."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Optional filter: pending/confirmed/completed/cancelled"},
            },
            "required": [],
        },
    },
    {
        "name": "get_orders_for_date",
        "description": "Get orders for a specific date (by preferred delivery/pickup date). Use when user mentions a specific day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "get_orders_range",
        "description": "Get orders placed within a date range. Use for 'this week', 'last month', specific date ranges.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date":   {"type": "string", "description": "YYYY-MM-DD"},
                "status":     {"type": "string", "description": "pending/confirmed/completed/cancelled"},
            },
            "required": [],
        },
    },
    {
        "name": "search_orders",
        "description": "Search orders by customer name or by product/item name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "item_name":     {"type": "string"},
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
                "category":   {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "add_expense",
        "description": (
            "Add a new business expense. "
            "Always confirm with the user first unless they said yes/confirm/go ahead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["Ingredients", "Packaging", "Utilities", "Equipment",
                             "Marketing", "Rent", "Staff", "Other"],
                },
                "description": {"type": "string"},
                "amount":      {"type": "number", "description": "Amount in MAD"},
                "date":        {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
            },
            "required": ["category", "description", "amount"],
        },
    },
    {
        "name": "change_order_status",
        "description": "Change an order's status. Always confirm with the user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "integer"},
                "status": {
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
                "limit": {"type": "integer", "description": "How many to return (default 5)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_ingredient_prices",
        "description": "Get the current price list for all ingredients (MAD per unit).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_order_details",
        "description": (
            "Get full details for a specific order including contact info (phone, email, address). "
            "Use when user asks for contact details, phone number, or full info about a specific order or customer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id":     {"type": "integer", "description": "Order ID number"},
                "customer_name": {"type": "string", "description": "Search by customer name if order ID not known"},
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

    if name == "get_all_recent_orders":
        start = (date.today() - timedelta(days=90)).isoformat()
        status = inputs.get("status")
        orders = get_orders(status=status, start_date=start, end_date=today_str, limit=500)
        return {"orders": [_slim_order(o) for o in orders], "count": len(orders)}

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
                start = today_str
                end = today_str
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
            "entries": expenses[:50],
        }

    if name == "add_expense":
        category = inputs.get("category", "Other")
        description = inputs.get("description", "")
        amount = float(inputs.get("amount", 0))
        expense_date = inputs.get("date", today_str)
        # Normalize ingredient description to exact system name
        if category == "Ingredients":
            matched = _match_ingredient_name(description)
            if matched:
                description = matched
        expense_id = create_expense(category, description, amount, expense_date)
        return {
            "success": True,
            "id": expense_id,
            "message": "Added: " + category + " — " + description + " — " + str(round(amount, 2)) + " MAD on " + expense_date,
        }

    if name == "change_order_status":
        order_id = int(inputs.get("order_id"))
        status = inputs.get("status")
        order = get_order(order_id)
        if not order:
            return {"success": False, "error": "Order #" + str(order_id) + " not found"}
        db_update_order_status(order_id, status)
        return {
            "success": True,
            "message": "Order #" + str(order_id) + " (" + order["customer_name"] + ") → " + status,
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
                        "available": val.get("available", True),
                    })
            return {"menu": items, "count": len(items)}
        except Exception as e:
            return {"error": str(e)}

    if name == "get_top_customers":
        limit = int(inputs.get("limit", 5))
        customers = get_customers()[:limit]
        return {"customers": customers, "count": len(customers)}

    if name == "get_order_details":
        order_id = inputs.get("order_id")
        customer_name = (inputs.get("customer_name") or "").lower()
        if order_id:
            order = get_order(int(order_id))
            if not order:
                return {"error": "Order #" + str(order_id) + " not found"}
            return _slim_order(order)
        elif customer_name:
            start = (date.today() - timedelta(days=180)).isoformat()
            all_orders = get_orders(start_date=start, end_date=today_str, limit=500)
            matches = [o for o in all_orders if customer_name in o.get("customer_name", "").lower()]
            if not matches:
                return {"error": "No orders found for customer: " + inputs.get("customer_name", "")}
            return {"orders": [_slim_order(o) for o in matches], "count": len(matches)}
        return {"error": "Provide order_id or customer_name"}

    if name == "get_ingredient_prices":
        try:
            with open(os.path.join(DATA_DIR, "ingredients.json"), encoding="utf-8") as f:
                raw = json.load(f)
            items = []
            for key, price in raw.items():
                if key.startswith("_"):
                    continue
                name_part = key
                unit = "unit"
                for suffix, u in [("_per_kg", "per kg"), ("_per_litre", "per litre"),
                                   ("_per_pot", "per pot"), ("_per_tub", "per tub"), ("_each", "each")]:
                    if name_part.endswith(suffix):
                        name_part = name_part[:-len(suffix)]
                        unit = u
                        break
                display = name_part.replace("_", " ").title()
                items.append({"name": display, "price_mad": price, "unit": unit})
            return {"ingredients": items, "count": len(items)}
        except Exception as e:
            return {"error": str(e)}

    return {"error": "Unknown tool: " + name}


def _slim_order(order):
    return {
        "id":               order.get("id"),
        "customer":         order.get("customer_name"),
        "phone":            order.get("customer_phone"),
        "email":            order.get("customer_email"),
        "delivery_type":    order.get("delivery_type"),
        "delivery_address": order.get("delivery_address"),
        "preferred_date":   order.get("preferred_date"),
        "pickup_time":      order.get("pickup_time"),
        "status":           order.get("status"),
        "total_price":      order.get("total_price"),
        "payment_method":   order.get("payment_method"),
        "payment_status":   order.get("payment_status"),
        "notes":            order.get("notes"),
        "items": [
            {"name": i.get("name"), "quantity": i.get("quantity"), "subtotal": i.get("subtotal")}
            for i in (order.get("items") or [])
        ],
        "created_at": order.get("created_at"),
    }


# ── ANTHROPIC API (stdlib, no SDK) ────────────────────────────────────────────
def _get_ingredient_names():
    try:
        with open(os.path.join(DATA_DIR, "ingredients.json"), encoding="utf-8") as f:
            raw = json.load(f)
        names = []
        for key in raw:
            if key.startswith("_"):
                continue
            name = key
            for suffix in ["_per_kg", "_per_litre", "_per_pot", "_per_tub", "_each"]:
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
                    break
            name = name.replace("_", " ").title()
            names.append(name)
        return names
    except Exception:
        return []


def _match_ingredient_name(query):
    """Normalize a user-supplied ingredient name to the exact system name."""
    q = query.lower().strip()
    names = _get_ingredient_names()
    # Exact match
    for n in names:
        if n.lower() == q:
            return n
    # Query is contained in a name (e.g. "sesame" → "Sesame Seeds")
    for n in names:
        if q in n.lower():
            return n
    # Name is contained in query (e.g. "sesame seeds oil" → "Sesame Seeds")
    for n in names:
        if n.lower() in q:
            return n
    return None


def _call_claude(messages):
    today = date.today()
    today_str = today.strftime("%A %d %B %Y") + " (" + today.isoformat() + ")"
    upcoming = ", ".join(
        (today + timedelta(days=i)).strftime("%A %d %b (%Y-%m-%d)")
        for i in range(1, 8)
    )
    ingredients = ", ".join(_get_ingredient_names())
    system_prompt = (
        "You are the smart business assistant for Samarkand Bakery, an Uzbek/Turkish bakery "
        "in Tetouan, Morocco. Today is " + today_str + ".\n"
        "Next 7 days: " + upcoming + ".\n"
        "ALWAYS use this list to resolve day names like 'Saturday' or 'next Friday' — do NOT calculate dates yourself.\n\n"
        "You help the owner manage orders, expenses, and business stats via Telegram.\n"
        "Currency is MAD. Be concise — this is a chat, not a report.\n\n"
        "EXPENSE HANDLING — this is very important:\n"
        "This is a TEXT chat, not a website. There are no dropdowns, no buttons, no UI.\n"
        "When the user wants to add an expense, collect these 4 things conversationally:\n"
        "  1. Category: Ingredients / Packaging / Utilities / Equipment / Marketing / Rent / Staff / Other\n"
        "  2. Description: what was bought or paid for (e.g. Flour, Sesame Seeds, Gas bill)\n"
        "  3. Amount in MAD\n"
        "  4. Date (default: today if not mentioned)\n"
        "If the user says 'Ingredients' as category, ask: 'Which ingredient and how much did it cost?'\n"
        "Use the EXACT ingredient name from this list when it matches (even partially):\n"
        "  " + ingredients + "\n"
        "Examples: user says 'sesame' → use 'Sesame Seeds'. User says 'butter' → use 'Salted Butter'.\n"
        "If the ingredient is NOT in the list at all, still save it — just use the name the user gave.\n"
        "Once you have all 4 fields, confirm before calling add_expense.\n"
        "Example: 'Add Ingredients — Sesame Seeds — 46 MAD on 23 Apr. Confirm?'\n\n"
        "OTHER RULES:\n"
        "- For change_order_status: confirm before acting.\n"
        "- Format order lists: one per line with ID, customer, items, total.\n"
        "- Use *bold* for key numbers. Keep replies under 300 words.\n"
        "- Understand English, Arabic, and French naturally.\n"
        "- Never mention dropdowns, buttons, or web UI — this is a chat only.\n"
    )

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1500,
        "system": system_prompt,
        "tools": TOOLS,
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", ANTHROPIC_API_KEY)
    req.add_header("anthropic-version", "2023-06-01")

    resp = urllib.request.urlopen(req, timeout=55)
    return json.loads(resp.read().decode("utf-8"))


def run_agent(chat_id, user_message):
    history = chat_histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_message})

    for _ in range(10):
        messages = history[-MAX_HISTORY:]
        response = _call_claude(messages)

        content = response.get("content", [])
        tool_uses = [b for b in content if b.get("type") == "tool_use"]

        if not tool_uses:
            text = next((b.get("text", "") for b in content if b.get("type") == "text"), "Done.")
            history.append({"role": "assistant", "content": content})
            if len(history) > MAX_HISTORY:
                chat_histories[chat_id] = history[-MAX_HISTORY:]
            return text


        history.append({"role": "assistant", "content": content})

        tool_results = []
        for tu in tool_uses:
            try:
                result = execute_tool(tu["name"], tu.get("input", {}))
            except Exception as e:
                result = {"error": str(e)}
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": tu["id"],
                "content":     json.dumps(result, default=str),
            })

        history.append({"role": "user", "content": tool_results})

    return "Sorry, I could not complete that. Please try again."


# ── TELEGRAM API (stdlib) ─────────────────────────────────────────────────────
def _tg_post(method, payload):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/" + method
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error("Telegram API error (%s): %s", method, e)
        return {}


def send_message(chat_id, text):
    for chunk in _split_message(text):
        _tg_post("sendMessage", {
            "chat_id":    chat_id,
            "text":       chunk,
            "parse_mode": "Markdown",
        })


def send_typing(chat_id):
    _tg_post("sendChatAction", {"chat_id": chat_id, "action": "typing"})


def notify_new_order(order):
    """Send a new-order notification to all allowed Telegram users."""
    if not TELEGRAM_BOT_TOKEN or not ALLOWED_USER_IDS:
        return
    items_text = ", ".join(
        i.get("name", "?") + " x" + str(i.get("quantity", 1))
        for i in (order.get("items") or [])
    )
    delivery_type = order.get("delivery_type", "pickup")
    when_parts = []
    if order.get("preferred_date"):
        when_parts.append(order["preferred_date"])
    if order.get("pickup_time"):
        when_parts.append(order["pickup_time"])
    when = " at ".join(when_parts) if when_parts else "-"
    payment = order.get("payment_method", "cod").upper()
    if order.get("payment_status") == "paid":
        payment += " (PAID)"
    lines = [
        "*New Order #" + str(order.get("id", "?")) + "!*",
        "Customer: " + order.get("customer_name", "?") + " — " + order.get("customer_phone", ""),
        "Items: " + items_text,
        "Total: " + str(round(order.get("total_price", 0), 2)) + " MAD | " + payment,
        ("Delivery" if delivery_type == "delivery" else "Pickup") + ": " + when,
    ]
    if delivery_type == "delivery" and order.get("delivery_address"):
        lines.append("Address: " + order["delivery_address"])
    if order.get("notes"):
        lines.append("Notes: " + order["notes"])
    text = "\n".join(lines)
    for uid in ALLOWED_USER_IDS:
        try:
            send_message(uid, text)
        except Exception as e:
            logger.error("notify_new_order to %s failed: %s", uid, e)


def _split_message(text, max_len=4000):
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


# ── VOICE TRANSCRIPTION (stdlib multipart, no openai package) ─────────────────
def _get_tg_file(file_id):
    result = _tg_post("getFile", {"file_id": file_id})
    return result.get("result", {}).get("file_path")


def _download_tg_file(file_path):
    url = "https://api.telegram.org/file/bot" + TELEGRAM_BOT_TOKEN + "/" + file_path
    req = urllib.request.Request(url)
    resp = urllib.request.urlopen(req, timeout=30)
    return resp.read()


def _transcribe_whisper(audio_bytes, filename="audio.ogg"):
    if not OPENAI_API_KEY:
        return None
    boundary = "----FormBoundary" + str(int(time.time()))
    body = (
        "--" + boundary + "\r\n"
        "Content-Disposition: form-data; name=\"model\"\r\n\r\n"
        "whisper-1\r\n"
        "--" + boundary + "\r\n"
        "Content-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\n"
        "Content-Type: audio/ogg\r\n\r\n"
    ).encode("utf-8") + audio_bytes + ("\r\n--" + boundary + "--\r\n").encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        method="POST",
    )
    req.add_header("Authorization", "Bearer " + OPENAI_API_KEY)
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("text", "")
    except Exception as e:
        logger.error("Whisper transcription error: %s", e)
        return None


# ── MAIN UPDATE HANDLER ───────────────────────────────────────────────────────
def handle_update(update):
    """Process one Telegram update dict. Called in a background thread."""
    try:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = message["chat"]["id"]
        user_id = message.get("from", {}).get("id")

        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            send_message(chat_id, "Access denied.")
            return

        # /start or /clear commands
        text = message.get("text", "")
        if text.startswith("/start"):
            send_message(
                chat_id,
                "Samarkand Bakery Assistant\n\n"
                "Ask me anything about orders, expenses, or stats.\n\n"
                "Examples:\n"
                "  What are today's orders?\n"
                "  Show this month's revenue\n"
                "  Add flour expense 45 MAD\n"
                "  Who ordered baklava this week?"
            )
            return
        if text.startswith("/clear"):
            chat_histories.pop(chat_id, None)
            send_message(chat_id, "Conversation history cleared.")
            return

        send_typing(chat_id)

        # Voice message
        if "voice" in message:
            if not OPENAI_API_KEY:
                _tg_post("sendMessage", {"chat_id": chat_id, "text": "Voice not configured. Please type your message."})
                return
            try:
                file_path = _get_tg_file(message["voice"]["file_id"])
                if not file_path:
                    _tg_post("sendMessage", {"chat_id": chat_id, "text": "Could not download voice file. Please type."})
                    return
                audio_bytes = _download_tg_file(file_path)
                transcribed = _transcribe_whisper(audio_bytes)
                if not transcribed:
                    _tg_post("sendMessage", {"chat_id": chat_id, "text": "Could not understand voice message. Please type."})
                    return
                _tg_post("sendMessage", {"chat_id": chat_id, "text": "Heard: " + transcribed})
                send_typing(chat_id)
                text = transcribed
            except Exception as e:
                logger.error("Voice processing error: %s", e)
                _tg_post("sendMessage", {"chat_id": chat_id, "text": "Voice processing failed. Please type your message."})
                return

        if not text.strip():
            return

        response = run_agent(chat_id, text)
        send_message(chat_id, response)

    except Exception as e:
        logger.error("handle_update error: %s", e)


def register_webhook(host_url):
    """Register the webhook URL with Telegram. Call once after deploy."""
    webhook_url = host_url.rstrip("/") + "/telegram/webhook"
    result = _tg_post("setWebhook", {"url": webhook_url})
    return result
