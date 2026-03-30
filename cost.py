#!/usr/bin/env python3
"""
Samarkand Bakery — CLI Costing Tool
Usage: python3 cost.py [command]
"""

import click
import re
from engine import load_data, calculate_cost, calculate_order


def format_mad(value):
    """Format a number as MAD currency."""
    return f"{value:,.2f} MAD"


@click.group()
def cli():
    """Samarkand Bakery — Product Costing Tool"""
    pass


@cli.command()
def recipes():
    """List all available recipes."""
    data = load_data()
    click.echo("")
    click.echo("=" * 50)
    click.echo("  SAMARKAND BAKERY — Available Products")
    click.echo("=" * 50)
    click.echo("")
    click.echo(f"  {'Key':<25} {'Name':<25} {'Price':>8}")
    click.echo(f"  {'-'*25} {'-'*25} {'-'*8}")
    for key, recipe in data["recipes"].items():
        click.echo(f"  {key:<25} {recipe['name']:<25} {format_mad(recipe['selling_price']):>8}")
    click.echo("")


@cli.command()
def prices():
    """Show current ingredient prices."""
    data = load_data()
    click.echo("")
    click.echo("=" * 50)
    click.echo("  SAMARKAND BAKERY — Ingredient Prices")
    click.echo("=" * 50)
    click.echo("")
    for key, price in data["ingredients"].items():
        if key.startswith("_"):
            continue
        label = key.replace("_per_kg", " /kg").replace("_per_litre", " /L").replace("_each", " each").replace("_per_pot", " /pot").replace("_per_tub", " /tub").replace("_", " ").title()
        click.echo(f"  {label:<35} {format_mad(price):>12}")
    click.echo("")


@cli.command()
@click.argument("recipe_key")
@click.option("-n", "--quantity", default=1, help="Number of items to cost")
def cost(recipe_key, quantity):
    """Calculate cost for a product. Usage: cost <recipe_key> -n <quantity>"""
    data = load_data()
    result = calculate_cost(recipe_key, quantity, data)

    if "error" in result:
        click.echo(f"\n  Error: {result['error']}\n")
        return

    click.echo("")
    click.echo("=" * 55)
    click.echo(f"  SAMARKAND BAKERY — {result['name']} Costing")
    click.echo("=" * 55)
    click.echo("")
    click.echo(f"  Quantity requested:  {result['quantity']}")
    click.echo("")

    # Components
    for comp_name, comp in result["components"].items():
        click.echo(f"  {comp_name.upper()}")
        click.echo(f"    Batch yields:      {comp['batch_yield']} items  (batch cost: {format_mad(comp['batch_cost'])})")
        click.echo(f"    Used for order:    {comp['fraction_used']} of a batch")
        if comp['leftover'] > 0:
            click.echo(f"    Leftover:          {comp['leftover']} (kept in fridge)")
        click.echo(f"    Cost charged:      {format_mad(comp['total_cost'])}")
        click.echo("")

    # Energy
    energy = result["energy"]
    if "oven_loads" in energy:
        click.echo(f"  BAKING")
        click.echo(f"    Oven loads:         {energy['oven_loads']}  ({energy['minutes_per_load']} min each = {energy['total_minutes']} min total)")
        click.echo(f"    Energy cost:        {format_mad(energy['cost'])}")
    elif "fry_batches" in energy:
        click.echo(f"  FRYING")
        click.echo(f"    Fry batches:        {energy['fry_batches']}  ({energy['minutes_per_batch']} min each = {energy['total_minutes']} min total)")
        click.echo(f"    Energy cost:        {format_mad(energy['cost'])}")
    click.echo("")

    # Frying oil
    if result["frying_oil"]["cost"] > 0:
        click.echo(f"  FRYING OIL")
        click.echo(f"    Oil used:           {result['frying_oil']['litres']} litres")
        click.echo(f"    Oil cost:           {format_mad(result['frying_oil']['cost'])}")
        click.echo("")

    # Packaging
    pkg = result["packaging"]
    click.echo(f"  PACKAGING")
    for item in pkg["items"]:
        click.echo(f"    {item['name']:20} x{item['count']}  = {format_mad(item['cost'])}")
    click.echo(f"    Total packaging:   {format_mad(pkg['total_cost'])}")
    click.echo("")

    # Summary
    click.echo(f"  {'─' * 50}")
    click.echo(f"  TOTAL COST:          {format_mad(result['total_cost'])}")
    click.echo(f"  COST PER UNIT:       {format_mad(result['cost_per_unit'])}")
    click.echo(f"  SELLING PRICE:       {format_mad(result['selling_price'])}")
    click.echo(f"  PROFIT PER UNIT:     {format_mad(result['profit_per_unit'])}")
    click.echo(f"  MARGIN:              {result['margin_percent']}%")
    click.echo(f"  REVENUE ({result['quantity']} pcs):    {format_mad(result['revenue'])}")
    click.echo(f"  TOTAL PROFIT:        {format_mad(result['profit'])}")
    click.echo("=" * 55)
    click.echo("")


@cli.command()
@click.argument("order_string")
def order(order_string):
    """
    Calculate cost for a mixed order.
    Usage: order "2 meat_samsa, 3 uzbek_bread, 1 pide_minced_beef"
    """
    data = load_data()

    # Parse order string: "2 meat_samsa, 3 uzbek_bread"
    order_items = []
    parts = [p.strip() for p in order_string.split(",")]
    for part in parts:
        match = re.match(r"(\d+)\s+(\w+)", part)
        if not match:
            click.echo(f"\n  Error: Could not parse '{part}'. Format: '2 meat_samsa'\n")
            return
        qty = int(match.group(1))
        key = match.group(2)
        order_items.append({"recipe_key": key, "quantity": qty})

    result = calculate_order(order_items, data)

    if "error" in result:
        click.echo(f"\n  Error: {result['error']}\n")
        return

    click.echo("")
    click.echo("=" * 60)
    click.echo("  SAMARKAND BAKERY — Order Quote")
    click.echo("=" * 60)
    click.echo("")
    click.echo(f"  {'Item':<25} {'Qty':>4} {'Cost':>10} {'Revenue':>10} {'Profit':>10}")
    click.echo(f"  {'-'*25} {'-'*4} {'-'*10} {'-'*10} {'-'*10}")

    for item in result["items"]:
        click.echo(
            f"  {item['name']:<25} {item['quantity']:>4} "
            f"{format_mad(item['total_cost']):>10} "
            f"{format_mad(item['revenue']):>10} "
            f"{format_mad(item['profit']):>10}"
        )

    click.echo(f"  {'-'*25} {'-'*4} {'-'*10} {'-'*10} {'-'*10}")
    click.echo(
        f"  {'TOTAL':<25} {'':>4} "
        f"{format_mad(result['total_cost']):>10} "
        f"{format_mad(result['total_revenue']):>10} "
        f"{format_mad(result['total_profit']):>10}"
    )
    click.echo("")
    click.echo(f"  Packaging total:     {format_mad(result['total_packaging'])}")
    click.echo(f"  Profit margin:       {result['margin_percent']}%")
    click.echo("=" * 60)
    click.echo("")


if __name__ == "__main__":
    cli()
