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
    from emailer import send_order_placed, send_order_confirmed, send_order_completed, send_contact_inquiry
except Exception:
    send_order_placed = None
    send_order_confirmed = None
    send_order_completed = None
    send_contact_inquiry = None

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
                      get_review_requests, get_customer_review_stats,
                      get_unrequested_completed_orders,
                      update_payment_status,
                      create_expense, get_expenses, update_expense, delete_expense)
import urllib.request
import urllib.parse
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
        pickup_time=req.get("pickup_time"),
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
                "pickup_time": req.get("pickup_time"),
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
        ok = send_contact_inquiry(name, email, message)
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


# ── Telegram Webhook ──────────────────────────────────────────────────────────

@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    if not _bot_agent_ok:
        return "bot_agent not loaded", 500
    import threading
    update = request.get_json(silent=True) or {}
    threading.Thread(target=bot_agent.handle_update, args=(update,), daemon=True).start()
    return "OK", 200


@app.route("/telegram/setup")
@admin_required
def telegram_setup():
    if not _bot_agent_ok:
        return jsonify({"error": "bot_agent not loaded"}), 500
    host_url = request.host_url
    result = bot_agent.register_webhook(host_url)
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
