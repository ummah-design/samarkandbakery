#!/usr/bin/env python3
"""
Samarkand Bakery — Web App
Run: python3 app.py
- Customer page: http://localhost:5050
- Admin dashboard: http://localhost:5050/admin (login required)
"""

import json
import os
import functools
import shutil
import glob
import zipfile
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory

from engine import load_data, calculate_cost, calculate_order
try:
    from emailer import send_order_placed, send_order_confirmed, send_order_completed, send_contact_inquiry, send_loyalty_code
except Exception:
    send_order_placed = None
    send_order_confirmed = None
    send_order_completed = None
    send_contact_inquiry = None
    send_loyalty_code = None

try:
    import bot_agent
    _bot_agent_ok = True
except Exception:
    _bot_agent_ok = False
from database import (create_order, get_orders, get_order, get_orders_by_date,
                      update_order_status,
                      get_customers, get_customer_orders,
                      create_review, get_reviews, update_review_status, add_review_reply,
                      get_product_review_summary, is_known_customer, get_customer_review_count,
                      create_promo, validate_promo, use_promo, get_promos, toggle_promo,
                      get_promo_usage,
                      record_review_request, record_review_reminder,
                      dismiss_review_request, restore_review_request,
                      get_review_requests, get_customer_review_stats,
                      get_unrequested_completed_orders,
                      update_payment_status,
                      create_expense, get_expenses, update_expense, delete_expense,
                      get_loyalty_balance, award_loyalty_points, redeem_loyalty_points,
                      adjust_loyalty, get_loyalty_transactions, get_all_loyalty_balances,
                      create_loyalty_code, verify_loyalty_code, consume_loyalty_code,
                      LOYALTY_REDEEM_VALUE, LOYALTY_MIN_REDEEM, LOYALTY_EARN_RATE,
                      create_blog_category, update_blog_category, delete_blog_category,
                      get_blog_categories, get_blog_category_by_slug,
                      create_blog_post, update_blog_post, delete_blog_post,
                      get_blog_posts, get_blog_post_by_id, get_blog_post_by_slug,
                      get_related_blog_posts, blog_slug_exists,
                      get_config, set_config, get_all_config, get_primary_language,
                      get_all_email_templates, get_email_template, update_email_template,
                      reset_email_template, EMAIL_TEMPLATE_TYPES, EMAIL_TEMPLATE_LANGUAGES)
import urllib.request
import urllib.parse
import urllib.error
import base64

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "samarkand-bakery-secret-2026-change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# Admin credentials — change these!
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Samarkand2026!"

# PayPal configuration
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "AfoPR4vq6Of0--mbKy8unlX8mYn2BB_rYg4ea4b6AG0-AeZ6Go-jU-LjpHdZ6Xwx-NtuemNo_k3hqfeE")
PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET", "EHmnwExzUv7LWltcVUeCBR9cq2KuQVpGrsCp0Rqp9p1-LeHkblqXHOXg01992bvcida_d8LPUEH_GjZ7")
PAYPAL_BASE_URL = os.environ.get("PAYPAL_BASE_URL", "https://api-m.paypal.com")  # Use sandbox for testing


def paypal_get_access_token():
    """Get PayPal OAuth2 access token."""
    url = PAYPAL_BASE_URL + "/v1/oauth2/token"
    credentials = base64.b64encode((PAYPAL_CLIENT_ID + ":" + PAYPAL_SECRET).encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", "Basic " + credentials)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode())["access_token"]


# MAD to USD conversion rate — update periodically
MAD_TO_USD = 0.10  # 1 MAD ≈ 0.10 USD (i.e. 10 MAD ≈ 1 USD)


def paypal_create_order(amount, currency="USD"):
    """Create a PayPal order and return the order ID."""
    token = paypal_get_access_token()
    url = PAYPAL_BASE_URL + "/v2/checkout/orders"
    body = json.dumps({
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {
                "currency_code": currency,
                "value": str(round(amount, 2))
            }
        }]
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode())


def paypal_capture_order(paypal_order_id):
    """Capture a PayPal order after customer approval."""
    token = paypal_get_access_token()
    url = PAYPAL_BASE_URL + "/v2/checkout/orders/" + paypal_order_id + "/capture"
    req = urllib.request.Request(url, data=b"", method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode())


