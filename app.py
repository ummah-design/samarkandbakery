#!/usr/bin/env python3
"""
Samarkand Bakery — Web App
Run: python3 app.py
- Costing tool: http://localhost:5050
- Ordering page: http://localhost:5050/order
- Admin orders: http://localhost:5050/admin/orders
"""

import json
import os
from flask import Flask, render_template, request, jsonify
from engine import load_data, calculate_cost, calculate_order
from database import create_order, get_orders, get_order, update_order_status

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_menu():
    """Load menu data for the ordering page."""
    with open(os.path.join(DATA_DIR, "menu.json"), "r") as f:
        return json.load(f)


# ── Costing Tool ──

@app.route("/")
def index():
    """Public-facing ordering page — this is what customers see."""
    menu = load_menu()
    return render_template("order.html", menu=menu)


@app.route("/admin")
def admin_dashboard():
    """Admin dashboard — only accessible via /admin URL."""
    data = load_data()
    recipes = {k: v["name"] for k, v in data["recipes"].items()}
    menu = load_menu()
    return render_template("index.html", recipes=recipes, menu=menu)


@app.route("/api/recipes")
def api_recipes():
    data = load_data()
    menu = load_menu()
    result = []
    for key, recipe in data["recipes"].items():
        menu_item = menu["products"].get(key, {})
        result.append({
            "key": key,
            "name": recipe["name"],
            "selling_price": recipe["selling_price"],
            "cooking_method": recipe["cooking"]["method"],
            "image": menu_item.get("image", ""),
            "description": menu_item.get("description", "")
        })
    return jsonify(result)


@app.route("/api/prices")
def api_prices():
    data = load_data()
    prices = {k: v for k, v in data["ingredients"].items() if not k.startswith("_")}
    return jsonify(prices)


@app.route("/api/cost")
def api_cost():
    data = load_data()
    recipe_key = request.args.get("recipe")
    quantity = int(request.args.get("quantity", 1))
    result = calculate_cost(recipe_key, quantity, data)
    return jsonify(result)


@app.route("/api/order", methods=["POST"])
def api_order():
    data = load_data()
    order_items = request.json.get("items", [])
    result = calculate_order(order_items, data)
    return jsonify(result)


# ── Product Detail Page ──

@app.route("/product/<product_key>")
def product_page(product_key):
    menu = load_menu()
    item = menu["products"].get(product_key)
    if not item:
        return "Product not found", 404
    return render_template("product.html", item=item, product_key=product_key, allergen_notice=menu.get("allergen_notice", ""))


# ── Public Ordering Page ──

@app.route("/order")
def order_page():
    menu = load_menu()
    return render_template("order.html", menu=menu)


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

    # Calculate total price
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

    # Calculate cost for profit tracking
    data = load_data()
    cost_items = [{"recipe_key": i["key"], "quantity": i["quantity"]} for i in items]
    cost_result = calculate_order(cost_items, data)
    total_cost = cost_result.get("total_cost", 0)
    total_profit = cost_result.get("total_profit", 0)

    # Save order
    order_id = create_order(
        customer_name=req["customer_name"],
        customer_phone=req["customer_phone"],
        delivery_type=req.get("delivery_type", "pickup"),
        delivery_address=req.get("delivery_address"),
        delivery_lat=req.get("delivery_lat"),
        delivery_lng=req.get("delivery_lng"),
        items=order_items,
        total_price=round(total_price, 2),
        total_cost=round(total_cost, 2),
        total_profit=round(total_profit, 2),
        notes=req.get("notes")
    )

    return jsonify({
        "success": True,
        "order_id": order_id,
        "total_price": round(total_price, 2),
        "message": f"Order #{order_id} received! We will contact you shortly."
    })


# ── Admin Orders Page ──

@app.route("/admin/orders")
def admin_orders_page():
    return render_template("admin_orders.html")


@app.route("/api/admin/orders")
def api_admin_orders():
    status = request.args.get("status")
    orders = get_orders(status=status)
    return jsonify(orders)


@app.route("/api/admin/orders/<int:order_id>/status", methods=["POST"])
def api_update_order_status(order_id):
    new_status = request.json.get("status")
    if new_status not in ("pending", "confirmed", "completed", "cancelled"):
        return jsonify({"error": "Invalid status"}), 400
    update_order_status(order_id, new_status)
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(debug=True, port=5050)
