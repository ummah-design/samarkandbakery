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
            pickup_time TEXT,
            notes TEXT,
            payment_method TEXT DEFAULT 'cod',
            payment_status TEXT DEFAULT 'unpaid',
            paypal_order_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrate existing databases: add payment columns if missing
    try:
        conn.execute("SELECT payment_method FROM orders LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'cod'")
        conn.execute("ALTER TABLE orders ADD COLUMN payment_status TEXT DEFAULT 'unpaid'")
        conn.execute("ALTER TABLE orders ADD COLUMN paypal_order_id TEXT")
        conn.commit()
    try:
        conn.execute("SELECT pickup_time FROM orders LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE orders ADD COLUMN pickup_time TEXT")
        conn.commit()
    conn.commit()
    conn.close()


def create_order(customer_name, customer_email, customer_phone, delivery_type,
                 delivery_address, delivery_lat, delivery_lng,
                 items, total_price, total_cost=None, total_profit=None,
                 promo_code=None, discount_amount=0,
                 preferred_date=None, pickup_time=None, notes=None,
                 payment_method='cod', payment_status='unpaid', paypal_order_id=None):
    """Save a new order. items should be a list of dicts."""
    customer_phone = normalise_phone(customer_phone)
    if customer_email:
        customer_email = customer_email.strip().lower()
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO orders (customer_name, customer_email, customer_phone, delivery_type,
                          delivery_address, delivery_lat, delivery_lng,
                          items, total_price, total_cost, total_profit,
                          promo_code, discount_amount, preferred_date, pickup_time, notes,
                          payment_method, payment_status, paypal_order_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        customer_name, customer_email, customer_phone, delivery_type,
        delivery_address, delivery_lat, delivery_lng,
        json.dumps(items), total_price, total_cost, total_profit,
        promo_code, discount_amount, preferred_date, pickup_time, notes,
        payment_method, payment_status, paypal_order_id
    ))
    conn.commit()
    order_id = cursor.lastrowid
    conn.close()
    return order_id


def update_payment_status(order_id, payment_status, paypal_order_id=None):
    """Update payment status for an order."""
    conn = get_db()
    if paypal_order_id:
        conn.execute("UPDATE orders SET payment_status = ?, paypal_order_id = ? WHERE id = ?",
                     (payment_status, paypal_order_id, order_id))
    else:
        conn.execute("UPDATE orders SET payment_status = ? WHERE id = ?",
                     (payment_status, order_id))
    conn.commit()
    conn.close()


def get_orders(status=None, limit=50, start_date=None, end_date=None, sort="date_desc"):
    """Get orders, optionally filtered by status and date range."""
    conn = get_db()
    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if start_date:
        query += " AND DATE(created_at) >= ?"
        params.append(start_date)
    if end_date:
        query += " AND DATE(created_at) <= ?"
        params.append(end_date)
    sort_map = {
        "date_desc": "created_at DESC",
        "date_asc": "created_at ASC",
        "amount_desc": "total_price DESC",
        "amount_asc": "total_price ASC",
    }
    query += " ORDER BY " + sort_map.get(sort, "created_at DESC")
    effective_limit = 500 if (start_date or end_date) else limit
    query += " LIMIT ?"
    params.append(effective_limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    orders = []
    for row in rows:
        order = dict(row)
        order["items"] = json.loads(order["items"])
        orders.append(order)
    return orders


def get_orders_by_date(date_str):
    """Get all non-cancelled orders for a specific preferred_date."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM orders WHERE preferred_date = ? AND status != 'cancelled' ORDER BY created_at",
        (date_str,)
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


# ── Review Requests Tracking ──

def init_review_requests_table():
    """Create review_requests table to track sent review request emails."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            customer_email TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            status TEXT DEFAULT 'sent',
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reminder_sent_at TIMESTAMP,
            UNIQUE(order_id)
        )
    """)
    conn.commit()
    conn.close()


def record_review_request(order_id, customer_email, customer_name):
    """Record that a review request email was sent for an order."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO review_requests (order_id, customer_email, customer_name) VALUES (?, ?, ?)",
            (order_id, customer_email.lower().strip(), customer_name)
        )
        conn.commit()
    except Exception:
        pass
    conn.close()


