"""
Samarkand Bakery — Costing Engine
Pure calculation logic, reusable by CLI, Telegram bot, or any other frontend.
"""

import json
import math
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_data():
    """Load all data files and return as a dict."""
    data = {}
    for name in ("ingredients", "recipes", "energy", "packaging"):
        path = os.path.join(DATA_DIR, f"{name}.json")
        with open(path, "r") as f:
            data[name] = json.load(f)
    return data


def get_ingredient_cost(ingredient_key, amount, ingredients):
    """Calculate cost for a given amount of an ingredient."""
    # water is free
    if ingredient_key.startswith("water"):
        return 0.0
    # Handle duplicate keys with suffix (e.g. milk_per_litre__wash)
    base_key = ingredient_key.split("__")[0]
    price = ingredients.get(base_key, 0.0)
    return price * amount


def calculate_component_batch_cost(component, ingredients):
    """Calculate the total cost of one batch of a component (dough, filling, etc.)."""
    total = 0.0
    breakdown = {}
    for ing_key, amount in component["ingredients"].items():
        cost = get_ingredient_cost(ing_key, amount, ingredients)
        breakdown[ing_key] = {"amount": amount, "cost": round(cost, 2)}
        total += cost
    return round(total, 2), breakdown


def calculate_energy_cost(recipe, quantity, energy):
    """Calculate energy cost for cooking a given quantity."""
    cooking = recipe["cooking"]
    rate = energy["rate_mad_per_kwh"]
    watts = energy["oven_watts"]

    if cooking["method"] == "oven":
        items_per_load = cooking["items_per_oven_load"]
        minutes = cooking["minutes_per_load"]
        num_loads = math.ceil(quantity / items_per_load)
        hours = (minutes / 60) * num_loads
        cost = (watts / 1000) * hours * rate
        return {
            "oven_loads": num_loads,
            "minutes_per_load": minutes,
            "total_minutes": minutes * num_loads,
            "cost": round(cost, 2)
        }
    elif cooking["method"] == "deep_fry":
        minutes = cooking["minutes_per_batch"]
        # Assume all items from one recipe batch are fried together
        batch_yield = min(comp["yields"] for comp in recipe["components"].values())
        num_batches = math.ceil(quantity / batch_yield)
        hours = (minutes / 60) * num_batches
        cost = (energy.get("stovetop_watts", watts) / 1000) * hours * rate
        return {
            "fry_batches": num_batches,
            "minutes_per_batch": minutes,
            "total_minutes": minutes * num_batches,
            "cost": round(cost, 2)
        }
    return {"cost": 0.0}


def calculate_frying_oil_cost(recipe, quantity, ingredients):
    """Calculate oil cost for deep-fried items."""
    cooking = recipe["cooking"]
    if cooking["method"] != "deep_fry":
        return {"cost": 0.0, "litres": 0.0}

    oil_per_batch = cooking.get("oil_per_batch_litres", 0)
    batch_yield = min(comp["yields"] for comp in recipe["components"].values())
    # Oil can't be fractioned — you need to fill the pan each time
    num_batches = math.ceil(quantity / batch_yield)
    total_litres = oil_per_batch * num_batches
    oil_price = ingredients.get("vegetable_oil_per_litre", 0)
    cost = total_litres * oil_price
    return {
        "litres": round(total_litres, 2),
        "batches": num_batches,
        "cost": round(cost, 2)
    }


def optimise_packaging(quantity, packaging_type, packaging_data):
    """Find the most cost-efficient packaging combination for a quantity."""
    if packaging_type == "bread_bags":
        options = packaging_data["bread_bags"]
        bag = options[0]
        num_bags = math.ceil(quantity / bag["capacity"])
        return {
            "items": [{"name": bag["name"], "count": num_bags, "cost": round(bag["price"] * num_bags, 2)}],
            "total_cost": round(bag["price"] * num_bags, 2)
        }

    # For pastry boxes, use greedy approach: largest first
    boxes = sorted(packaging_data["pastry_boxes"], key=lambda b: b["capacity"], reverse=True)
    remaining = quantity
    result_items = []
    total_cost = 0.0

    for box in boxes:
        if remaining <= 0:
            break
        count = remaining // box["capacity"]
        if count > 0:
            cost = box["price"] * count
            result_items.append({"name": box["name"], "count": count, "cost": round(cost, 2)})
            total_cost += cost
            remaining -= count * box["capacity"]

    # Handle remainder with smallest box that fits
    if remaining > 0:
        # Find smallest box that fits the remainder
        fitting_boxes = [b for b in reversed(boxes) if b["capacity"] >= remaining]
        if fitting_boxes:
            box = fitting_boxes[0]
        else:
            box = boxes[-1]  # smallest available
            # May need multiple
            count = math.ceil(remaining / box["capacity"])
            result_items.append({"name": box["name"], "count": count, "cost": round(box["price"] * count, 2)})
            total_cost += box["price"] * count
            remaining = 0

        if remaining > 0:
            result_items.append({"name": box["name"], "count": 1, "cost": round(box["price"], 2)})
            total_cost += box["price"]

    return {
        "items": result_items,
        "total_cost": round(total_cost, 2)
    }