def load_menu():
    """Load menu data for the ordering page."""
    with open(os.path.join(DATA_DIR, "menu.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def load_translations():
    """Load UI translations."""
    with open(os.path.join(DATA_DIR, "translations.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def load_blocked_dates():
    """Load blocked delivery dates."""
    path = os.path.join(DATA_DIR, "blocked_dates.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Create file if missing
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass
        return []


def save_blocked_dates(dates):
    """Save blocked delivery dates."""
    path = os.path.join(DATA_DIR, "blocked_dates.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dates, f, indent=2)
    except Exception as e:
        print("Error saving blocked dates: " + str(e))


AUTO_DISCOUNT_DEFAULT = {"enabled": False, "threshold": 200.0, "percent": 5.0}


def load_auto_discount():
    """Load auto-discount settings (threshold-based order discount)."""
    path = os.path.join(DATA_DIR, "auto_discount.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "threshold": float(cfg.get("threshold", 0) or 0),
            "percent": float(cfg.get("percent", 0) or 0),
        }
    except Exception:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(AUTO_DISCOUNT_DEFAULT, f, indent=2)
        except Exception:
            pass
        return dict(AUTO_DISCOUNT_DEFAULT)


def save_auto_discount(cfg):
    """Save auto-discount settings."""
    path = os.path.join(DATA_DIR, "auto_discount.json")
    payload = {
        "enabled": bool(cfg.get("enabled", False)),
        "threshold": float(cfg.get("threshold", 0) or 0),
        "percent": float(cfg.get("percent", 0) or 0),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return payload


def compute_auto_discount(subtotal, promo_applied=False):
    """Return auto-discount amount for a given subtotal, or 0."""
    cfg = load_auto_discount()
    if not cfg["enabled"] or promo_applied:
        return 0.0, cfg
    if cfg["threshold"] <= 0 or cfg["percent"] <= 0:
        return 0.0, cfg
    if subtotal + 1e-9 < cfg["threshold"]:
        return 0.0, cfg
    return round(subtotal * cfg["percent"] / 100.0, 2), cfg


def get_lang():
    """Get current language from query param, session, or fall back to the
    admin-configured primary language."""
    lang = request.args.get("lang")
    if lang in ("en", "fr", "ar"):
        session["lang"] = lang
        return lang
    sess_lang = session.get("lang")
    if sess_lang in ("en", "fr", "ar"):
        return sess_lang
    try:
        return get_primary_language()
    except Exception:
        return "en"


def get_t():
    """Get translations dict for current language."""
    lang = get_lang()
    translations = load_translations()
    return translations.get(lang, translations["en"])


def admin_required(f):
    """Decorator to protect admin routes with login."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.url))
        return f(*args, **kwargs)
    return decorated


# ── Public Pages ──

@app.route("/")
def index():
    """Public-facing ordering page — this is what customers see."""
    menu = load_menu()
    t = get_t()
    lang = get_lang()
    return render_template("order.html", menu=menu, t=t, lang=lang, paypal_client_id=PAYPAL_CLIENT_ID, blocked_dates=load_blocked_dates())


@app.route("/order")
def order_page():
    menu = load_menu()
    t = get_t()
    lang = get_lang()
    return render_template("order.html", menu=menu, t=t, lang=lang, paypal_client_id=PAYPAL_CLIENT_ID, blocked_dates=load_blocked_dates())


@app.route("/product/<product_key>")
def product_page(product_key):
    menu = load_menu()
    t = get_t()
    lang = get_lang()
    item = menu["products"].get(product_key)
    if not item:
        return "Product not found", 404
    # Get translated allergen notice
    suffix = "_" + lang if lang != "en" else ""
    allergen_notice = menu.get("allergen_notice" + suffix, menu.get("allergen_notice", ""))
    return render_template("product.html", item=item, product_key=product_key, allergen_notice=allergen_notice, t=t, lang=lang, menu=menu)


# ── Public API ──

@app.route("/api/menu")
def api_menu():
    menu = load_menu()
    return jsonify(menu)


@app.route("/api/blocked-dates")
def api_public_blocked_dates():
    """Public endpoint for customer calendar to check blocked dates."""
    return jsonify(load_blocked_dates())


@app.route("/api/auto-discount")
def api_public_auto_discount():
    """Public endpoint for customer page to read auto-discount config."""
    return jsonify(load_auto_discount())


@app.route("/api/orders/submit", methods=["POST"])
def api_submit_order():
    req = request.json
    items = req.get("items", [])

    if not items:
        return jsonify({"error": "No items in order"}), 400
    if not req.get("customer_name") or not req.get("customer_phone"):
        return jsonify({"error": "Name and phone are required"}), 400

    menu = load_menu()
    total_price = 0
    order_items = []
    for item in items:
        menu_item = menu["products"].get(item["key"])
        if not menu_item:
            return jsonify({"error": f"Unknown item: {item['key']}"}), 400
        subtotal = menu_item["price"] * item["quantity"]
        total_price += subtotal
        order_items.append({
            "key": item["key"],
            "name": menu_item["name"],
            "quantity": item["quantity"],
            "price": menu_item["price"],
            "subtotal": subtotal
        })

    # Validate and apply promo code if provided
    subtotal = total_price
    promo_code = req.get("promo_code", "").strip().upper() or None
    discount_amt = 0
    promo_applied = False
    if promo_code:
        promo_result = validate_promo(promo_code, subtotal)
        if promo_result.get("valid"):
            discount_amt = promo_result["discount_amount"]
            total_price -= discount_amt
            use_promo(promo_code)
            promo_applied = True

    # Auto-discount (threshold-based) — only if no promo applied
    auto_amt, _ = compute_auto_discount(subtotal, promo_applied=promo_applied)
    if auto_amt > 0:
        discount_amt += auto_amt
        total_price -= auto_amt

    # Loyalty redemption — must be a verified email + a verified code that we now consume.
    # Customer sends loyalty_redeem_points in the payload; we re-validate against live balance.
    loyalty_redeem_pts = 0
    loyalty_redeem_mad = 0
    requested_redeem = int(req.get("loyalty_redeem_points") or 0)
    customer_email_for_loyalty = (req.get("customer_email") or "").strip().lower()
    if requested_redeem > 0 and customer_email_for_loyalty:
        balance = get_loyalty_balance(customer_email_for_loyalty)
        if requested_redeem >= LOYALTY_MIN_REDEEM and requested_redeem <= balance["balance"]:
            # Consume the verified code; if no verified code exists, reject.
            if consume_loyalty_code(customer_email_for_loyalty):
                # Cap so we never push the order below 0
                max_redeem_mad = max(total_price, 0)
                desired_mad = round(requested_redeem * LOYALTY_REDEEM_VALUE, 2)
                loyalty_redeem_mad = min(desired_mad, max_redeem_mad)
                # Recalculate points actually consumed (in case we capped to remaining total)
                loyalty_redeem_pts = int(round(loyalty_redeem_mad / LOYALTY_REDEEM_VALUE))
                total_price -= loyalty_redeem_mad
                discount_amt += loyalty_redeem_mad

    # Manual discount entered by admin (manual order form only)
    manual_discount = float(req.get("manual_discount_amount") or 0)
    if manual_discount > 0:
        manual_discount = min(manual_discount, total_price)
        discount_amt += manual_discount
        total_price -= manual_discount

    data = load_data()
    cost_items = [{"recipe_key": i["key"], "quantity": i["quantity"]} for i in items]
    cost_result = calculate_order(cost_items, data)
    total_cost = cost_result.get("total_cost", 0)
    total_profit = round(total_price - total_cost, 2)

    payment_method = req.get("payment_method", "cod")
    payment_status = "unpaid"
    paypal_oid = None
    if payment_method == "paypal":
        paypal_oid = req.get("paypal_order_id")
        if paypal_oid:
            payment_status = "paid"

    # Capture which language the customer used so future emails about this
    # order can be sent in their language (e.g. confirmed/completed updates).
    customer_lang = req.get("customer_lang") or get_lang()
    if customer_lang not in ("en", "fr", "ar"):
        customer_lang = None

    order_id = create_order(
        customer_name=req["customer_name"],
        customer_email=req.get("customer_email", ""),
        customer_phone=req["customer_phone"],
        delivery_type=req.get("delivery_type", "pickup"),
        delivery_address=req.get("delivery_address"),
        delivery_lat=req.get("delivery_lat"),
        delivery_lng=req.get("delivery_lng"),
        items=order_items,
        total_price=round(total_price, 2),
        total_cost=round(total_cost, 2),
        total_profit=round(total_profit, 2),
        promo_code=promo_code,
        discount_amount=round(discount_amt, 2),
        preferred_date=req.get("preferred_date"),
        pickup_time=req.get("pickup_time"),
        notes=req.get("notes"),
        payment_method=payment_method,
        payment_status=payment_status,
        paypal_order_id=paypal_oid,
        customer_lang=customer_lang
    )

    # Loyalty: write the redemption ledger entry now that we have the order id,
    # then award points on the post-discount total. Skip awarding if no email.
    loyalty_earned_pts = 0
    if customer_email_for_loyalty:
        if loyalty_redeem_pts > 0:
            redeem_loyalty_points(customer_email_for_loyalty, loyalty_redeem_pts, order_id)
        loyalty_earned_pts = award_loyalty_points(customer_email_for_loyalty,
                                                  round(total_price, 2), order_id)

    # Telegram notification
    if _bot_agent_ok:
        try:
            bot_agent.notify_new_order({
                "id": order_id,
                "customer_name": req["customer_name"],
                "customer_phone": req["customer_phone"],
                "items": order_items,
                "total_price": round(total_price, 2),
                "discount_amount": round(discount_amt, 2),
                "promo_code": promo_code,
                "delivery_type": req.get("delivery_type", "pickup"),
                "preferred_date": req.get("preferred_date"),
                "pickup_time": req.get("pickup_time"),
                "delivery_address": req.get("delivery_address"),
                "notes": req.get("notes"),
                "payment_method": payment_method,
                "payment_status": payment_status,
            })
        except Exception:
            pass

    # Send order confirmation email
    if send_order_placed:
        try:
            send_order_placed(
                {
                    "id": order_id,
                    "customer_name": req["customer_name"],
                    "customer_email": req.get("customer_email", ""),
                    "items": order_items,
                    "total_price": round(total_price, 2),
                    "delivery_type": req.get("delivery_type", "pickup"),
                    "pickup_time": req.get("pickup_time"),
                    "delivery_address": req.get("delivery_address"),
                    "preferred_date": req.get("preferred_date"),
                    "promo_code": promo_code,
                    "discount_amount": round(discount_amt, 2),
                    "customer_lang": customer_lang,
                },
                loyalty_earned=loyalty_earned_pts,
                loyalty_redeemed_pts=loyalty_redeem_pts,
                loyalty_redeemed_mad=round(loyalty_redeem_mad, 2)
            )
        except Exception:
            pass

    return jsonify({
        "success": True,
        "order_id": order_id,
        "total_price": round(total_price, 2),
        "payment_method": payment_method,
        "loyalty_redeemed_points": loyalty_redeem_pts,
        "loyalty_redeemed_mad": round(loyalty_redeem_mad, 2),
        "loyalty_earned_points": loyalty_earned_pts,
        "message": f"Order #{order_id} received! We will contact you shortly."
    })


# ── PayPal API ──

@app.route("/api/paypal/create", methods=["POST"])
def api_paypal_create():
    """Create a PayPal order for the given amount (MAD converted to USD)."""
    req = request.json
    amount_mad = req.get("amount", 0)
    if amount_mad <= 0:
        return jsonify({"error": "Invalid amount"}), 400
    try:
        amount_usd = round(amount_mad * MAD_TO_USD, 2)
        if amount_usd < 0.01:
            amount_usd = 0.01
        result = paypal_create_order(amount_usd)
        return jsonify({"id": result["id"], "amount_usd": amount_usd})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/paypal/capture", methods=["POST"])
def api_paypal_capture():
    """Capture a PayPal order after customer approval."""
    req = request.json
    paypal_oid = req.get("paypal_order_id")
    if not paypal_oid:
        return jsonify({"error": "Missing PayPal order ID"}), 400
    try:
        result = paypal_capture_order(paypal_oid)
        status = result.get("status", "")
        if status == "COMPLETED":
            return jsonify({"success": True, "paypal_order_id": paypal_oid})
        else:
            return jsonify({"error": "Payment not completed", "status": status}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Admin Login ──

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            next_url = request.args.get("next", url_for("admin_dashboard"))
            return redirect(next_url)
        else:
            error = "Invalid username or password"
    return render_template("login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("index"))


# ── Admin Pages (all protected) ──

@app.route("/admin")
@admin_required
def admin_dashboard():
    return redirect(url_for("admin_orders_page"))


@app.route("/admin/old")
@admin_required
def admin_dashboard_old():
    """Legacy single-page dashboard (kept as backup)."""
    data = load_data()
    recipes = {k: v["name"] for k, v in data["recipes"].items()}
    menu = load_menu()
    return render_template("index.html", recipes=recipes, menu=menu)


@app.route("/admin/orders")
@admin_required
def admin_orders_page():
    return render_template("admin/orders.html", active_page="orders")


@app.route("/admin/manual-order")
@admin_required
def admin_manual_order_page():
    menu = load_menu()
    return render_template("admin/manual_order.html", active_page="manual_order", menu=menu)


@app.route("/admin/product-cost")
@admin_required
def admin_product_cost_page():
    data = load_data()
    recipes = {k: v["name"] for k, v in data["recipes"].items()}
    return render_template("admin/product_cost.html", active_page="product_cost", recipes=recipes)


@app.route("/admin/order-quote")
@admin_required
def admin_order_quote_page():
    data = load_data()
    recipes = {k: v["name"] for k, v in data["recipes"].items()}
    return render_template("admin/order_quote.html", active_page="order_quote", recipes=recipes)


@app.route("/admin/products")
@admin_required
def admin_products_page():
    return render_template("admin/products.html", active_page="products")


@app.route("/admin/reviews")
@admin_required
def admin_reviews_page():
    return render_template("admin/reviews.html", active_page="reviews")


@app.route("/admin/promo-codes")
@admin_required
def admin_promo_codes_page():
    return render_template("admin/promo_codes.html", active_page="promo_codes")


@app.route("/admin/auto-discount")
@admin_required
def admin_auto_discount_page():
    return render_template("admin/auto_discount.html", active_page="auto_discount")


@app.route("/admin/loyalty")
@admin_required
def admin_loyalty_page():
    return render_template("admin/loyalty.html", active_page="loyalty",
                           earn_rate=LOYALTY_EARN_RATE,
                           redeem_value=LOYALTY_REDEEM_VALUE,
                           min_redeem=LOYALTY_MIN_REDEEM)


@app.route("/api/admin/loyalty/balances")
@admin_required
def api_admin_loyalty_balances():
    return jsonify(get_all_loyalty_balances())


@app.route("/api/admin/loyalty/transactions")
@admin_required
def api_admin_loyalty_transactions():
    email = (request.args.get("email") or "").strip().lower()
    return jsonify(get_loyalty_transactions(email, limit=200))


@app.route("/api/admin/loyalty/adjust", methods=["POST"])
@admin_required
def api_admin_loyalty_adjust():
    req = request.json or {}
    email = (req.get("email") or "").strip().lower()
    points = int(req.get("points") or 0)
    note = (req.get("note") or "").strip()
    if not email or points == 0:
        return jsonify({"success": False, "error": "Email and non-zero points required"}), 400
    adjust_loyalty(email, points, note)
    return jsonify({"success": True, "balance": get_loyalty_balance(email)["balance"]})


@app.route("/api/admin/loyalty/backfill", methods=["POST"])
@admin_required
def api_admin_loyalty_backfill():
    """Award loyalty points for all historical orders not yet credited."""
    import sqlite3
    db_path = os.path.join(BASE_DIR, "data", "orders.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, customer_email, total_price FROM orders "
        "WHERE customer_email != '' AND customer_email IS NOT NULL AND status != 'cancelled'"
    ).fetchall()
    credited_ids = set(
        r[0] for r in conn.execute(
            "SELECT DISTINCT order_id FROM loyalty_transactions "
            "WHERE type='earn' AND order_id IS NOT NULL"
        ).fetchall()
    )
    conn.close()
    awarded = 0
    skipped = 0
    for row in rows:
        if row["id"] in credited_ids:
            skipped += 1
            continue
        email = (row["customer_email"] or "").strip().lower()
        total = float(row["total_price"] or 0)
        if email and total > 0:
            award_loyalty_points(email, total, row["id"])
            awarded += 1
    return jsonify({"success": True, "awarded": awarded, "skipped": skipped})


@app.route("/api/admin/auto-discount", methods=["GET", "POST"])
@admin_required
def api_admin_auto_discount():
    if request.method == "GET":
        return jsonify(load_auto_discount())
    req = request.json or {}
    try:
        threshold = float(req.get("threshold", 0) or 0)
        percent = float(req.get("percent", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid number"}), 400
    if threshold < 0 or percent < 0 or percent > 100:
        return jsonify({"error": "Threshold must be ≥ 0 and percent 0–100."}), 400
    saved = save_auto_discount({
        "enabled": bool(req.get("enabled", False)),
        "threshold": threshold,
        "percent": percent,
    })
    return jsonify({"success": True, "config": saved})


@app.route("/admin/customers")
@admin_required
def admin_customers_page():
    return render_template("admin/customers.html", active_page="customers")


@app.route("/admin/ingredients")
@admin_required
def admin_ingredients_page():
    return render_template("admin/ingredients.html", active_page="ingredients")


@app.route("/admin/production")
@admin_required
def admin_production_page():
    return render_template("admin/production.html", active_page="production")


@app.route("/admin/backups")
@admin_required
def admin_backups_page():
    return render_template("admin/backups.html", active_page="backups")


@app.route("/admin/reports")
@admin_required
def admin_reports_page():
    return render_template("admin/reports.html", active_page="reports")


@app.route("/admin/settings")
@admin_required
def admin_settings_page():
    return render_template("admin/settings.html", active_page="settings")


@app.route("/admin/email-templates")
@admin_required
def admin_email_templates_page():
    return render_template(
        "admin/email_templates.html",
        active_page="email_templates",
        template_types=list(EMAIL_TEMPLATE_TYPES),
        template_languages=list(EMAIL_TEMPLATE_LANGUAGES),
    )


# ── Settings API ──

@app.route("/api/admin/settings", methods=["GET"])
@admin_required
def api_admin_settings_get():
    return jsonify(get_all_config())


@app.route("/api/admin/settings", methods=["POST"])
@admin_required
def api_admin_settings_save():
    data = request.json or {}
    primary = (data.get("primary_language") or "").lower().strip()
    if primary not in ("en", "fr", "ar"):
        return jsonify({"error": "Invalid primary language"}), 400
    set_config("primary_language", primary)
    return jsonify({"success": True, "config": get_all_config()})


# ── Email templates API ──

EMAIL_TEMPLATE_TYPE_META = {
    "order_placed": {
        "label": "Order Placed",
        "description": "Sent to the customer (and admin) when a new order is submitted.",
        "placeholders": [
            "customer_name", "order_id", "total_price", "items_table",
            "delivery_info", "preferred_date_block", "discount_block",
            "loyalty_block", "title",
        ],
    },
    "order_confirmed": {
        "label": "Order Confirmed",
        "description": "Sent to the customer when the order status is changed to 'confirmed'.",
        "placeholders": [
            "customer_name", "order_id", "total_price", "items_table",
            "preferred_date_block", "title",
        ],
    },
    "order_completed": {
        "label": "Order Completed / Review Request",
        "description": "Sent to the customer when an order is marked completed. Includes review CTAs.",
        "placeholders": [
            "customer_name", "order_id", "total_price", "review_links_block", "title",
        ],
    },
    "contact_inquiry": {
        "label": "Contact Form Inquiry",
        "description": "Sent to the admin when a visitor submits the website contact form.",
        "placeholders": ["name", "email", "message", "title"],
    },
    "loyalty_code": {
        "label": "Loyalty Code Verification",
        "description": "Sent to the customer with a 6-digit code when they redeem loyalty points.",
        "placeholders": ["greeting", "code", "ttl_minutes", "customer_name", "title"],
    },
}


@app.route("/api/admin/email-templates", methods=["GET"])
@admin_required
def api_admin_email_templates_list():
    return jsonify({
        "templates": get_all_email_templates(),
        "meta": EMAIL_TEMPLATE_TYPE_META,
        "primary_language": get_primary_language(),
    })


@app.route("/api/admin/email-templates/<template_type>/<language>", methods=["GET"])
@admin_required
def api_admin_email_template_get(template_type, language):
    if template_type not in EMAIL_TEMPLATE_TYPES or language not in EMAIL_TEMPLATE_LANGUAGES:
        return jsonify({"error": "Unknown template"}), 404
    tpl = get_email_template(template_type, language)
    if not tpl:
        return jsonify({"error": "Not found"}), 404
    return jsonify(tpl)


@app.route("/api/admin/email-templates/<template_type>/<language>", methods=["POST"])
@admin_required
def api_admin_email_template_save(template_type, language):
    if template_type not in EMAIL_TEMPLATE_TYPES or language not in EMAIL_TEMPLATE_LANGUAGES:
        return jsonify({"error": "Unknown template"}), 404
    data = request.json or {}
    subject = (data.get("subject") or "").strip()
    body_html = data.get("body_html") or ""
    if not subject or not body_html.strip():
        return jsonify({"error": "Subject and body are required"}), 400
    update_email_template(template_type, language, subject, body_html)
    return jsonify({"success": True})


@app.route("/api/admin/email-templates/<template_type>/<language>/reset", methods=["POST"])
@admin_required
def api_admin_email_template_reset(template_type, language):
    if template_type not in EMAIL_TEMPLATE_TYPES or language not in EMAIL_TEMPLATE_LANGUAGES:
        return jsonify({"error": "Unknown template"}), 404
    ok = reset_email_template(template_type, language)
    if not ok:
        return jsonify({"error": "No default available"}), 500
    return jsonify({"success": True, "template": get_email_template(template_type, language)})


@app.route("/api/admin/email-templates/<template_type>/<language>/preview", methods=["POST"])
@admin_required
def api_admin_email_template_preview(template_type, language):
    """Render a preview using the in-memory subject/body the admin is currently
    editing (so previews reflect unsaved changes)."""
    if template_type not in EMAIL_TEMPLATE_TYPES or language not in EMAIL_TEMPLATE_LANGUAGES:
        return jsonify({"error": "Unknown template"}), 404
    data = request.json or {}
    draft_subject = data.get("subject")
    draft_body = data.get("body_html")
    if draft_subject is not None or draft_body is not None:
        existing = get_email_template(template_type, language) or {}
        update_email_template(
            template_type, language,
            draft_subject if draft_subject is not None else existing.get("subject", ""),
            draft_body if draft_body is not None else existing.get("body_html", ""),
        )
        try:
            from emailer import render_preview
            preview = render_preview(template_type, language)
        finally:
            if existing:
                update_email_template(template_type, language,
                                      existing.get("subject", ""),
                                      existing.get("body_html", ""))
    else:
        from emailer import render_preview
        preview = render_preview(template_type, language)
    return jsonify(preview)


@app.route("/admin/product/<product_key>/edit")
@admin_required
def admin_product_edit(product_key):
    menu = load_menu()
    item = menu["products"].get(product_key)
    if not item:
        return "Product not found", 404
    return render_template("product_edit.html", item=item, product_key=product_key)


# ── Admin API (all protected) ──

@app.route("/api/recipes")
@admin_required
def api_recipes():
    data = load_data()
    menu = load_menu()
    result = []
    for key, recipe in data["recipes"].items():
        menu_item = menu["products"].get(key, {})
        result.append({
            "key": key,
            "name": menu_item.get("name", recipe["name"]),
            "selling_price": menu_item.get("price", recipe["selling_price"]),
            "cooking_method": recipe["cooking"]["method"],
            "image": menu_item.get("image", ""),
            "description": menu_item.get("description", ""),
            "description_long": menu_item.get("description_long", ""),
            "meta_title": menu_item.get("meta_title", ""),
            "meta_description": menu_item.get("meta_description", ""),
            "draft": bool(menu_item.get("draft", False))
        })
    return jsonify(result)


@app.route("/api/admin/product/<product_key>/update", methods=["POST"])
@admin_required
def api_update_product(product_key):
    """Update product description, price, and optionally image."""
    menu = load_menu()
    if product_key not in menu["products"]:
        return jsonify({"error": "Product not found"}), 404

    # Update fields if provided
    name = request.form.get("name")
    description = request.form.get("description")
    description_long = request.form.get("description_long")
    price = request.form.get("price")
    meta_title = request.form.get("meta_title")
    meta_description = request.form.get("meta_description")
    slug = request.form.get("slug")

    if name is not None and name.strip():
        menu["products"][product_key]["name"] = name.strip()
    if description is not None:
        menu["products"][product_key]["description"] = description
    if description_long is not None:
        menu["products"][product_key]["description_long"] = description_long
    if price is not None:
        try:
            new_price = float(price)
            menu["products"][product_key]["price"] = new_price
            # Also update recipes.json to keep costing engine in sync
            recipes_path = os.path.join(DATA_DIR, "recipes.json")
            with open(recipes_path, "r", encoding="utf-8") as f:
                recipes_data = json.load(f)
            if product_key in recipes_data:
                recipes_data[product_key]["selling_price"] = new_price
                with open(recipes_path, "w", encoding="utf-8") as f:
                    json.dump(recipes_data, f, indent=4, ensure_ascii=False)
        except ValueError:
            pass
    if meta_title is not None:
        menu["products"][product_key]["meta_title"] = meta_title
    if meta_description is not None:
        menu["products"][product_key]["meta_description"] = meta_description

    # Publish / draft toggle
    draft_val = request.form.get("draft")
    if draft_val is not None:
        if draft_val in ("true", "1", "True"):
            menu["products"][product_key]["draft"] = True
        else:
            menu["products"][product_key].pop("draft", None)

    # Handle slug change — rename the product key
    new_key = product_key
    if slug is not None and slug.strip():
        import re
        new_slug = re.sub(r'[^a-z0-9_]', '_', slug.strip().lower())
        new_slug = re.sub(r'_+', '_', new_slug).strip('_')
        if new_slug and new_slug != product_key and new_slug not in menu["products"]:
            # Move the product to new key
            menu["products"][new_slug] = menu["products"].pop(product_key)
            # Update category references
            for cat in menu.get("categories", []):
                if product_key in cat["product_keys"]:
                    idx = cat["product_keys"].index(product_key)
                    cat["product_keys"][idx] = new_slug
            new_key = new_slug

    # Handle image upload
    if "image" in request.files:
        file = request.files["image"]
        if file.filename:
            import werkzeug.utils
            # Keep original extension
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                return jsonify({"error": "Only JPG, PNG, WEBP images allowed"}), 400
            filename = product_key + ext
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "products", filename)
            file.save(filepath)
            # Remove old image if different filename AND no other product uses it
            old_image = menu["products"][product_key].get("image", "")
            if old_image and old_image != filename:
                other_uses = any(p.get("image") == old_image for k, p in menu["products"].items() if k != product_key)
                if not other_uses:
                    old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "products", old_image)
                    if os.path.exists(old_path):
                        os.remove(old_path)
            menu["products"][product_key]["image"] = filename

    # Save menu.json
    menu_path = os.path.join(DATA_DIR, "menu.json")
    with open(menu_path, "w", encoding="utf-8") as f:
        json.dump(menu, f, indent=4, ensure_ascii=False)

    return jsonify({"success": True, "key": new_key, "image": menu["products"][new_key].get("image", "")})


@app.route("/api/admin/product/gallery/add", methods=["POST"])
@admin_required
def api_gallery_add():
    product_key = request.form.get("product_key")
    menu = load_menu()
    if product_key not in menu["products"]:
        return jsonify({"error": "Product not found"}), 404
    file = request.files.get("gallery_image")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        return jsonify({"error": "Only JPG, PNG, WEBP allowed"}), 400
    # Generate unique filename
    import time
    filename = product_key + "_gallery_" + str(int(time.time())) + ext
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "products", filename)
    file.save(filepath)
    # Add to gallery list
    if "gallery" not in menu["products"][product_key]:
        menu["products"][product_key]["gallery"] = []
    menu["products"][product_key]["gallery"].append(filename)
    menu_path = os.path.join(DATA_DIR, "menu.json")
    with open(menu_path, "w", encoding="utf-8") as f:
        json.dump(menu, f, indent=4, ensure_ascii=False)
    return jsonify({"success": True, "filename": filename})


@app.route("/api/admin/product/gallery/remove", methods=["POST"])
@admin_required
def api_gallery_remove():
    req = request.get_json()
    product_key = req.get("product_key")
    filename = req.get("filename")
    menu = load_menu()
    if product_key not in menu["products"]:
        return jsonify({"error": "Product not found"}), 404
    gallery = menu["products"][product_key].get("gallery", [])
    if filename in gallery:
        gallery.remove(filename)
        menu["products"][product_key]["gallery"] = gallery
        menu_path = os.path.join(DATA_DIR, "menu.json")
        with open(menu_path, "w", encoding="utf-8") as f:
            json.dump(menu, f, indent=4, ensure_ascii=False)
        # Delete file
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "products", filename)
        if os.path.exists(filepath):
            os.remove(filepath)
    return jsonify({"success": True})


@app.route("/api/admin/product/<product_key>/video/upload", methods=["POST"])
@admin_required
def api_video_upload(product_key):
    """Upload a video, strip audio with ffmpeg, save to static/products/."""
    import time
    import subprocess
    menu = load_menu()
    if product_key not in menu["products"]:
        return jsonify({"error": "Product not found"}), 404
    file = request.files.get("video")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext != ".mp4":
        return jsonify({"error": "Only MP4 files allowed"}), 400
    timestamp = str(int(time.time()))
    filename = product_key + "_" + timestamp + ".mp4"
    products_dir = os.path.join(BASE_DIR, "static", "products")
    os.makedirs(products_dir, exist_ok=True)
    temp_path = os.path.join(products_dir, "_temp_" + filename)
    final_path = os.path.join(products_dir, filename)
    file.save(temp_path)
    # Try to strip audio with ffmpeg
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", temp_path, "-an", "-c:v", "copy", final_path],
            capture_output=True, timeout=120
        )
        if result.returncode == 0:
            os.remove(temp_path)
        else:
            # ffmpeg failed, use original with audio
            os.rename(temp_path, final_path)
    except Exception:
        # ffmpeg not available, save with audio
        os.rename(temp_path, final_path)
    # Add to videos array in menu.json
    if "videos" not in menu["products"][product_key]:
        menu["products"][product_key]["videos"] = []
    menu["products"][product_key]["videos"].append(filename)
    menu_path = os.path.join(DATA_DIR, "menu.json")
    with open(menu_path, "w", encoding="utf-8") as f:
        json.dump(menu, f, indent=4, ensure_ascii=False)
    return jsonify({"success": True, "filename": filename})


@app.route("/api/admin/product/<product_key>/video/remove", methods=["POST"])
@admin_required
def api_video_remove(product_key):
    """Remove a video filename from the product's videos array (keeps file on disk)."""
    req = request.get_json()
    filename = req.get("filename")
    menu = load_menu()
    if product_key not in menu["products"]:
        return jsonify({"error": "Product not found"}), 404
    videos = menu["products"][product_key].get("videos", [])
    if filename in videos:
        videos.remove(filename)
        menu["products"][product_key]["videos"] = videos
        menu_path = os.path.join(DATA_DIR, "menu.json")
        with open(menu_path, "w", encoding="utf-8") as f:
            json.dump(menu, f, indent=4, ensure_ascii=False)
    return jsonify({"success": True})


@app.route("/api/admin/product/<product_key>/set-cover", methods=["POST"])
@admin_required
def api_set_cover(product_key):
    req = request.get_json()
    filename = req.get("filename")
    menu = load_menu()
    if product_key not in menu["products"]:
        return jsonify({"error": "Product not found"}), 404
    gallery = menu["products"][product_key].get("gallery", [])
    if filename not in gallery:
        return jsonify({"error": "Image not in gallery"}), 400
    # Swap: old cover goes to gallery, selected gallery image becomes cover
    old_cover = menu["products"][product_key].get("image", "")
    menu["products"][product_key]["image"] = filename
    gallery.remove(filename)
    if old_cover:
        gallery.insert(0, old_cover)
    menu["products"][product_key]["gallery"] = gallery
    menu_path = os.path.join(DATA_DIR, "menu.json")
    with open(menu_path, "w", encoding="utf-8") as f:
        json.dump(menu, f, indent=4, ensure_ascii=False)
    return jsonify({"success": True})


@app.route("/api/prices")
@admin_required
def api_prices():
    data = load_data()
    prices = {k: v for k, v in data["ingredients"].items() if not k.startswith("_")}
    return jsonify(prices)


@app.route("/api/cost")
@admin_required
def api_cost():
    data = load_data()
    recipe_key = request.args.get("recipe")
    quantity = int(request.args.get("quantity", 1))
    result = calculate_cost(recipe_key, quantity, data)
    return jsonify(result)


@app.route("/api/order", methods=["POST"])
@admin_required
def api_order():
    data = load_data()
    order_items = request.json.get("items", [])
    result = calculate_order(order_items, data)
    return jsonify(result)


@app.route("/api/admin/orders")
@admin_required
def api_admin_orders():
    status = request.args.get("status")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    sort = request.args.get("sort", "date_desc")
    orders = get_orders(status=status, start_date=start_date, end_date=end_date, sort=sort)
    return jsonify(orders)


@app.route("/api/admin/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def api_update_order_status(order_id):
    new_status = request.json.get("status")
    if new_status not in ("pending", "confirmed", "completed", "cancelled"):
        return jsonify({"error": "Invalid status"}), 400
    update_order_status(order_id, new_status)

    # Send email notifications on status change
    try:
        order = get_order(order_id)
        if order and new_status == "confirmed" and send_order_confirmed:
            send_order_confirmed(order)
        elif order and new_status == "completed":
            if send_order_completed:
                send_order_completed(order)
            # Track the review request
            if order.get("customer_email"):
                record_review_request(order_id, order["customer_email"], order["customer_name"])
    except Exception:
        pass

    return jsonify({"success": True})


@app.route("/api/admin/orders/<int:order_id>/delete", methods=["POST"])
@admin_required
def api_delete_order(order_id):
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "orders.db")
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/admin/orders/<int:order_id>/payment", methods=["POST"])
@admin_required
def api_update_payment_status(order_id):
    new_status = request.json.get("payment_status")
    if new_status not in ("paid", "unpaid"):
        return jsonify({"error": "Invalid payment status"}), 400
    update_payment_status(order_id, new_status)
    return jsonify({"success": True})


@app.route("/api/admin/customers")
@admin_required
def api_admin_customers():
    customers = get_customers()
    return jsonify(customers)


@app.route("/api/admin/customers/<path:email>/orders")
@admin_required
def api_admin_customer_orders(email):
    orders = get_customer_orders(email)
    return jsonify(orders)


@app.route("/api/admin/customer-orders")
@admin_required
def api_admin_customer_orders_by_query():
    """Alternative endpoint using query param to avoid URL encoding issues."""
    email = request.args.get("email", "")
    orders = get_customer_orders(email)
    return jsonify(orders)


@app.route("/api/admin/customer-lookup")
@admin_required
def api_customer_lookup():
    """Look up a customer by email for manual order auto-fill."""
    email = request.args.get("email", "").strip().lower()
    if not email:
        return jsonify({"found": False})
    orders = get_customer_orders(email)
    if orders:
        latest = orders[0]
        return jsonify({
            "found": True,
            "customer_name": latest["customer_name"],
            "customer_phone": latest["customer_phone"],
            "order_count": len(orders),
            "total_spent": round(sum(o["total_price"] for o in orders), 2)
        })
    return jsonify({"found": False})


@app.route("/api/admin/blocked-dates", methods=["GET", "POST"])
@admin_required
def api_blocked_dates():
    """Get or update blocked delivery dates."""
    if request.method == "GET":
        return jsonify(load_blocked_dates())
    req = request.json
    date = req.get("date")
    action = req.get("action", "block")
    dates = load_blocked_dates()
    if action == "block" and date not in dates:
        dates.append(date)
        dates.sort()
    elif action == "unblock" and date in dates:
        dates.remove(date)
    save_blocked_dates(dates)
    return jsonify({"success": True, "blocked_dates": dates})


@app.route("/api/admin/production/<date>")
@admin_required
def api_production_plan(date):
    """Get orders for a specific delivery date and calculate total ingredients needed."""
    import math
    orders = get_orders_by_date(date)
    data = load_data()
    recipes = data["recipes"]
    ingredients_db = data["ingredients"]

    # Aggregate product quantities across all orders
    product_totals = {}
    for order in orders:
        for item in order.get("items", []):
            key = item["key"]
            qty = item["quantity"]
            product_totals[key] = product_totals.get(key, 0) + qty

    # Calculate total ingredients needed (proportional costing)
    ingredient_totals = {}
    for recipe_key, quantity in product_totals.items():
        recipe = recipes.get(recipe_key)
        if not recipe:
            continue
        for comp_name, comp in recipe["components"].items():
            batch_yield = comp["yields"]
            fraction = quantity / batch_yield
            for ing_key, amount_per_batch in comp["ingredients"].items():
                base_key = ing_key.split("__")[0]
                needed = amount_per_batch * fraction
                if base_key not in ingredient_totals:
                    ingredient_totals[base_key] = 0.0
                ingredient_totals[base_key] += needed

    # Build ingredient list with costs
    shopping_list = []
    total_cost = 0.0
    for ing_key, amount in sorted(ingredient_totals.items()):
        if ing_key.startswith("water"):
            continue
        price = ingredients_db.get(ing_key, 0)
        cost = price * amount
        total_cost += cost
        # Format name nicely
        name = ing_key.replace("_per_kg", "").replace("_per_litre", "").replace("_per_pot", "").replace("_each", "").replace("_", " ").title()
        unit = "kg"
        if "per_litre" in ing_key:
            unit = "L"
        elif "per_pot" in ing_key:
            unit = "pots"
        elif "_each" in ing_key:
            unit = "pcs"
        elif "per_tub" in ing_key:
            unit = "tubs"
        shopping_list.append({
            "key": ing_key,
            "name": name,
            "amount": round(amount, 3),
            "unit": unit,
            "cost": round(cost, 2)
        })

    return jsonify({
        "date": date,
        "orders": orders,
        "product_totals": product_totals,
        "shopping_list": shopping_list,
        "total_ingredient_cost": round(total_cost, 2)
    })


# ── Public Reviews API ──

@app.route("/api/contact", methods=["POST"])
def api_contact():
    """Send contact form inquiry via email."""
    data = request.get_json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    message = data.get("message", "").strip()
    if not name or not email or not message:
        return jsonify({"error": "All fields are required"}), 400
    if send_contact_inquiry:
        ok = send_contact_inquiry(name, email, message, language=get_lang())
        if ok:
            return jsonify({"success": True})
        return jsonify({"error": "Failed to send email"}), 500
    return jsonify({"error": "Email not configured"}), 500


@app.route("/api/reviews/all")
def api_all_reviews():
    """Get all approved reviews across all products (for homepage)."""
    reviews = get_reviews(status="approved")
    # Enrich with product names from menu
    menu = load_menu()
    for r in reviews:
        product = menu["products"].get(r.get("product_key", ""), {})
        r["product_name"] = product.get("name", r.get("product_key", ""))
    return jsonify(reviews)


@app.route("/api/reviews/<product_key>")
def api_product_reviews(product_key):
    """Get approved reviews for a product."""
    reviews = get_reviews(product_key=product_key, status="approved")
    summary = get_product_review_summary(product_key)
    return jsonify({"reviews": reviews, "summary": summary})


@app.route("/api/reviews/<product_key>/submit", methods=["POST"])
def api_submit_review(product_key):
    """Submit a review (goes to pending moderation)."""
    req = request.json
    name = req.get("name", "").strip()
    email = req.get("email", "").strip()
    rating = req.get("rating", 0)
    text = req.get("text", "").strip()

    if not name or not rating or not text:
        return jsonify({"error": "Name, rating, and review text are required"}), 400
    if rating < 1 or rating > 5:
        return jsonify({"error": "Rating must be between 1 and 5"}), 400

    review_id = create_review(product_key, name, email, rating, text)
    return jsonify({"success": True, "message": "Thank you! Your review will appear after approval."})


# ── Admin Reviews API ──

@app.route("/api/admin/reviews")
@admin_required
def api_admin_reviews():
    """Get all reviews for moderation, enriched with customer info."""
    status = request.args.get("status")
    reviews = get_reviews(status=status)
    for r in reviews:
        email = r.get("customer_email", "")
        r["is_known_customer"] = is_known_customer(email) if email else False
        r["total_reviews"] = get_customer_review_count(email) if email else 0
    return jsonify(reviews)


@app.route("/api/admin/reviews/<int:review_id>/status", methods=["POST"])
@admin_required
def api_admin_review_status(review_id):
    new_status = request.json.get("status")
    if new_status not in ("approved", "rejected"):
        return jsonify({"error": "Invalid status"}), 400
    update_review_status(review_id, new_status)
    return jsonify({"success": True})


@app.route("/api/admin/reviews/<int:review_id>/date", methods=["POST"])
@admin_required
def api_admin_review_update_date(review_id):
    """Update review date (admin only)."""
    new_date = request.json.get("date")
    if not new_date:
        return jsonify({"error": "Date required"}), 400
    import sqlite3
    db_path = os.path.join(DATA_DIR, "orders.db")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE reviews SET created_at = ? WHERE id = ?", (new_date, review_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/admin/reviews/<int:review_id>/reply", methods=["POST"])
@admin_required
def api_admin_review_reply(review_id):
    reply = request.json.get("reply", "").strip()
    if not reply:
        return jsonify({"error": "Reply cannot be empty"}), 400
    add_review_reply(review_id, reply)
    return jsonify({"success": True})


# ── Admin Review Requests API ──

@app.route("/api/admin/review-requests")
@admin_required
def api_admin_review_requests():
    """Get all review request tracking data."""
    return jsonify(get_review_requests())


@app.route("/api/admin/review-requests/unrequested")
@admin_required
def api_admin_unrequested():
    """Get completed orders that haven't had a review request sent."""
    return jsonify(get_unrequested_completed_orders())


@app.route("/api/admin/review-requests/send", methods=["POST"])
@admin_required
def api_admin_send_review_request():
    """Manually send a review request email for an order."""
    order_id = request.json.get("order_id")
    order = get_order(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    if not order.get("customer_email"):
        return jsonify({"error": "No email address for this customer"}), 400

    if send_order_completed:
        try:
            send_order_completed(order)
        except Exception:
            return jsonify({"error": "Failed to send email"}), 500

    record_review_request(order_id, order["customer_email"], order["customer_name"])
    return jsonify({"success": True})


@app.route("/api/admin/review-requests/<int:order_id>/remind", methods=["POST"])
@admin_required
def api_admin_send_reminder(order_id):
    """Send a reminder review request email."""
    order = get_order(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    if not order.get("customer_email"):
        return jsonify({"error": "No email address"}), 400

    if send_order_completed:
        try:
            send_order_completed(order)
        except Exception:
            return jsonify({"error": "Failed to send email"}), 500

    record_review_reminder(order_id)
    return jsonify({"success": True})


@app.route("/api/admin/review-requests/<int:order_id>/dismiss", methods=["POST"])
@admin_required
def api_admin_dismiss_review_request(order_id):
    """Dismiss a review request so it stops appearing in Awaiting."""
    dismiss_review_request(order_id)
    return jsonify({"success": True})


@app.route("/api/admin/review-requests/<int:order_id>/restore", methods=["POST"])
@admin_required
def api_admin_restore_review_request(order_id):
    """Restore a previously dismissed review request."""
    restore_review_request(order_id)
    return jsonify({"success": True})


@app.route("/api/admin/review-requests/stats/<path:email>")
@admin_required
def api_admin_customer_review_stats(email):
    """Get review stats for a specific customer."""
    return jsonify(get_customer_review_stats(email))


# ── Public Promo API ──

@app.route("/api/promo/validate", methods=["POST"])
def api_validate_promo():
    code = request.json.get("code", "")
    order_total = request.json.get("order_total", 0)
    result = validate_promo(code, order_total)
    return jsonify(result)


# ── Public Loyalty API ──

@app.route("/api/loyalty/balance")
def api_loyalty_balance():
    """Look up a customer's loyalty balance by email."""
    email = (request.args.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"balance": 0, "lifetime_earned": 0, "redeem_value_mad": 0,
                        "min_redeem": LOYALTY_MIN_REDEEM,
                        "redeem_value_per_point": LOYALTY_REDEEM_VALUE,
                        "earn_rate": LOYALTY_EARN_RATE})
    bal = get_loyalty_balance(email)
    bal["earn_rate"] = LOYALTY_EARN_RATE
    return jsonify(bal)


@app.route("/api/loyalty/send-code", methods=["POST"])
def api_loyalty_send_code():
    """Generate and email a 6-digit verification code so the customer can redeem points."""
    req = request.json or {}
    email = (req.get("email") or "").strip().lower()
    name = (req.get("customer_name") or "").strip() or None
    if not email or "@" not in email:
        return jsonify({"success": False, "error": "Valid email required"}), 400
    bal = get_loyalty_balance(email)
    if bal["balance"] < LOYALTY_MIN_REDEEM:
        return jsonify({"success": False,
                        "error": f"You need at least {LOYALTY_MIN_REDEEM} points to redeem"}), 400
    code = create_loyalty_code(email)
    if not code:
        return jsonify({"success": False, "error": "Could not generate code"}), 500
    if send_loyalty_code:
        try:
            send_loyalty_code(email, code, customer_name=name, language=get_lang())
        except Exception as e:
            print("Loyalty code email error: " + str(e))
    return jsonify({"success": True})


@app.route("/api/loyalty/verify-code", methods=["POST"])
def api_loyalty_verify_code():
    """Verify a 6-digit code. Does not consume it — that happens on order submit."""
    req = request.json or {}
    email = (req.get("email") or "").strip().lower()
    code = (req.get("code") or "").strip()
    result = verify_loyalty_code(email, code)
    if result["valid"]:
        bal = get_loyalty_balance(email)
        result["balance"] = bal["balance"]
        result["redeem_value_mad"] = bal["redeem_value_mad"]
    return jsonify(result)


# ── Admin Promo API ──

@app.route("/api/admin/promos")
@admin_required
def api_admin_promos():
    return jsonify(get_promos())


@app.route("/api/admin/promos/create", methods=["POST"])
@admin_required
def api_admin_create_promo():
    req = request.json
    code = req.get("code", "")
    discount_type = req.get("discount_type", "percentage")
    discount_value = req.get("discount_value", 0)
    min_order = req.get("min_order", 0)
    max_uses = req.get("max_uses", 0)
    if not code or not discount_value:
        return jsonify({"error": "Code and discount value required"}), 400
    success = create_promo(code, discount_type, discount_value, min_order, max_uses)
    if not success:
        return jsonify({"error": "Code already exists"}), 400
    return jsonify({"success": True})


@app.route("/api/admin/promos/<code>/usage")
@admin_required
def api_admin_promo_usage(code):
    """Get all orders that used a specific promo code."""
    usage = get_promo_usage(code)
    return jsonify(usage)


@app.route("/api/admin/promos/<int:promo_id>/toggle", methods=["POST"])
@admin_required
def api_admin_toggle_promo(promo_id):
    active = request.json.get("active", True)
    toggle_promo(promo_id, active)
    return jsonify({"success": True})


# ── Public API: Recent orders for social proof ──

@app.route("/api/recent-orders")
def api_recent_orders():
    """Return recent orders for social proof pop-ups (first name only)."""
    # Show confirmed and completed orders (not pending or cancelled)
    all_orders = get_orders(limit=50)
    orders = [o for o in all_orders if o["status"] in ("confirmed", "completed")]
    recent = []
    for o in orders:
        first_name = o["customer_name"].split()[0] if o["customer_name"] else "Someone"
        items_summary = ", ".join(
            f"{i['quantity']} {i['name']}" for i in o["items"][:2]
        )
        if len(o["items"]) > 2:
            items_summary += f" +{len(o['items']) - 2} more"
        recent.append({
            "name": first_name,
            "items": items_summary,
            "time": o["created_at"]
        })
    return jsonify(recent)


# ── Backup & Restore API ──

@app.route("/api/admin/backup/create", methods=["POST"])
@admin_required
def api_admin_backup_create():
    """Create a timestamped backup zip of all data, database, and product images."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = "backup_" + timestamp + ".zip"
    zip_path = os.path.join(BACKUP_DIR, filename)

    data_files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    db_path = os.path.join(DATA_DIR, "orders.db")
    products_dir = os.path.join(BASE_DIR, "static", "products")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add JSON data files
        for fp in data_files:
            arcname = "data/" + os.path.basename(fp)
            zf.write(fp, arcname)
        # Add database
        if os.path.exists(db_path):
            zf.write(db_path, "data/orders.db")
        # Add product images
        if os.path.isdir(products_dir):
            for img in os.listdir(products_dir):
                img_path = os.path.join(products_dir, img)
                if os.path.isfile(img_path):
                    zf.write(img_path, "static/products/" + img)

    size = os.path.getsize(zip_path)
    return jsonify({"filename": filename, "size": size})


@app.route("/api/admin/backups")
@admin_required
def api_admin_backups():
    """List all backup zip files."""
    backups = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.endswith(".zip") and f.startswith("backup_"):
            fp = os.path.join(BACKUP_DIR, f)
            stat = os.stat(fp)
            backups.append({
                "filename": f,
                "size": stat.st_size,
                "date": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            })
    return jsonify(backups)


@app.route("/api/admin/backup/restore", methods=["POST"])
@admin_required
def api_admin_backup_restore():
    """Restore data from a backup zip file."""
    filename = request.json.get("filename", "")
    if not filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    zip_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(zip_path):
        return jsonify({"error": "Backup not found"}), 404

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.startswith("data/"):
                target = os.path.join(BASE_DIR, member)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
            elif member.startswith("static/products/"):
                target = os.path.join(BASE_DIR, member)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())

    return jsonify({"success": True})


@app.route("/api/admin/backup/download/<filename>")
@admin_required
def api_admin_backup_download(filename):
    """Download a backup zip file."""
    if ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)


@app.route("/api/admin/backup/delete", methods=["POST"])
@admin_required
def api_admin_backup_delete():
    """Delete a backup zip file."""
    filename = request.json.get("filename", "")
    if not filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    zip_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(zip_path):
        return jsonify({"error": "Backup not found"}), 404
    os.remove(zip_path)
    return jsonify({"success": True})


# ── Ingredients list (for expense form) ──

@app.route("/api/admin/ingredients-list")
@admin_required
def api_admin_ingredients_list():
    data = load_data()
    ingredients = data.get("ingredients", {})
    result = []
    for key, price in ingredients.items():
        if key.startswith("_"):
            continue
        if "_per_" in key:
            parts = key.split("_per_")
            name = parts[0].replace("_", " ").title()
            unit = "per " + parts[1].replace("_", " ")
        elif key.endswith("_each"):
            name = key[:-5].replace("_", " ").title()
            unit = "each"
        else:
            name = key.replace("_", " ").title()
            unit = ""
        label = name
        result.append({"key": key, "name": name, "unit": unit, "label": label, "price": price})
    result.sort(key=lambda x: x["name"])
    return jsonify(result)


# ── Expenses ──

@app.route("/admin/expenses")
@admin_required
def admin_expenses_page():
    return render_template("admin/expenses.html", active_page="expenses")


@app.route("/api/admin/expenses")
@admin_required
def api_admin_expenses_list():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    sort = request.args.get("sort", "date_desc")
    expenses = get_expenses(start_date=start_date, end_date=end_date, sort=sort)
    return jsonify(expenses)


@app.route("/api/admin/expenses", methods=["POST"])
@admin_required
def api_admin_expenses_create():
    data = request.json or {}
    category = (data.get("category") or "").strip()
    description = (data.get("description") or "").strip()
    expense_date = (data.get("expense_date") or "").strip()
    try:
        amount = float(data.get("amount", 0))
    except Exception:
        amount = 0
    if not category or not expense_date or amount <= 0:
        return jsonify({"error": "Category, date and a positive amount are required"}), 400
    expense_id = create_expense(category, description, amount, expense_date)
    return jsonify({"success": True, "id": expense_id})


@app.route("/api/admin/expenses/<int:expense_id>", methods=["PUT"])
@admin_required
def api_admin_expenses_update(expense_id):
    data = request.json or {}
    category = (data.get("category") or "").strip()
    description = (data.get("description") or "").strip()
    expense_date = (data.get("expense_date") or "").strip()
    try:
        amount = float(data.get("amount", 0))
    except Exception:
        amount = 0
    if not category or not expense_date or amount <= 0:
        return jsonify({"error": "Category, date and a positive amount are required"}), 400
    update_expense(expense_id, category, description, amount, expense_date)
    return jsonify({"success": True})


@app.route("/api/admin/expenses/<int:expense_id>/delete", methods=["POST"])
@admin_required
def api_admin_expenses_delete(expense_id):
    delete_expense(expense_id)
    return jsonify({"success": True})


# ── Reports / Analytics ───────────────────────────────────────────────────────

@app.route("/api/admin/reports")
@admin_required
def api_admin_reports():
    """Aggregate analytics for the Reports dashboard.

    Query params:
      start_date, end_date — YYYY-MM-DD (inclusive). Both optional.
    """
    start_date = (request.args.get("start_date") or "").strip() or None
    end_date = (request.args.get("end_date") or "").strip() or None

    # Pull all orders in range (large limit; date filter caps it server-side).
    orders = get_orders(start_date=start_date, end_date=end_date, limit=10000)
    # Cancelled orders are excluded from financial calculations but kept for status counts.
    active_orders = [o for o in orders if (o.get("status") or "") != "cancelled"]

    menu = load_menu()
    products = menu.get("products", {})
    categories = menu.get("categories", [])

    # Build product_key -> category name map
    product_to_category = {}
    for cat in categories:
        cat_name = cat.get("name") or "Uncategorised"
        for k in cat.get("product_keys", []) or []:
            product_to_category[k] = cat_name

    # ── KPIs and financial roll-up ────────────────────────────────────────
    total_revenue = 0.0
    total_cost = 0.0
    total_profit = 0.0
    total_discount = 0.0
    total_items = 0
    customer_emails = set()
    customer_phones = set()

    # Per-product aggregation
    product_stats = {}
    # Per-category
    category_stats = {}
    # Status / payment / delivery / time-of-day buckets
    status_counts = {}
    payment_counts = {}
    delivery_counts = {"delivery": 0, "pickup": 0}
    hour_buckets = [0] * 24
    dow_buckets = [0] * 7  # 0 = Mon, 6 = Sun
    # Per-day timeseries
    daily = {}
    # Top customers
    customer_stats = {}
    # Promo usage
    promo_stats = {}

    def _parse_dt(value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            try:
                return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                return None

    # Status counts include all orders (so cancelled shows up too)
    for o in orders:
        st = (o.get("status") or "unknown").lower()
        status_counts[st] = status_counts.get(st, 0) + 1

    for o in active_orders:
        revenue = float(o.get("total_price") or 0)
        cost = float(o.get("total_cost") or 0)
        profit = float(o.get("total_profit") or 0)
        discount = float(o.get("discount_amount") or 0)
        total_revenue += revenue
        total_cost += cost
        total_profit += profit
        total_discount += discount

        email = (o.get("customer_email") or "").strip().lower()
        phone = (o.get("customer_phone") or "").strip()
        if email:
            customer_emails.add(email)
        elif phone:
            customer_phones.add(phone)

        # Payment method
        pm = (o.get("payment_method") or "cod").lower()
        payment_counts[pm] = payment_counts.get(pm, 0) + 1

        # Delivery vs pickup
        dt_type = (o.get("delivery_type") or "").lower()
        if dt_type == "pickup":
            delivery_counts["pickup"] += 1
        else:
            delivery_counts["delivery"] += 1

        # Time-of-day / day-of-week from created_at
        dt = _parse_dt(o.get("created_at"))
        if dt is not None:
            hour_buckets[dt.hour] += 1
            dow_buckets[dt.weekday()] += 1
            day_key = dt.strftime("%Y-%m-%d")
            d = daily.setdefault(day_key, {"date": day_key, "revenue": 0.0, "orders": 0, "profit": 0.0})
            d["revenue"] += revenue
            d["orders"] += 1
            d["profit"] += profit

        # Per-customer stats
        cust_key = email or ("phone:" + phone) if (email or phone) else None
        if cust_key:
            cs = customer_stats.setdefault(cust_key, {
                "name": o.get("customer_name") or "",
                "email": email,
                "phone": phone,
                "orders": 0,
                "revenue": 0.0,
                "profit": 0.0,
            })
            cs["orders"] += 1
            cs["revenue"] += revenue
            cs["profit"] += profit
            if not cs["name"] and o.get("customer_name"):
                cs["name"] = o["customer_name"]

        # Promo usage
        promo_code = (o.get("promo_code") or "").strip()
        if promo_code:
            ps = promo_stats.setdefault(promo_code, {"code": promo_code, "uses": 0, "revenue": 0.0, "discount": 0.0})
            ps["uses"] += 1
            ps["revenue"] += revenue
            ps["discount"] += discount

        # Items breakdown
        for it in (o.get("items") or []):
            key = it.get("key") or "unknown"
            name = it.get("name") or key
            qty = int(it.get("quantity") or 0)
            line_revenue = float(it.get("subtotal") or (qty * float(it.get("price") or 0)))
            total_items += qty
            ps = product_stats.setdefault(key, {
                "key": key,
                "name": name,
                "units": 0,
                "revenue": 0.0,
            })
            ps["units"] += qty
            ps["revenue"] += line_revenue

            cat_name = product_to_category.get(key, "Uncategorised")
            cs2 = category_stats.setdefault(cat_name, {"name": cat_name, "units": 0, "revenue": 0.0})
            cs2["units"] += qty
            cs2["revenue"] += line_revenue

    # Backfill product cost / margin from current menu prices (best-effort)
    for key, ps in product_stats.items():
        prod = products.get(key) or {}
        unit_price = float(prod.get("price") or 0)
        # We don't have per-unit cost in menu; estimate margin from order-level totals proportionally.
        ps["avg_unit_price"] = round(ps["revenue"] / ps["units"], 2) if ps["units"] else 0
        # Mark whether this product still exists in the menu
        ps["in_menu"] = key in products

    # Sorted product lists
    products_by_revenue = sorted(product_stats.values(), key=lambda p: p["revenue"], reverse=True)
    products_by_units = sorted(product_stats.values(), key=lambda p: p["units"], reverse=True)
    top_products = products_by_revenue[:10]
    bottom_products_in_menu = [p for p in products_by_revenue if p["in_menu"]]
    bottom_products = list(reversed(bottom_products_in_menu))[:10]

    # Products in menu that have ZERO sales in this range (full inventory check)
    sold_keys = set(product_stats.keys())
    no_sales = []
    for k, p in products.items():
        if k in sold_keys:
            continue
        no_sales.append({
            "key": k,
            "name": p.get("name") or k,
            "price": float(p.get("price") or 0),
        })
    no_sales.sort(key=lambda x: x["name"])

    # Categories sorted
    categories_sorted = sorted(category_stats.values(), key=lambda c: c["revenue"], reverse=True)

    # Timeseries: fill gaps so chart looks continuous
    timeseries = []
    if daily:
        sorted_days = sorted(daily.keys())
        try:
            d_start = datetime.strptime(sorted_days[0], "%Y-%m-%d").date()
            d_end = datetime.strptime(sorted_days[-1], "%Y-%m-%d").date()
            from datetime import timedelta
            cur = d_start
            while cur <= d_end:
                k = cur.strftime("%Y-%m-%d")
                if k in daily:
                    timeseries.append(daily[k])
                else:
                    timeseries.append({"date": k, "revenue": 0.0, "orders": 0, "profit": 0.0})
                cur += timedelta(days=1)
        except Exception:
            timeseries = [daily[k] for k in sorted_days]

    # Top customers
    top_customers = sorted(customer_stats.values(), key=lambda c: c["revenue"], reverse=True)[:10]

    # Expenses breakdown for the same window
    exp_rows = get_expenses(start_date=start_date, end_date=end_date)
    expense_total = sum(float(e.get("amount") or 0) for e in exp_rows)
    exp_cat = {}
    for e in exp_rows:
        cat = e.get("category") or "Other"
        exp_cat[cat] = exp_cat.get(cat, 0.0) + float(e.get("amount") or 0)
    expense_breakdown = sorted(
        [{"category": k, "amount": round(v, 2)} for k, v in exp_cat.items()],
        key=lambda x: x["amount"], reverse=True
    )

    # Reviews summary in window
    review_rows = get_reviews(status="approved", limit=1000)
    if start_date or end_date:
        from datetime import datetime as _dt
        def _in_range(r):
            ts = r.get("created_at") or ""
            day = ts[:10]
            if start_date and day < start_date:
                return False
            if end_date and day > end_date:
                return False
            return True
        review_rows = [r for r in review_rows if _in_range(r)]
    rev_count = len(review_rows)
    rev_avg = (sum(int(r.get("rating") or 0) for r in review_rows) / rev_count) if rev_count else 0
    by_star = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
    for r in review_rows:
        rating = str(int(r.get("rating") or 0))
        if rating in by_star:
            by_star[rating] += 1

    # Net profit (after expenses)
    net_profit = total_profit - expense_total
    profit_margin_pct = (total_profit / total_revenue * 100.0) if total_revenue else 0.0
    aov = (total_revenue / len(active_orders)) if active_orders else 0
    unique_customers = len(customer_emails) + len(customer_phones)

    return jsonify({
        "range": {"start": start_date or "", "end": end_date or ""},
        "kpis": {
            "revenue": round(total_revenue, 2),
            "cost": round(total_cost, 2),
            "gross_profit": round(total_profit, 2),
            "profit_margin_pct": round(profit_margin_pct, 1),
            "orders": len(active_orders),
            "items_sold": total_items,
            "aov": round(aov, 2),
            "unique_customers": unique_customers,
            "discounts": round(total_discount, 2),
            "expenses": round(expense_total, 2),
            "net_profit": round(net_profit, 2),
        },
        "timeseries": timeseries,
        "products_by_revenue": products_by_revenue,
        "products_by_units": products_by_units,
        "top_products": top_products,
        "bottom_products": bottom_products,
        "no_sales_products": no_sales,
        "categories": categories_sorted,
        "statuses": status_counts,
        "payment_methods": payment_counts,
        "delivery_types": delivery_counts,
        "hour_of_day": [{"hour": h, "orders": hour_buckets[h]} for h in range(24)],
        "day_of_week": [
            {"day": i, "name": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][i], "orders": dow_buckets[i]}
            for i in range(7)
        ],
        "top_customers": top_customers,
        "expense_breakdown": expense_breakdown,
        "promos": sorted(promo_stats.values(), key=lambda p: p["revenue"], reverse=True),
        "reviews": {
            "avg_rating": round(rev_avg, 2),
            "count": rev_count,
            "by_star": by_star,
        },
    })


# ── Telegram Webhook ──────────────────────────────────────────────────────────

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    if not _bot_agent_ok:
        return "bot_agent not loaded", 500
    update = request.get_json(silent=True) or {}
    bot_agent.handle_update(update)
    return "OK", 200


@app.route("/telegram/setup")
@admin_required
def telegram_setup():
    if not _bot_agent_ok:
        return jsonify({"error": "bot_agent not loaded"}), 500
    host_url = request.host_url
    result = bot_agent.register_webhook(host_url)
    return jsonify(result)


@app.route("/telegram/status")
@admin_required
def telegram_status():
    import urllib.request as _ur
    status = {
        "bot_agent_loaded": _bot_agent_ok,
        "TELEGRAM_BOT_TOKEN": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
        "TELEGRAM_ALLOWED_IDS": os.environ.get("TELEGRAM_ALLOWED_IDS", "(not set)"),
    }
    if _bot_agent_ok and os.environ.get("TELEGRAM_BOT_TOKEN"):
        try:
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            req = _ur.Request("https://api.telegram.org/bot" + token + "/getWebhookInfo")
            resp = _ur.urlopen(req, timeout=10)
            status["webhook_info"] = json.loads(resp.read().decode())
        except Exception as e:
            status["webhook_info"] = {"error": str(e)}
    return jsonify(status)


# ── Blog ────────────────────────────────────────────────────────────────────

BLOG_DIR = os.path.join(BASE_DIR, "static", "blog")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# SSL context for Anthropic API calls — use certifi if available (fixes macOS dev cert errors)
import ssl as _ssl
try:
    import certifi as _certifi
    _SSL_CONTEXT = _ssl.create_default_context(cafile=_certifi.where())
except Exception:
    _SSL_CONTEXT = _ssl.create_default_context()


@app.route("/blog")
def blog_listing():
    page = int(request.args.get("page", 1))
    cat_slug = request.args.get("category", "")
    cat = get_blog_category_by_slug(cat_slug) if cat_slug else None
    cat_id = cat["id"] if cat else None
    posts, total = get_blog_posts(status="published", category_id=cat_id, page=page, per_page=9)
    categories = get_blog_categories()
    total_pages = (total + 8) // 9
    return render_template("blog.html",
                           posts=posts,
                           categories=categories,
                           current_category=cat,
                           page=page,
                           total_pages=total_pages,
                           total=total)


@app.route("/blog/category/<slug>")
def blog_category(slug):
    return redirect("/blog?category=" + slug)


@app.route("/blog/<slug>")
def blog_post_page(slug):
    post = get_blog_post_by_slug(slug)
    if not post or post["status"] != "published":
        return render_template("blog.html",
                               posts=[], categories=get_blog_categories(),
                               current_category=None, page=1, total_pages=1, total=0,
                               error="Post not found"), 404
    cat_ids = [c["id"] for c in post.get("categories", [])]
    related = get_related_blog_posts(post["id"], cat_ids, limit=3)
    return render_template("blog_post.html", post=post, related=related)


# ── Admin: Blog posts ───────────────────────────────────────────────────────

@app.route("/admin/blog")
@admin_required
def admin_blog():
    status_filter = request.args.get("status", "")
    cat_filter = request.args.get("category", "")
    cat = get_blog_category_by_slug(cat_filter) if cat_filter else None
    page = int(request.args.get("page", 1))
    posts, total = get_blog_posts(
        status=status_filter or None,
        category_id=cat["id"] if cat else None,
        page=page, per_page=20
    )
    categories = get_blog_categories()
    return render_template("admin/blog_posts.html",
                           posts=posts, total=total,
                           categories=categories,
                           status_filter=status_filter,
                           cat_filter=cat_filter,
                           page=page,
                           total_pages=(total + 19) // 20,
                           active_page="blog")


@app.route("/admin/blog/new")
@admin_required
def admin_blog_new():
    categories = get_blog_categories()
    return render_template("admin/blog_editor.html",
                           post=None,
                           categories=categories,
                           active_page="blog")


@app.route("/admin/blog/<int:post_id>/edit")
@admin_required
def admin_blog_edit(post_id):
    post = get_blog_post_by_id(post_id)
    if not post:
        return redirect("/admin/blog")
    categories = get_blog_categories()
    return render_template("admin/blog_editor.html",
                           post=post,
                           categories=categories,
                           active_page="blog")


@app.route("/api/admin/blog/posts", methods=["POST"])
@admin_required
def api_blog_post_create():
    data = request.get_json()
    title_en = (data.get("title_en") or "").strip()
    slug = (data.get("slug") or "").strip()
    if not title_en or not slug:
        return jsonify({"error": "Title and slug are required"}), 400
    if blog_slug_exists(slug):
        return jsonify({"error": "Slug already in use"}), 400
    cat_ids = [int(x) for x in (data.get("category_ids") or []) if str(x).isdigit()]
    post_id = create_blog_post(
        title_en=title_en,
        slug=slug,
        content_en=data.get("content_en"),
        excerpt_en=data.get("excerpt_en"),
        status=data.get("status", "draft"),
        meta_title=data.get("meta_title"),
        meta_description_en=data.get("meta_description_en"),
        focus_keyword=data.get("focus_keyword"),
        featured_image=data.get("featured_image"),
        category_ids=cat_ids
    )
    return jsonify({"success": True, "id": post_id})


@app.route("/api/admin/blog/posts/<int:post_id>", methods=["POST"])
@admin_required
def api_blog_post_update(post_id):
    post = get_blog_post_by_id(post_id)
    if not post:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    slug = (data.get("slug") or "").strip()
    if slug and blog_slug_exists(slug, exclude_id=post_id):
        return jsonify({"error": "Slug already in use"}), 400
    cat_ids = [int(x) for x in (data.get("category_ids") or []) if str(x).isdigit()]
    fields = {
        "title_en": data.get("title_en"),
        "title_ar": data.get("title_ar"),
        "title_fr": data.get("title_fr"),
        "slug": slug or post["slug"],
        "content_en": data.get("content_en"),
        "content_ar": data.get("content_ar"),
        "content_fr": data.get("content_fr"),
        "excerpt_en": data.get("excerpt_en"),
        "excerpt_ar": data.get("excerpt_ar"),
        "excerpt_fr": data.get("excerpt_fr"),
        "status": data.get("status", post["status"]),
        "meta_title": data.get("meta_title"),
        "meta_description_en": data.get("meta_description_en"),
        "meta_description_ar": data.get("meta_description_ar"),
        "meta_description_fr": data.get("meta_description_fr"),
        "focus_keyword": data.get("focus_keyword"),
        "featured_image": data.get("featured_image"),
        "image_alt": data.get("image_alt"),
        "category_ids": cat_ids,
    }
    update_blog_post(post_id, **fields)
    return jsonify({"success": True})


@app.route("/api/admin/blog/posts/<int:post_id>/delete", methods=["POST"])
@admin_required
def api_blog_post_delete(post_id):
    post = get_blog_post_by_id(post_id)
    if not post:
        return jsonify({"error": "Not found"}), 404
    # Remove featured image file if stored locally
    if post.get("featured_image"):
        img_path = os.path.join(BASE_DIR, "static", "blog", post["featured_image"])
        if os.path.exists(img_path):
            os.remove(img_path)
    delete_blog_post(post_id)
    return jsonify({"success": True})


@app.route("/api/admin/blog/posts/<int:post_id>/image", methods=["POST"])
@admin_required
def api_blog_post_image(post_id):
    os.makedirs(BLOG_DIR, exist_ok=True)
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"error": "No file"}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        return jsonify({"error": "Only JPG, PNG, WEBP allowed"}), 400

    # Build SEO-friendly filename from slug or focus keyword
    import re as _re
    import time as _time
    slug_hint = (request.form.get("slug") or "").strip().lower()
    if not slug_hint:
        post = get_blog_post_by_id(post_id)
        slug_hint = (post.get("slug") if post else "") or ""
    # Sanitise: lowercase, replace non-alphanumeric with hyphens, collapse repeats
    base = _re.sub(r"[^a-z0-9]+", "-", slug_hint.lower()).strip("-")
    if not base:
        base = "blog-" + str(post_id)
    filename = base + "-" + str(int(_time.time()))[-6:] + ext
    file.save(os.path.join(BLOG_DIR, filename))

    # Remove old image if it's being replaced
    old = (request.form.get("old_image") or "").strip()
    if old and old != filename:
        old_path = os.path.join(BLOG_DIR, old)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    return jsonify({"success": True, "filename": filename})


@app.route("/api/admin/blog/generate-seo", methods=["POST"])
@admin_required
def api_blog_generate_seo():
    """Generate excerpt + SEO metadata from a post's title and content using Claude."""
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    data = request.get_json() or {}
    title = (data.get("title_en") or "").strip()
    content = (data.get("content_en") or "").strip()
    if not title and not content:
        return jsonify({"error": "Please add a title or content first"}), 400

    user_msg = (
        "You are an SEO assistant for a bakery blog. Read the blog post below and "
        "generate SEO metadata. Return ONLY valid JSON with these exact keys "
        "(no markdown fences, no explanation):\n"
        "- excerpt: a compelling 1-2 sentence summary (~140-160 chars) for the listing page, plain text\n"
        "- meta_title: SEO title optimized for Google (50-60 chars), can include brand at end\n"
        "- slug: URL slug (lowercase, hyphens between words, 3-6 words, no special chars or stop words)\n"
        "- meta_description: 120-160 character description for Google search results — should entice clicks\n"
        "- focus_keyword: 2-4 word keyword phrase that the post targets\n"
        "- image_alt: descriptive alt text for the featured image (50-125 chars), include focus keyword naturally, describe what the image likely shows based on the post topic\n\n"
        "Title: " + title + "\n\n"
        "Content:\n" + content[:6000]
    )

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 800,
        "messages": [{"role": "user", "content": user_msg}]
    }).encode("utf-8")

    import urllib.request as _ur
    req = _ur.Request("https://api.anthropic.com/v1/messages", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", ANTHROPIC_API_KEY)
    req.add_header("anthropic-version", "2023-06-01")

    try:
        resp = _ur.urlopen(req, timeout=45, context=_SSL_CONTEXT)
        result = json.loads(resp.read().decode("utf-8"))
        text = result["content"][0]["text"].strip()
        # Strip code fences if Claude added them
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        seo = json.loads(text.strip())
        return jsonify({"success": True, "seo": seo})
    except Exception as e:
        return jsonify({"error": "Generation failed: " + str(e)}), 500


@app.route("/api/admin/blog/translate", methods=["POST"])
@admin_required
def api_blog_translate():
    """Translate English blog content into Arabic and French. Works on unsaved drafts."""
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    data = request.get_json() or {}
    title_en = (data.get("title_en") or "").strip()
    excerpt_en = (data.get("excerpt_en") or "").strip()
    content_en = (data.get("content_en") or "").strip()
    meta_en = (data.get("meta_description_en") or "").strip()

    if not title_en and not content_en:
        return jsonify({"error": "Add a title or content first."}), 400

    system_prompt = (
        "You are a professional translator specialising in food and bakery content. "
        "You translate English content into Modern Standard Arabic and French. "
        "You preserve all HTML tags, attributes, and structure exactly as given. "
        "You output only valid JSON — no markdown code fences, no commentary, no explanation."
    )

    user_msg = (
        "Translate the following blog post fields from English into Arabic and French. "
        "Return ONLY a single JSON object with these exact keys: "
        "title_ar, title_fr, excerpt_ar, excerpt_fr, content_ar, content_fr, meta_ar, meta_fr.\n\n"
        "Rules:\n"
        "- Preserve every HTML tag in content fields (<p>, <h2>, <a>, etc.) — translate only the text inside.\n"
        "- Keep proper nouns (Samarkand, Tetouan, etc.) but transliterate naturally for Arabic.\n"
        "- If a field is empty, return an empty string for both translations.\n"
        "- Do not wrap your response in code fences.\n\n"
        "===== Source content =====\n"
        "title_en: " + title_en + "\n"
        "excerpt_en: " + excerpt_en + "\n"
        "meta_description_en: " + meta_en + "\n"
        "content_en:\n" + content_en
    )

    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 8000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_msg}]
    }).encode("utf-8")

    import urllib.request as _ur
    req = _ur.Request("https://api.anthropic.com/v1/messages", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-api-key", ANTHROPIC_API_KEY)
    req.add_header("anthropic-version", "2023-06-01")

    try:
        resp = _ur.urlopen(req, timeout=90, context=_SSL_CONTEXT)
        result = json.loads(resp.read().decode("utf-8"))
        text = result["content"][0]["text"].strip()
        # Strip code fences if Claude added them
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        # Find first { and last } for safety
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
        translated = json.loads(text.strip())
        return jsonify({"success": True, "translations": translated})
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = str(e)
        return jsonify({"error": "Anthropic API error: " + err_body}), 500
    except Exception as e:
        return jsonify({"error": "Translation failed: " + str(e)}), 500


# ── Admin: Blog categories ───────────────────────────────────────────────────

@app.route("/api/admin/blog/categories", methods=["GET"])
@admin_required
def api_blog_categories_list():
    return jsonify(get_blog_categories())


@app.route("/api/admin/blog/categories", methods=["POST"])
@admin_required
def api_blog_category_create():
    data = request.get_json()
    name_en = (data.get("name_en") or "").strip()
    slug = (data.get("slug") or "").strip()
    if not name_en or not slug:
        return jsonify({"error": "Name and slug required"}), 400
    try:
        cat_id = create_blog_category(name_en, slug,
                                      data.get("name_ar"), data.get("name_fr"))
        return jsonify({"success": True, "id": cat_id})
    except Exception:
        return jsonify({"error": "Slug already exists"}), 400


@app.route("/api/admin/blog/categories/<int:cat_id>", methods=["POST"])
@admin_required
def api_blog_category_update(cat_id):
    data = request.get_json()
    name_en = (data.get("name_en") or "").strip()
    slug = (data.get("slug") or "").strip()
    if not name_en or not slug:
        return jsonify({"error": "Name and slug required"}), 400
    update_blog_category(cat_id, name_en, slug,
                         data.get("name_ar"), data.get("name_fr"))
    return jsonify({"success": True})


@app.route("/api/admin/blog/categories/<int:cat_id>/delete", methods=["POST"])
@admin_required
def api_blog_category_delete(cat_id):
    delete_blog_category(cat_id)
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(debug=True, port=5050)
