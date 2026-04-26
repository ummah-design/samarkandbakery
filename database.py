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
                 payment_method='cod', payment_status='unpaid', paypal_order_id=None,
                 customer_lang=None):
    """Save a new order. items should be a list of dicts."""
    customer_phone = normalise_phone(customer_phone)
    if customer_email:
        customer_email = customer_email.strip().lower()
    if customer_lang not in ("en", "fr", "ar"):
        customer_lang = None
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO orders (customer_name, customer_email, customer_phone, delivery_type,
                          delivery_address, delivery_lat, delivery_lng,
                          items, total_price, total_cost, total_profit,
                          promo_code, discount_amount, preferred_date, pickup_time, notes,
                          payment_method, payment_status, paypal_order_id, customer_lang)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        customer_name, customer_email, customer_phone, delivery_type,
        delivery_address, delivery_lat, delivery_lng,
        json.dumps(items), total_price, total_cost, total_profit,
        promo_code, discount_amount, preferred_date, pickup_time, notes,
        payment_method, payment_status, paypal_order_id, customer_lang
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


def dismiss_review_request(order_id):
    """Mark a review request as dismissed (manually closed by admin)."""
    conn = get_db()
    conn.execute(
        "UPDATE review_requests SET status = 'dismissed' WHERE order_id = ?",
        (order_id,)
    )
    conn.commit()
    conn.close()