def record_review_reminder(order_id):
    """Record that a reminder was sent for an order."""
    conn = get_db()
    conn.execute(
        "UPDATE review_requests SET status = 'reminded', reminder_sent_at = CURRENT_TIMESTAMP WHERE order_id = ?",
        (order_id,)
    )
    conn.commit()
    conn.close()


def get_review_requests():
    """Get all review requests with order details and review status."""
    conn = get_db()
    rows = conn.execute("""
        SELECT rr.*, o.items, o.total_price, o.status as order_status, o.created_at as order_date
        FROM review_requests rr
        JOIN orders o ON rr.order_id = o.id
        ORDER BY rr.sent_at DESC
    """).fetchall()
    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        r["items"] = json.loads(r["items"])
        # Check if this customer left any reviews after the request was sent
        reviews = get_reviews_by_email_after(r["customer_email"], r["sent_at"])
        r["reviews_received"] = len(reviews)
        if r["reviews_received"] > 0:
            r["status"] = "reviewed"
        results.append(r)
    return results


def get_reviews_by_email_after(email, after_date):
    """Get reviews by a customer email submitted after a given date."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM reviews WHERE LOWER(customer_email) = ? AND created_at >= ?",
        (email.lower().strip(), after_date)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_customer_review_stats(email):
    """Get per-customer review stats: total reviews, avg rating, response rate."""
    conn = get_db()
    email = email.lower().strip()

    # Total reviews submitted
    review_row = conn.execute(
        "SELECT COUNT(*) as total, AVG(rating) as avg_rating FROM reviews WHERE LOWER(customer_email) = ?",
        (email,)
    ).fetchone()

    # Total review requests sent to this customer
    request_row = conn.execute(
        "SELECT COUNT(*) as total FROM review_requests WHERE customer_email = ?",
        (email,)
    ).fetchone()

    conn.close()

    total_reviews = review_row["total"] if review_row else 0
    avg_rating = round(review_row["avg_rating"], 1) if review_row and review_row["avg_rating"] else 0
    total_requests = request_row["total"] if request_row else 0
    response_rate = round((total_reviews / total_requests * 100)) if total_requests > 0 else 0

    return {
        "total_reviews": total_reviews,
        "avg_rating": avg_rating,
        "total_requests": total_requests,
        "response_rate": min(response_rate, 100)
    }


def get_unrequested_completed_orders():
    """Get completed orders that haven't had a review request sent yet."""
    conn = get_db()
    rows = conn.execute("""
        SELECT o.* FROM orders o
        LEFT JOIN review_requests rr ON o.id = rr.order_id
        WHERE o.status = 'completed' AND rr.id IS NULL AND o.customer_email != ''
        ORDER BY o.created_at DESC
    """).fetchall()
    conn.close()
    results = []
    for row in rows:
        r = dict(row)
        r["items"] = json.loads(r["items"])
        results.append(r)
    return results


def init_expenses_table():
    """Create expenses table if it doesn't exist."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL,
            expense_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def create_expense(category, description, amount, expense_date):
    """Add a new business expense."""
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO expenses (category, description, amount, expense_date) VALUES (?, ?, ?, ?)",
        (category, description or "", amount, expense_date)
    )
    conn.commit()
    expense_id = cursor.lastrowid
    conn.close()
    return expense_id


def get_expenses(start_date=None, end_date=None, sort="date_desc"):
    """Get expenses filtered by date range and sorted."""
    conn = get_db()
    query = "SELECT * FROM expenses WHERE 1=1"
    params = []
    if start_date:
        query += " AND expense_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND expense_date <= ?"
        params.append(end_date)
    sort_map = {
        "date_desc": "expense_date DESC, created_at DESC",
        "date_asc": "expense_date ASC, created_at ASC",
        "amount_desc": "amount DESC",
        "amount_asc": "amount ASC",
    }
    query += " ORDER BY " + sort_map.get(sort, "expense_date DESC, created_at DESC")
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_expense(expense_id, category, description, amount, expense_date):
    """Update an existing expense entry."""
    conn = get_db()
    conn.execute(
        "UPDATE expenses SET category=?, description=?, amount=?, expense_date=? WHERE id=?",
        (category, description or "", amount, expense_date, expense_id)
    )
    conn.commit()
    conn.close()


def delete_expense(expense_id):
    """Delete an expense entry."""
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()


# Initialize database on import
init_db()
init_reviews_table()
init_promo_table()
init_review_requests_table()
init_expenses_table()
