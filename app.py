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
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

from engine import load_data, calculate_cost, calculate_order
try:
    from emailer import send_order_placed, send_order_confirmed, send_order_completed
except Exception:
    send_order_placed = None
    send_order_confirmed = None
    send_order_completed = None
from database import (create_order, get_orders, get_order, update_order_status,
                      get_customers, get_customer_orders,
                      create_review, get_reviews, update_review_status, add_review_reply,
                      get_product_review_summary, is_known_customer, get_customer_review_count,
                      create_promo, validate_promo, use_promo, get_promos, toggle_promo,
                      get_promo_usage,
                      record_review_request, record_review_reminder,
                      get_review_requests, get_customer_review_stats,
                      get_unrequested_completed_orders,
                      update_payment_status)
import urllib.request
import urllib.parse
import base64

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "samarkand-bakery-secret-2026-change-me")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

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


def paypal_create_order(amount, currency="MAD"):
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


def get_lang():
    """Get current language from query param, session, or default to 'en'."""
    lang = request.args.get("lang")
    if lang in ("en", "fr", "ar"):
        session["lang"] = lang
        return lang
    return session.get("lang", "en")


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
    return render_template("order.html", menu=menu, t=t, lang=lang, paypal_client_id=PAYPAL_CLIENT_ID)


@app.route("/order")
def order_page():
    menu = load_menu()
    t = get_t()
    lang = get_lang()
    return render_template("order.html", menu=menu, t=t, lang=lang, paypal_client_id=PAYPAL_CLIENT_ID)


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
    return render_template("product.html", item=item, product_key=product_key, allergen_notice=allergen_notice, t=t, lang=lang)


# ── Public API ──

@app.route("/api/menu")
def api_menu():
    menu = load_menu()
    return jsonify(menu)


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
    promo_code = req.get("promo_code", "").strip().upper() or None
    discount_amt = 0
    if promo_code:
        promo_result = validate_promo(promo_code, total_price)
        if promo_result.get("valid"):
            discount_amt = promo_result["discount_amount"]
            total_price -= discount_amt
            use_promo(promo_code)

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
        notes=req.get("notes"),
        payment_method=payment_method,
        payment_status=payment_status,
        paypal_order_id=paypal_oid
    )

    # Send order confirmation email
    if send_order_placed:
        try:
            send_order_placed({
                "id": order_id,
                "customer_name": req["customer_name"],
                "customer_email": req.get("customer_email", ""),
                "items": order_items,
                "total_price": round(total_price, 2),
                "delivery_type": req.get("delivery_type", "pickup"),
                "delivery_address": req.get("delivery_address"),
                "preferred_date": req.get("preferred_date"),
                "promo_code": promo_code,
                "discount_amount": round(discount_amt, 2)
            })
        except Exception:
            pass

    return jsonify({
        "success": True,
        "order_id": order_id,
        "total_price": round(total_price, 2),
        "payment_method": payment_method,
        "message": f"Order #{order_id} received! We will contact you shortly."
    })


# ── PayPal API ──

@app.route("/api/paypal/create", methods=["POST"])
def api_paypal_create():
    """Create a PayPal order for the given amount."""
    req = request.json
    amount = req.get("amount", 0)
    if amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400
    try:
        result = paypal_create_order(amount)
        return jsonify({"id": result["id"]})
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
    data = load_data()
    recipes = {k: v["name"] for k, v in data["recipes"].items()}
    menu = load_menu()
    return render_template("index.html", recipes=recipes, menu=menu)


@app.route("/admin/orders")
@admin_required
def admin_orders_page():
    return render_template("admin_orders.html")


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
            "selling_price": recipe["selling_price"],
            "cooking_method": recipe["cooking"]["method"],
            "image": menu_item.get("image", ""),
            "description": menu_item.get("description", ""),
            "description_long": menu_item.get("description_long", ""),
            "meta_title": menu_item.get("meta_title", ""),
            "meta_description": menu_item.get("meta_description", "")
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
            menu["products"][product_key]["price"] = float(price)
        except ValueError:
            pass
    if meta_title is not None:
        menu["products"][product_key]["meta_title"] = meta_title
    if meta_description is not None:
        menu["products"][product_key]["meta_description"] = meta_description

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
            # Remove old image if different filename
            old_image = menu["products"][product_key].get("image", "")
            if old_image and old_image != filename:
                old_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "products", old_image)
                if os.path.exists(old_path):
                    os.remove(old_path)
            menu["products"][product_key]["image"] = filename

    # Save menu.json
    menu_path = os.path.join(DATA_DIR, "menu.json")
    with open(menu_path, "w", encoding="utf-8") as f:
        json.dump(menu, f, indent=4, ensure_ascii=False)

    return jsonify({"success": True, "key": new_key, "image": menu["products"][new_key].get("image", "")})


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
    orders = get_orders(status=status)
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


# ── Public Reviews API ──

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


if __name__ == "__main__":
    app.run(debug=True, port=5050)