def restore_review_request(order_id):
    """Restore a dismissed review request back to its send/remind state."""
    conn = get_db()
    conn.execute(
        "UPDATE review_requests SET status = CASE WHEN reminder_sent_at IS NULL THEN 'sent' ELSE 'reminded' END WHERE order_id = ? AND status = 'dismissed'",
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


# ── Loyalty Points ──
#
# Earning rate: 1 point per 1 MAD spent (on the post-discount order total).
# Redemption value: 20 points = 1 MAD off (= 5% effective reward).
# Minimum redemption: 100 points (5 MAD).
# Expiry: 12 months from earning date.
# Identity: customer email (verified via 6-digit code before redemption).

LOYALTY_EARN_RATE = 1.0           # points awarded per 1 MAD spent
LOYALTY_REDEEM_VALUE = 0.05       # MAD value of 1 point (so 20 pts = 1 MAD)
LOYALTY_MIN_REDEEM = 100          # minimum points required to redeem
LOYALTY_EXPIRY_MONTHS = 12        # earned points expire 12 months later
LOYALTY_CODE_TTL_MINUTES = 15     # verification code lifetime
LOYALTY_CODE_MAX_ATTEMPTS = 5     # max verify attempts before code is locked


def _normalise_email(email):
    return (email or "").strip().lower()


def init_loyalty_tables():
    """Create loyalty tables if they don't exist."""
    conn = get_db()
    # Ledger of every points movement (earn / redeem / expire / adjust).
    # Balance is always derived from this ledger — no separate balance column to drift.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS loyalty_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            type TEXT NOT NULL,
            points REAL NOT NULL,
            order_id INTEGER,
            expires_at TIMESTAMP,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_loyalty_tx_email ON loyalty_transactions(email)")
    # One-time verification codes for redemption.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS loyalty_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            consumed INTEGER DEFAULT 0,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_loyalty_codes_email ON loyalty_codes(email)")
    conn.commit()
    conn.close()


def get_loyalty_balance(email):
    """
    Return current balance and lifetime stats for an email address.
    Balance = sum of all non-expired ledger entries.
    """
    email = _normalise_email(email)
    if not email:
        return {"email": "", "balance": 0, "lifetime_earned": 0, "redeem_value_mad": 0}
    conn = get_db()
    # Live balance: earned entries that haven't expired, plus any redemptions/adjustments
    row = conn.execute("""
        SELECT
            COALESCE(SUM(CASE
                WHEN type = 'earn' AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) THEN points
                WHEN type IN ('redeem', 'expire', 'adjust') THEN points
                ELSE 0
            END), 0) AS balance,
            COALESCE(SUM(CASE WHEN type = 'earn' THEN points ELSE 0 END), 0) AS lifetime_earned
        FROM loyalty_transactions
        WHERE email = ?
    """, (email,)).fetchone()
    conn.close()
    balance = max(0, int(round(row["balance"])))
    lifetime = int(round(row["lifetime_earned"]))
    return {
        "email": email,
        "balance": balance,
        "lifetime_earned": lifetime,
        "redeem_value_mad": round(balance * LOYALTY_REDEEM_VALUE, 2),
        "min_redeem": LOYALTY_MIN_REDEEM,
        "redeem_value_per_point": LOYALTY_REDEEM_VALUE,
    }


def award_loyalty_points(email, order_total_mad, order_id):
    """
    Award points for a completed/placed order. Skips silently if no email.
    Returns the integer points awarded (0 if none).
    """
    email = _normalise_email(email)
    if not email or not order_total_mad or order_total_mad <= 0:
        return 0
    points = int(round(order_total_mad * LOYALTY_EARN_RATE))
    if points <= 0:
        return 0
    conn = get_db()
    conn.execute("""
        INSERT INTO loyalty_transactions (email, type, points, order_id, expires_at, note)
        VALUES (?, 'earn', ?, ?, datetime(CURRENT_TIMESTAMP, ?), ?)
    """, (email, points, order_id, "+" + str(LOYALTY_EXPIRY_MONTHS) + " months",
          "Earned on order #" + str(order_id)))
    conn.commit()
    conn.close()
    return points


def redeem_loyalty_points(email, points, order_id):
    """Record a redemption (negative ledger entry). Caller must validate balance first."""
    email = _normalise_email(email)
    if not email or points <= 0:
        return False
    conn = get_db()
    conn.execute("""
        INSERT INTO loyalty_transactions (email, type, points, order_id, note)
        VALUES (?, 'redeem', ?, ?, ?)
    """, (email, -abs(int(points)), order_id, "Redeemed on order #" + str(order_id)))
    conn.commit()
    conn.close()
    return True


def adjust_loyalty(email, points, note=""):
    """Admin adjustment — positive or negative integer points."""
    email = _normalise_email(email)
    if not email or not points:
        return False
    conn = get_db()
    expires_clause = ""
    params = [email, int(points), note or "Admin adjustment"]
    if int(points) > 0:
        # Positive admin grants also expire after the same window
        conn.execute("""
            INSERT INTO loyalty_transactions (email, type, points, expires_at, note)
            VALUES (?, 'adjust', ?, datetime(CURRENT_TIMESTAMP, '+%d months'), ?)
        """ % LOYALTY_EXPIRY_MONTHS, params)
    else:
        conn.execute("""
            INSERT INTO loyalty_transactions (email, type, points, note)
            VALUES (?, 'adjust', ?, ?)
        """, params)
    conn.commit()
    conn.close()
    return True


def get_loyalty_transactions(email, limit=50):
    """Get the ledger for an email."""
    email = _normalise_email(email)
    if not email:
        return []
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM loyalty_transactions
        WHERE email = ?
        ORDER BY created_at DESC LIMIT ?
    """, (email, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_loyalty_balances():
    """Aggregate balances per email for the admin dashboard."""
    conn = get_db()
    rows = conn.execute("""
        SELECT
            email,
            COALESCE(SUM(CASE
                WHEN type = 'earn' AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) THEN points
                WHEN type IN ('redeem', 'expire', 'adjust') THEN points
                ELSE 0
            END), 0) AS balance,
            COALESCE(SUM(CASE WHEN type = 'earn' THEN points ELSE 0 END), 0) AS lifetime_earned,
            COALESCE(SUM(CASE WHEN type = 'redeem' THEN -points ELSE 0 END), 0) AS lifetime_redeemed,
            MAX(created_at) AS last_activity
        FROM loyalty_transactions
        GROUP BY email
        ORDER BY balance DESC, last_activity DESC
    """).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["balance"] = max(0, int(round(d["balance"])))
        d["lifetime_earned"] = int(round(d["lifetime_earned"]))
        d["lifetime_redeemed"] = int(round(d["lifetime_redeemed"]))
        d["redeem_value_mad"] = round(d["balance"] * LOYALTY_REDEEM_VALUE, 2)
        out.append(d)
    return out


def create_loyalty_code(email):
    """
    Generate a 6-digit verification code, store it, and return it.
    Invalidates any prior unconsumed code for this email.
    """
    import random
    email = _normalise_email(email)
    if not email:
        return None
    code = "{:06d}".format(random.randint(0, 999999))
    conn = get_db()
    # Invalidate older outstanding codes for this email
    conn.execute("UPDATE loyalty_codes SET consumed = 1 WHERE email = ? AND consumed = 0", (email,))
    conn.execute("""
        INSERT INTO loyalty_codes (email, code, expires_at)
        VALUES (?, ?, datetime(CURRENT_TIMESTAMP, ?))
    """, (email, code, "+" + str(LOYALTY_CODE_TTL_MINUTES) + " minutes"))
    conn.commit()
    conn.close()
    return code


def verify_loyalty_code(email, code):
    """
    Verify a code. Marks the code as verified (but not consumed) on success.
    Returns {"valid": bool, "error": str or None}.
    The code is consumed only when actually used in a redemption (consume_loyalty_code).
    """
    email = _normalise_email(email)
    code = (code or "").strip()
    if not email or not code:
        return {"valid": False, "error": "Email and code required"}
    conn = get_db()
    row = conn.execute("""
        SELECT * FROM loyalty_codes
        WHERE email = ? AND consumed = 0
        ORDER BY id DESC LIMIT 1
    """, (email,)).fetchone()
    if not row:
        conn.close()
        return {"valid": False, "error": "No active code — please request a new one"}
    rec = dict(row)
    # Bump attempts
    conn.execute("UPDATE loyalty_codes SET attempts = attempts + 1 WHERE id = ?", (rec["id"],))
    conn.commit()
    if rec["attempts"] + 1 > LOYALTY_CODE_MAX_ATTEMPTS:
        conn.execute("UPDATE loyalty_codes SET consumed = 1 WHERE id = ?", (rec["id"],))
        conn.commit()
        conn.close()
        return {"valid": False, "error": "Too many attempts — please request a new code"}
    # Check expiry
    expires = conn.execute("SELECT expires_at < CURRENT_TIMESTAMP AS expired FROM loyalty_codes WHERE id = ?",
                           (rec["id"],)).fetchone()
    if expires and expires["expired"]:
        conn.close()
        return {"valid": False, "error": "Code expired — please request a new one"}
    if rec["code"] != code:
        conn.close()
        return {"valid": False, "error": "Incorrect code"}
    conn.execute("UPDATE loyalty_codes SET verified = 1 WHERE id = ?", (rec["id"],))
    conn.commit()
    conn.close()
    return {"valid": True, "error": None}


def consume_loyalty_code(email):
    """
    Mark the most recent verified+unconsumed code for this email as consumed.
    Returns True if a verified code was found and consumed.
    Used at order submission to ensure a verification was completed.
    """
    email = _normalise_email(email)
    if not email:
        return False
    conn = get_db()
    row = conn.execute("""
        SELECT id FROM loyalty_codes
        WHERE email = ? AND consumed = 0 AND verified = 1
          AND expires_at > CURRENT_TIMESTAMP
        ORDER BY id DESC LIMIT 1
    """, (email,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("UPDATE loyalty_codes SET consumed = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()
    return True


# ── Blog ────────────────────────────────────────────────────────────────────


def init_blog_tables():
    """Create blog tables if they don't exist."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blog_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name_en TEXT NOT NULL,
            name_ar TEXT,
            name_fr TEXT,
            slug TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blog_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_en TEXT NOT NULL,
            title_ar TEXT,
            title_fr TEXT,
            slug TEXT UNIQUE NOT NULL,
            content_en TEXT,
            content_ar TEXT,
            content_fr TEXT,
            excerpt_en TEXT,
            excerpt_ar TEXT,
            excerpt_fr TEXT,
            featured_image TEXT,
            status TEXT DEFAULT 'draft',
            published_at TIMESTAMP,
            meta_title TEXT,
            meta_description_en TEXT,
            meta_description_ar TEXT,
            meta_description_fr TEXT,
            focus_keyword TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS blog_post_categories (
            post_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            PRIMARY KEY (post_id, category_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blog_posts_slug ON blog_posts(slug)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blog_posts_status ON blog_posts(status)")
    # Migration: add image_alt column if missing
    try:
        conn.execute("SELECT image_alt FROM blog_posts LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE blog_posts ADD COLUMN image_alt TEXT")
    conn.commit()
    conn.close()


def create_blog_category(name_en, slug, name_ar=None, name_fr=None):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO blog_categories (name_en, name_ar, name_fr, slug) VALUES (?, ?, ?, ?)",
        (name_en, name_ar, name_fr, slug)
    )
    conn.commit()
    cat_id = cursor.lastrowid
    conn.close()
    return cat_id


def update_blog_category(cat_id, name_en, slug, name_ar=None, name_fr=None):
    conn = get_db()
    conn.execute(
        "UPDATE blog_categories SET name_en=?, name_ar=?, name_fr=?, slug=? WHERE id=?",
        (name_en, name_ar, name_fr, slug, cat_id)
    )
    conn.commit()
    conn.close()


def delete_blog_category(cat_id):
    conn = get_db()
    conn.execute("DELETE FROM blog_post_categories WHERE category_id=?", (cat_id,))
    conn.execute("DELETE FROM blog_categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()


def get_blog_categories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM blog_categories ORDER BY name_en").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_blog_category_by_slug(slug):
    conn = get_db()
    row = conn.execute("SELECT * FROM blog_categories WHERE slug=?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_blog_post(title_en, slug, content_en=None, excerpt_en=None,
                     status="draft", meta_title=None, meta_description_en=None,
                     focus_keyword=None, featured_image=None, category_ids=None):
    conn = get_db()
    published_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") if status == "published" else None
    cursor = conn.execute("""
        INSERT INTO blog_posts
            (title_en, slug, content_en, excerpt_en, status, published_at,
             meta_title, meta_description_en, focus_keyword, featured_image)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title_en, slug, content_en, excerpt_en, status, published_at,
          meta_title, meta_description_en, focus_keyword, featured_image))
    post_id = cursor.lastrowid
    if category_ids:
        for cid in category_ids:
            conn.execute(
                "INSERT OR IGNORE INTO blog_post_categories (post_id, category_id) VALUES (?, ?)",
                (post_id, cid)
            )
    conn.commit()
    conn.close()
    return post_id


def update_blog_post(post_id, **fields):
    conn = get_db()
    allowed = {
        "title_en", "title_ar", "title_fr", "slug",
        "content_en", "content_ar", "content_fr",
        "excerpt_en", "excerpt_ar", "excerpt_fr",
        "featured_image", "image_alt", "status", "meta_title",
        "meta_description_en", "meta_description_ar", "meta_description_fr",
        "focus_keyword"
    }
    data = {k: v for k, v in fields.items() if k in allowed}
    if not data:
        conn.close()
        return
    # Handle publish timestamp
    current = conn.execute("SELECT status, published_at FROM blog_posts WHERE id=?", (post_id,)).fetchone()
    if current:
        new_status = data.get("status", current["status"])
        if new_status == "published" and current["published_at"] is None:
            data["published_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    data["updated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(k + "=?" for k in data)
    values = list(data.values()) + [post_id]
    conn.execute("UPDATE blog_posts SET " + set_clause + " WHERE id=?", values)
    # Update categories if provided
    if "category_ids" in fields:
        conn.execute("DELETE FROM blog_post_categories WHERE post_id=?", (post_id,))
        for cid in (fields["category_ids"] or []):
            conn.execute(
                "INSERT OR IGNORE INTO blog_post_categories (post_id, category_id) VALUES (?, ?)",
                (post_id, cid)
            )
    conn.commit()
    conn.close()


def delete_blog_post(post_id):
    conn = get_db()
    conn.execute("DELETE FROM blog_post_categories WHERE post_id=?", (post_id,))
    conn.execute("DELETE FROM blog_posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()


def get_blog_posts(status=None, category_id=None, page=1, per_page=9):
    conn = get_db()
    query = "SELECT p.* FROM blog_posts p WHERE 1=1"
    params = []
    if status:
        query += " AND p.status=?"
        params.append(status)
    if category_id:
        query += " AND p.id IN (SELECT post_id FROM blog_post_categories WHERE category_id=?)"
        params.append(category_id)
    # count
    count_row = conn.execute("SELECT COUNT(*) as total FROM (" + query + ")", params).fetchone()
    total = count_row["total"] if count_row else 0
    query += " ORDER BY p.published_at DESC, p.created_at DESC LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]
    rows = conn.execute(query, params).fetchall()
    conn.close()
    posts = _attach_categories(rows)
    return posts, total


def get_blog_post_by_id(post_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM blog_posts WHERE id=?", (post_id,)).fetchone()
    conn.close()
    if not row:
        return None
    post = dict(row)
    post["categories"] = _get_post_categories(post_id)
    return post


def get_blog_post_by_slug(slug):
    conn = get_db()
    row = conn.execute("SELECT * FROM blog_posts WHERE slug=?", (slug,)).fetchone()
    conn.close()
    if not row:
        return None
    post = dict(row)
    post["categories"] = _get_post_categories(post["id"])
    return post


def get_related_blog_posts(post_id, category_ids, limit=3):
    if not category_ids:
        return []
    conn = get_db()
    placeholders = ",".join("?" for _ in category_ids)
    rows = conn.execute("""
        SELECT DISTINCT p.* FROM blog_posts p
        JOIN blog_post_categories pc ON p.id = pc.post_id
        WHERE pc.category_id IN ({}) AND p.id != ? AND p.status = 'published'
        ORDER BY p.published_at DESC
        LIMIT ?
    """.format(placeholders), category_ids + [post_id, limit]).fetchall()
    conn.close()
    return _attach_categories(rows)


def _get_post_categories(post_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT c.* FROM blog_categories c
        JOIN blog_post_categories pc ON c.id = pc.category_id
        WHERE pc.post_id = ?
    """, (post_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _attach_categories(rows):
    posts = []
    for row in rows:
        post = dict(row)
        post["categories"] = _get_post_categories(post["id"])
        posts.append(post)
    return posts


def blog_slug_exists(slug, exclude_id=None):
    conn = get_db()
    if exclude_id:
        row = conn.execute(
            "SELECT id FROM blog_posts WHERE slug=? AND id!=?", (slug, exclude_id)
        ).fetchone()
    else:
        row = conn.execute("SELECT id FROM blog_posts WHERE slug=?", (slug,)).fetchone()
    conn.close()
    return row is not None


# ── Site config (admin-editable settings) ──

DEFAULT_SITE_CONFIG = {
    "primary_language": "en",
}


def init_site_config_table():
    """Create site_config table if it doesn't exist and seed defaults."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for k, v in DEFAULT_SITE_CONFIG.items():
        conn.execute("INSERT OR IGNORE INTO site_config (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def get_config(key, default=None):
    """Get a single config value by key."""
    conn = get_db()
    row = conn.execute("SELECT value FROM site_config WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row:
        return row["value"]
    return DEFAULT_SITE_CONFIG.get(key, default)


def set_config(key, value):
    """Set a single config value by key."""
    conn = get_db()
    conn.execute("""
        INSERT INTO site_config (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
    """, (key, value))
    conn.commit()
    conn.close()


def get_all_config():
    """Get all config values as a dict, falling back to defaults."""
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM site_config").fetchall()
    conn.close()
    cfg = dict(DEFAULT_SITE_CONFIG)
    for r in rows:
        cfg[r["key"]] = r["value"]
    return cfg


def get_primary_language():
    """Convenience: site default language ('en'/'fr'/'ar')."""
    val = get_config("primary_language", "en")
    if val not in ("en", "fr", "ar"):
        return "en"
    return val


# ── Email templates (admin-editable, stored per type x language) ──

EMAIL_TEMPLATE_TYPES = (
    "order_placed",
    "order_confirmed",
    "order_completed",
    "contact_inquiry",
    "loyalty_code",
)
EMAIL_TEMPLATE_LANGUAGES = ("en", "fr", "ar")


def init_email_templates_table():
    """Create the email_templates table; seed defaults for missing rows."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_templates (
            template_type TEXT NOT NULL,
            language TEXT NOT NULL,
            subject TEXT NOT NULL,
            body_html TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (template_type, language)
        )
    """)
    conn.commit()
    conn.close()
    seed_email_templates()


def seed_email_templates(force=False):
    """Insert default subject/body for any (type, lang) row missing.
    If force=True, overwrite existing rows with defaults."""
    try:
        from email_defaults import DEFAULT_EMAIL_TEMPLATES
    except Exception:
        DEFAULT_EMAIL_TEMPLATES = {}
    conn = get_db()
    for ttype in EMAIL_TEMPLATE_TYPES:
        for lang in EMAIL_TEMPLATE_LANGUAGES:
            tpl = DEFAULT_EMAIL_TEMPLATES.get(ttype, {}).get(lang)
            if not tpl:
                continue
            if force:
                conn.execute("""
                    INSERT INTO email_templates (template_type, language, subject, body_html, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(template_type, language) DO UPDATE SET
                        subject = excluded.subject,
                        body_html = excluded.body_html,
                        updated_at = CURRENT_TIMESTAMP
                """, (ttype, lang, tpl["subject"], tpl["body_html"]))
            else:
                conn.execute("""
                    INSERT OR IGNORE INTO email_templates (template_type, language, subject, body_html)
                    VALUES (?, ?, ?, ?)
                """, (ttype, lang, tpl["subject"], tpl["body_html"]))
    conn.commit()
    conn.close()


def get_email_template(template_type, language):
    """Fetch a single template by (type, lang). Returns dict or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT template_type, language, subject, body_html, updated_at "
        "FROM email_templates WHERE template_type = ? AND language = ?",
        (template_type, language)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_email_template_with_fallback(template_type, language):
    """Fetch a template, falling back to primary_language then 'en'."""
    tpl = get_email_template(template_type, language)
    if tpl:
        return tpl
    primary = get_primary_language()
    if primary != language:
        tpl = get_email_template(template_type, primary)
        if tpl:
            return tpl
    if language != "en" and primary != "en":
        tpl = get_email_template(template_type, "en")
        if tpl:
            return tpl
    return None


def get_all_email_templates():
    """Return all templates as nested dict: {type: {lang: {subject, body_html, updated_at}}}."""
    conn = get_db()
    rows = conn.execute(
        "SELECT template_type, language, subject, body_html, updated_at FROM email_templates"
    ).fetchall()
    conn.close()
    out = {}
    for r in rows:
        out.setdefault(r["template_type"], {})[r["language"]] = {
            "subject": r["subject"],
            "body_html": r["body_html"],
            "updated_at": r["updated_at"],
        }
    return out


def update_email_template(template_type, language, subject, body_html):
    """Save edits to a single template."""
    if template_type not in EMAIL_TEMPLATE_TYPES:
        raise ValueError("Unknown template type: " + str(template_type))
    if language not in EMAIL_TEMPLATE_LANGUAGES:
        raise ValueError("Unknown language: " + str(language))
    conn = get_db()
    conn.execute("""
        INSERT INTO email_templates (template_type, language, subject, body_html, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(template_type, language) DO UPDATE SET
            subject = excluded.subject,
            body_html = excluded.body_html,
            updated_at = CURRENT_TIMESTAMP
    """, (template_type, language, subject, body_html))
    conn.commit()
    conn.close()


def reset_email_template(template_type, language):
    """Restore a single template to its default."""
    try:
        from email_defaults import DEFAULT_EMAIL_TEMPLATES
    except Exception:
        return False
    tpl = DEFAULT_EMAIL_TEMPLATES.get(template_type, {}).get(language)
    if not tpl:
        return False
    update_email_template(template_type, language, tpl["subject"], tpl["body_html"])
    return True


# ── Order language migration ──

def init_order_language_column():
    """Add customer_lang column to orders table if missing."""
    conn = get_db()
    try:
        conn.execute("SELECT customer_lang FROM orders LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE orders ADD COLUMN customer_lang TEXT")
        conn.commit()
    conn.close()


# Initialize database on import
init_db()
init_reviews_table()
init_promo_table()
init_review_requests_table()
init_expenses_table()
init_loyalty_tables()
init_blog_tables()
init_site_config_table()
init_email_templates_table()
init_order_language_column()
