"""
Samarkand Bakery — Order Database
SQLite-based storage for customer orders.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "orders.db")


def normalise_phone(phone):
    """
    Standardise phone number format.
    Strips spaces, dashes, brackets, dots. Keeps + and digits only.
    Defaults to Morocco (+212) for local numbers.

    Examples:
        '+212 680 342 679'  -> '+212680342679'
        '+212-680-342-679'  -> '+212680342679'
        '0680342679'        -> '+212680342679'  (Moroccan local -> +212)
        '680342679'         -> '+212680342679'  (no prefix -> +212)
        '212680342679'      -> '+212680342679'  (missing +)
        '+44 7911 123456'   -> '+447911123456'  (international, kept)
    """
    if not phone:
        return phone
    # Remove everything except digits and +
    cleaned = ""
    for ch in phone:
        if ch.isdigit() or ch == "+":
            cleaned += ch

    # If starts with +, it's already international — just clean it
    if cleaned.startswith("+"):
        return cleaned

    # If starts with 00 (international dialling prefix), replace with +
    if cleaned.startswith("00"):
        return "+" + cleaned[2:]

    # If starts with 0 (Moroccan local number), replace 0 with +212
    if cleaned.startswith("0") and len(cleaned) == 10:
        return "+212" + cleaned[1:]

    # If starts with 212 (Moroccan without +)
    if cleaned.startswith("212") and len(cleaned) >= 12:
        return "+" + cleaned

    # If 9 digits (Moroccan without 0 or country code), add +212
    if len(cleaned) == 9 and cleaned[0] in "567":
        return "+212" + cleaned

    # Fallback: if more than 10 digits, likely has country code without +
    if len(cleaned) > 10:
        return "+" + cleaned

    # Otherwise return as-is with + prefix
    return "+" + cleaned if cleaned else phone


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_email TEXT,
            customer_phone TEXT NOT NULL,
            delivery_type TEXT NOT NULL,
            delivery_address TEXT,
            delivery_lat REAL,
            delivery_lng REAL,
            items TEXT NOT NULL,
            total_price REAL NOT NULL,
            total_cost REAL,
            total_profit REAL,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def create_order(customer_name, customer_email, customer_phone, delivery_type,
                 delivery_address, delivery_lat, delivery_lng,
                 items, total_price, total_cost=None, total_profit=None, notes=None):
    """Save a new order. items should be a list of dicts."""
    customer_phone = normalise_phone(customer_phone)
    if customer_email:
        customer_email = customer_email.strip().lower()
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO orders (customer_name, customer_email, customer_phone, delivery_type,
                          delivery_address, delivery_lat, delivery_lng,
                          items, total_price, total_cost, total_profit, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        customer_name, customer_email, customer_phone, delivery_type,
        delivery_address, delivery_lat, delivery_lng,
        json.dumps(items), total_price, total_cost, total_profit, notes
    ))
    conn.commit()
    order_id = cursor.lastrowid
    conn.close()
    return order_id


def get_orders(status=None, limit=50):
    """Get orders, optionally filtered by status."""
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()

    orders = []
    for row in rows:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        orders.append(order)
    return orders


def get_order(order_id):
    """Get a single order by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    conn.close()
    if row:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        return order
    return None


def update_order_status(order_id, status):
    """Update order status (pending, confirmed, completed, cancelled)."""
    conn = get_db()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()


def get_customers():
    """Get all customers with their order stats."""
    conn = get_db()
    rows = conn.execute("""
        SELECT
            customer_name,
            customer_email,
            customer_phone,
            COUNT(*) as total_orders,
            SUM(total_price) as total_revenue,
            SUM(total_profit) as total_profit,
            MAX(created_at) as last_order,
            MIN(created_at) as first_order
        FROM orders
        WHERE status != 'cancelled' AND customer_email IS NOT NULL AND customer_email != ''
        GROUP BY customer_email
        ORDER BY total_revenue DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_customer_orders(email):
    """Get all orders for a specific customer by email."""
    if email:
        email = email.strip().lower()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM orders WHERE customer_email = ? ORDER BY created_at DESC",
        (email,)
    ).fetchall()
    conn.close()
    orders = []
    for row in rows:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        orders.append(order)
    return orders


# Initialize database on import
init_db()