def calculate_cost(recipe_key, quantity, data):
    """
    Main costing function.
    Returns a full breakdown for producing `quantity` of a given recipe.
    """
    recipes = data["recipes"]
    ingredients = data["ingredients"]
    energy = data["energy"]
    packaging = data["packaging"]

    if recipe_key not in recipes:
        return {"error": f"Recipe '{recipe_key}' not found. Use 'recipes' command to see available recipes."}

    recipe = recipes[recipe_key]
    result = {
        "recipe_key": recipe_key,
        "name": recipe["name"],
        "quantity": quantity,
        "selling_price": recipe["selling_price"],
        "components": {},
        "total_ingredient_cost": 0.0
    }

    # Calculate each component — proportional costing
    # Only charge for the fraction of a batch actually used.
    # Leftovers stay in the fridge and are not wasted.
    for comp_name, comp_data in recipe["components"].items():
        batch_yield = comp_data["yields"]
        batch_cost, breakdown = calculate_component_batch_cost(comp_data, ingredients)
        # Proportional: cost only for the items we're making
        fraction_used = quantity / batch_yield
        total_cost = batch_cost * fraction_used
        full_batches = math.ceil(quantity / batch_yield)
        total_produced = full_batches * batch_yield
        leftover = total_produced - quantity

        result["components"][comp_name] = {
            "batch_yield": batch_yield,
            "fraction_used": round(fraction_used, 2),
            "batch_cost": batch_cost,
            "total_cost": round(total_cost, 2),
            "leftover": leftover,
            "leftover_note": f"{leftover} can be kept in the fridge" if leftover > 0 else "",
            "breakdown": breakdown
        }
        result["total_ingredient_cost"] += total_cost

    result["total_ingredient_cost"] = round(result["total_ingredient_cost"], 2)

    # Energy cost
    result["energy"] = calculate_energy_cost(recipe, quantity, energy)

    # Frying oil cost (if applicable)
    result["frying_oil"] = calculate_frying_oil_cost(recipe, quantity, ingredients)

    # Packaging
    result["packaging"] = optimise_packaging(quantity, recipe["packaging_type"], packaging)

    # Totals
    total_cost = (
        result["total_ingredient_cost"]
        + result["energy"]["cost"]
        + result["frying_oil"]["cost"]
        + result["packaging"]["total_cost"]
    )
    result["total_cost"] = round(total_cost, 2)
    result["cost_per_unit"] = round(total_cost / quantity, 2)
    result["revenue"] = round(recipe["selling_price"] * quantity, 2)
    result["profit"] = round(result["revenue"] - total_cost, 2)
    result["profit_per_unit"] = round(result["profit"] / quantity, 2)
    result["margin_percent"] = round((result["profit"] / result["revenue"]) * 100, 1) if result["revenue"] > 0 else 0

    return result


def calculate_order(order_items, data):
    """
    Calculate costs for a mixed order.
    order_items: list of {"recipe_key": str, "quantity": int}
    Returns combined breakdown.
    """
    results = []
    total_cost = 0.0
    total_revenue = 0.0
    total_packaging = 0.0

    for item in order_items:
        r = calculate_cost(item["recipe_key"], item["quantity"], data)
        if "error" in r:
            return r
        results.append(r)
        total_cost += r["total_cost"]
        total_revenue += r["revenue"]
        total_packaging += r["packaging"]["total_cost"]

    total_profit = total_revenue - total_cost
    return {
        "items": results,
        "total_cost": round(total_cost, 2),
        "total_revenue": round(total_revenue, 2),
        "total_profit": round(total_profit, 2),
        "total_packaging": round(total_packaging, 2),
        "margin_percent": round((total_profit / total_revenue) * 100, 1) if total_revenue > 0 else 0
    }
