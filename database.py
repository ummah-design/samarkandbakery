"""
Samarkand Bakery — Order Database
SQLite-based storage for customer orders.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "orders.db")


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


def create_order(customer_name, customer_phone, delivery_type,
                 delivery_address, delivery_lat, delivery_lng,
                 items, total_price, total_cost=None, total_profit=None, notes=None):
    """Save a new order. items should be a list of dicts."""
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO orders (customer_name, customer_phone, delivery_type,
                          delivery_address, delivery_lat, delivery_lng,
                          items, total_price, total_cost, total_profit, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        customer_name, customer_phone, delivery_type,
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


# Initialize database on import
init_db()
