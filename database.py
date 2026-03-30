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
            promo_code TEXT,
            discount_amount REAL DEFAULT 0,
            preferred_date TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def create_order(customer_name, customer_email, customer_phone, delivery_type,
                 delivery_address, delivery_lat, delivery_lng,
                 items, total_price, total_cost=None, total_profit=None,
                 promo_code=None, discount_amount=0,
                 preferred_date=None, notes=None):
    """Save a new order. items should be a list of dicts."""
    customer_phone = normalise_phone(customer_phone)
    if customer_email:
        customer_email = customer_email.strip().lower()
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO orders (customer_name, customer_email, customer_phone, delivery_type,
                          delivery_address, delivery_lat, delivery_lng,
                          items, total_price, total_cost, total_profit,
                          promo_code, discount_amount, preferred_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        customer_name, customer_email, customer_phone, delivery_type,
        delivery_address, delivery_lat, delivery_lng,
        json.dumps(items), total_price, total_cost, total_profit,
        promo_code, discount_amount, preferred_date, notes
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


def is_known_customer(email):
    """Check if an email belongs to a customer who has placed orders."""
    if not email:
        return False
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as count FROM orders WHERE customer_email = ?",
        (email.strip().lower(),)
    ).fetchone()
    conn.close()
    return dict(row)["count"] > 0


def get_customer_review_count(email):
    """Get how many reviews a customer has left."""
    if not email:
        return 0
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as count FROM reviews WHERE customer_email = ?",
        (email.strip().lower(),)
    ).fetchone()
    conn.close()
    return dict(row)["count"]


def init_reviews_table():
    """Create reviews table if it doesn't exist."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            customer_email TEXT,
            rating INTEGER NOT NULL,
            review_text TEXT,
            status TEXT DEFAULT 'pending',
            admin_reply TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def create_review(product_key, customer_name, customer_email, rating, review_text):
    """Submit a new review (pending moderation)."""
    if customer_email:
        customer_email = customer_email.strip().lower()
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO reviews (product_key, customer_name, customer_email, rating, review_text)
        VALUES (?, ?, ?, ?, ?)
    """, (product_key, customer_name, customer_email, rating, review_text))
    conn.commit()
    review_id = cursor.lastrowid
    conn.close()
    return review_id


def get_reviews(product_key=None, status=None, limit=100):
    """Get reviews, optionally filtered by product and/or status."""
    conn = get_db()
    query = "SELECT * FROM reviews WHERE 1=1"
    params = []
    if product_key:
        query += " AND product_key = ?"
        params.append(product_key)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_review_status(review_id, status):
    """Approve or reject a review."""
    conn = get_db()
    conn.execute("UPDATE reviews SET status = ? WHERE id = ?", (status, review_id))
    conn.commit()
    conn.close()


def add_review_reply(review_id, reply_text):
    """Admin reply to a review."""
    conn = get_db()
    conn.execute("UPDATE reviews SET admin_reply = ? WHERE id = ?", (reply_text, review_id))
    conn.commit()
    conn.close()


def get_product_review_summary(product_key):
    """Get average rating and count for a product."""
    conn = get_db()
    row = conn.execute("""
        SELECT COUNT(*) as count, AVG(rating) as avg_rating
        FROM reviews
        WHERE product_key = ? AND status = 'approved'
    """, (product_key,)).fetchone()
    conn.close()
    result = dict(row)
    result["avg_rating"] = round(result["avg_rating"], 1) if result["avg_rating"] else 0
    return result


def init_promo_table():
    """Create promo codes table if it doesn't exist."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            discount_type TEXT NOT NULL,
            discount_value REAL NOT NULL,
            min_order REAL DEFAULT 0,
            max_uses INTEGER DEFAULT 0,
            times_used INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def create_promo(code, discount_type, discount_value, min_order=0, max_uses=0):
    """Create a new promo code. discount_type: 'percentage' or 'fixed'."""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO promo_codes (code, discount_type, discount_value, min_order, max_uses)
            VALUES (?, ?, ?, ?, ?)
        """, (code.upper().strip(), discount_type, discount_value, min_order, max_uses))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def validate_promo(code, order_total):
    """Validate a promo code and return discount amount, or error."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM promo_codes WHERE code = ? AND active = 1",
        (code.upper().strip(),)
    ).fetchone()
    conn.close()

    if not row:
        return {"valid": False, "error": "Invalid promo code"}

    promo = dict(row)

    if promo["max_uses"] > 0 and promo["times_used"] >= promo["max_uses"]:
        return {"valid": False, "error": "This promo code has expired"}

    if order_total < promo["min_order"]:
        return {"valid": False, "error": f"Minimum order of {promo['min_order']} MAD required"}

    if promo["discount_type"] == "percentage":
        discount = round(order_total * promo["discount_value"] / 100, 2)
    else:
        discount = min(promo["discount_value"], order_total)

    return {
        "valid": True,
        "code": promo["code"],
        "discount_type": promo["discount_type"],
        "discount_value": promo["discount_value"],
        "discount_amount": discount
    }


def use_promo(code):
    """Increment usage count for a promo code."""
    conn = get_db()
    conn.execute("UPDATE promo_codes SET times_used = times_used + 1 WHERE code = ?", (code.upper().strip(),))
    conn.commit()
    conn.close()


def get_promos():
    """Get all promo codes for admin."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM promo_codes ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_promo_usage(code):
    """Get all orders that used a specific promo code."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, customer_name, customer_email, customer_phone, total_price, discount_amount, created_at FROM orders WHERE promo_code = ? ORDER BY created_at DESC",
        (code.upper().strip(),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def toggle_promo(promo_id, active):
    """Enable or disable a promo code."""
    conn = get_db()
    conn.execute("UPDATE promo_codes SET active = ? WHERE id = ?", (1 if active else 0, promo_id))
    conn.commit()
    conn.close()


# Initialize database on import
init_db()
init_reviews_table()
init_promo_table()
