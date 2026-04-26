"""
Samarkand Bakery — Email Notification System
Sends transactional emails for order lifecycle events.

Templates are stored per (type, language) in the SQLite `email_templates`
table and rendered via simple {{placeholder}} substitution. Language is
resolved per call: explicit > customer_lang on order > primary_language site
config > 'en'. The branded header/footer wrapper is applied automatically.
"""

import smtplib
import os
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from database import get_email_template_with_fallback, get_primary_language
except Exception:
    get_email_template_with_fallback = None
    get_primary_language = None

try:
    from email_defaults import get_default_title, get_labels, DEFAULT_EMAIL_TEMPLATES
except Exception:
    DEFAULT_EMAIL_TEMPLATES = {}
    def get_default_title(template_type, language):
        return ""
    def get_labels(language):
        return {}


# SMTP Configuration
SMTP_HOST = os.environ.get("SMTP_HOST", "mail.samarkandbakery.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "orders@samarkandbakery.com")
SMTP_PASS = os.environ.get("SMTP_PASS", "Morocco-2026")
FROM_NAME = "Samarkand Turkic Bakery"
FROM_EMAIL = SMTP_USER
SITE_URL = "https://samarkandbakery.com"

# Admin notification recipients
ADMIN_EMAIL = "azizadadaami@gmail.com"
ADMIN_CC = "ummah.design@gmail.com"


# ── Core helpers ──

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _render(template_str, vars_dict):
    """Replace {{placeholder}} tokens with values from vars_dict.
    Unknown placeholders are left blank rather than raising."""
    if not template_str:
        return ""
    def repl(match):
        key = match.group(1)
        val = vars_dict.get(key, "")
        return "" if val is None else str(val)
    return _PLACEHOLDER_RE.sub(repl, template_str)


def _resolve_language(explicit_lang=None, order=None):
    """Pick the best language for an email."""
    if explicit_lang in ("en", "fr", "ar"):
        return explicit_lang
    if order:
        ol = order.get("customer_lang")
        if ol in ("en", "fr", "ar"):
            return ol
    if get_primary_language:
        try:
            return get_primary_language()
        except Exception:
            pass
    return "en"


def _load_template(template_type, language):
    """Get the (subject, body_html) for a (type, language) pair.
    Falls back through DB lookup; if DB unavailable, falls back to defaults."""
    if get_email_template_with_fallback:
        try:
            tpl = get_email_template_with_fallback(template_type, language)
            if tpl:
                return tpl["subject"], tpl["body_html"]
        except Exception:
            pass
    # Final fallback: hardcoded defaults
    fallback = DEFAULT_EMAIL_TEMPLATES.get(template_type, {})
    tpl = fallback.get(language) or fallback.get("en") or {}
    return tpl.get("subject", ""), tpl.get("body_html", "")


def _send_email(to_email, subject, html_body, cc=None):
    """Send an HTML email via SMTP SSL."""
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = FROM_NAME + " <" + FROM_EMAIL + ">"
        msg["To"] = to_email
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        recipients = [to_email]
        if cc:
            recipients.append(cc)

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, recipients, msg.as_string())
        return True
    except Exception as e:
        print("Email error: " + str(e))
        return False


def _send_admin_notification(subject, html_body):
    return _send_email(ADMIN_EMAIL, subject, html_body, cc=ADMIN_CC)


def _email_wrapper(content_html, title="", language="en"):
    """Wrap content in the branded email shell. RTL-aware for Arabic."""
    direction = "rtl" if language == "ar" else "ltr"
    title_block = ""
    if title:
        title_block = (
            '<h2 style="font-family:Georgia,serif;font-size:1.3em;'
            'color:#1e2a4a;margin:0 0 16px;">' + title + '</h2>'
        )
    return (
        '<!DOCTYPE html>\n'
        '<html lang="' + language + '" dir="' + direction + '">\n'
        '<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>\n'
        '<body style="margin:0;padding:0;background:#f5f0eb;'
        'font-family:\'Segoe UI\',Tahoma,Geneva,Verdana,sans-serif;">\n'
        '<div style="max-width:560px;margin:0 auto;padding:24px 16px;">\n'
        '    <div style="text-align:center;padding:24px 0 20px;">\n'
        '        <img src="' + SITE_URL + '/static/profile-pic.png" '
        'alt="Samarkand Bakery" style="width:64px;height:64px;border-radius:50%;">\n'
        '        <h1 style="font-family:Georgia,serif;font-size:1.4em;'
        'color:#1e2a4a;margin:12px 0 4px;">Samarkand Turkic Bakery</h1>\n'
        '        <p style="color:#9a9aad;font-size:0.85em;margin:0;">'
        'Fresh Uzbek &amp; Turkish Baked Goods</p>\n'
        '    </div>\n'
        '    <div style="background:#ffffff;border-radius:12px;padding:28px;'
        'box-shadow:0 2px 8px rgba(30,42,74,0.06);">\n'
        '        ' + title_block + '\n'
        '        ' + content_html + '\n'
        '    </div>\n'
        '    <div style="text-align:center;padding:24px 0;color:#9a9aad;font-size:0.78em;">\n'
        '        <p>Samarkand Turkic Bakery — Tetouan, Morocco</p>\n'
        '        <p><a href="tel:+212680342679" style="color:#1e2a4a;text-decoration:none;">'
        '+212 680 342 679</a> &bull; '
        '<a href="https://www.instagram.com/SamarkandBakery" '
        'style="color:#1e2a4a;text-decoration:none;">@SamarkandBakery</a></p>\n'
        '    </div>\n'
        '</div>\n'
        '</body>\n'
        '</html>'
    )


# ── Block builders (compose dynamic HTML fragments from order data) ──

def _items_table_html(items, labels):
    """Render order items as table rows."""
    rows = ""
    qty_prefix = labels.get("qty_prefix", "x")
    currency = labels.get("currency", "MAD")
    for item in items:
        rows += (
            '<tr style="border-bottom:1px solid #f0ebe3;">'
            '<td style="padding:10px 0;color:#444;">' + str(item.get("name", "")) + '</td>'
            '<td style="padding:10px 8px;text-align:center;color:#888;">' +
            qty_prefix + str(item.get("quantity", "")) + '</td>'
            '<td style="padding:10px 0;text-align:right;font-weight:600;color:#1e2a4a;">' +
            ("%.2f" % float(item.get("subtotal", 0))) + ' ' + currency + '</td>'
            '</tr>'
        )
    return rows


def _delivery_info_text(order, labels):
    if order.get("delivery_type") == "delivery":
        info = labels.get("delivery_to_location", "Delivery to your location")
        if order.get("delivery_address"):
            info += " (" + str(order["delivery_address"]) + ")"
        return info
    return labels.get("delivery_pickup", "Pickup from Wilaya Centre")


def _preferred_date_block(order, labels):
    if not order.get("preferred_date"):
        return ""
    label = labels.get("preferred_date_label", "Preferred date")
    return ('<br>' + label + ': <strong style="color:#b8860b;">' +
            str(order["preferred_date"]) + '</strong>')


def _discount_block_html(order, labels):
    disc_amt = order.get("discount_amount", 0) or 0
    if disc_amt <= 0:
        return ""
    currency = labels.get("currency", "MAD")
    if order.get("promo_code"):
        label = labels.get("discount_with_code", "Discount ({code})").format(code=order["promo_code"])
    else:
        label = labels.get("discount_generic", "Order discount")
    return (
        '<tr style="border-bottom:1px solid #f0ebe3;">'
        '<td colspan="2" style="padding:10px 0;color:#2d7a4f;font-weight:600;">' + label + '</td>'
        '<td style="padding:10px 0;text-align:right;color:#2d7a4f;font-weight:600;">-' +
        ("%.2f" % float(disc_amt)) + ' ' + currency + '</td>'
        '</tr>'
    )


def _loyalty_block_html(loyalty_earned, loyalty_redeemed_pts, loyalty_redeemed_mad, labels):
    if loyalty_earned <= 0 and loyalty_redeemed_pts <= 0:
        return ""
    currency = labels.get("currency", "MAD")
    heading = labels.get("loyalty_heading", "Loyalty Points")
    lines = ""
    if loyalty_redeemed_pts > 0:
        line1 = labels.get("loyalty_redeemed", "{pts} points redeemed").format(pts=loyalty_redeemed_pts)
        line2 = labels.get("loyalty_redeemed_off", "{mad} MAD off this order").format(
            mad=("%.2f" % float(loyalty_redeemed_mad))
        )
        lines += ('<p style="margin:4px 0;font-size:0.9em;color:#c0392b;">&#9733; '
                  '<strong>' + line1 + '</strong> &mdash; ' + line2 + '</p>')
    if loyalty_earned > 0:
        line1 = labels.get("loyalty_earned", "+{pts} points earned").format(pts=loyalty_earned)
        line2 = labels.get("loyalty_earned_on", "on this order")
        lines += ('<p style="margin:4px 0;font-size:0.9em;color:#2d7a4f;">&#9733; '
                  '<strong>' + line1 + '</strong> ' + line2 + '</p>')
    return (
        '<div style="margin-top:16px;padding:14px 16px;background:#faf6f1;'
        'border-radius:8px;border-left:3px solid #b8860b;">'
        '<p style="margin:0 0 4px;font-size:0.82em;color:#9a9aad;'
        'text-transform:uppercase;letter-spacing:0.05em;font-weight:600;">' + heading + '</p>'
        + lines + '</div>'
    )


def _review_links_html(items):
    """Build row of CTA buttons linking to review forms for each unique product."""
    seen = set()
    parts = []
    for item in items:
        key = item.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        name = item.get("name", key)
        parts.append(
            '<a href="' + SITE_URL + '/product/' + str(key) + '#review-form" '
            'style="display:inline-block;margin:4px 4px 4px 0;padding:8px 16px;'
            'background:#1e2a4a;color:#fff;border-radius:6px;text-decoration:none;'
            'font-size:0.85em;font-weight:600;">' + str(name) + '</a>'
        )
    return " ".join(parts)


# ── Public send_* functions ──

def send_contact_inquiry(name, email, message, language=None):
    """Send contact form inquiry to admin."""
    lang = _resolve_language(language)
    labels = get_labels(lang)
    subject_tpl, body_tpl = _load_template("contact_inquiry", lang)
    vars_dict = {
        "name": name,
        "email": email,
        "message": message,
        "title": get_default_title("contact_inquiry", lang),
    }
    subject = _render(subject_tpl, vars_dict)
    body_html = _render(body_tpl, vars_dict)
    title = vars_dict["title"]
    html = _email_wrapper(body_html, title=title, language=lang)
    return _send_admin_notification(subject, html)


def send_order_placed(order, loyalty_earned=0, loyalty_redeemed_pts=0, loyalty_redeemed_mad=0.0,
                      language=None):
    """Email sent when a customer places an order. Also notifies admin."""
    if not order.get("customer_email"):
        return False
    lang = _resolve_language(language, order)
    labels = get_labels(lang)

    items_html = _items_table_html(order.get("items", []), labels)
    discount_block = _discount_block_html(order, labels)
    delivery_info = _delivery_info_text(order, labels)
    preferred_date_block = _preferred_date_block(order, labels)
    loyalty_block = _loyalty_block_html(
        loyalty_earned, loyalty_redeemed_pts, loyalty_redeemed_mad, labels
    )

    subject_tpl, body_tpl = _load_template("order_placed", lang)
    vars_dict = {
        "customer_name": order.get("customer_name", ""),
        "order_id": order.get("id", ""),
        "total_price": "%.2f" % float(order.get("total_price", 0)),
        "items_table": items_html,
        "discount_block": discount_block,
        "delivery_info": delivery_info,
        "preferred_date_block": preferred_date_block,
        "loyalty_block": loyalty_block,
        "title": get_default_title("order_placed", lang),
    }
    subject = _render(subject_tpl, vars_dict)
    body_html = _render(body_tpl, vars_dict)
    html = _email_wrapper(body_html, title=vars_dict["title"], language=lang)

    _send_email(order["customer_email"], subject, html)
    # Admin notification — render in admin's language (site primary)
    admin_lang = get_primary_language() if get_primary_language else "en"
    if admin_lang != lang:
        admin_subject_tpl, admin_body_tpl = _load_template("order_placed", admin_lang)
        admin_labels = get_labels(admin_lang)
        admin_vars = dict(vars_dict)
        admin_vars["items_table"] = _items_table_html(order.get("items", []), admin_labels)
        admin_vars["discount_block"] = _discount_block_html(order, admin_labels)
        admin_vars["delivery_info"] = _delivery_info_text(order, admin_labels)
        admin_vars["preferred_date_block"] = _preferred_date_block(order, admin_labels)
        admin_vars["loyalty_block"] = _loyalty_block_html(
            loyalty_earned, loyalty_redeemed_pts, loyalty_redeemed_mad, admin_labels
        )
        admin_vars["title"] = get_default_title("order_placed", admin_lang)
        admin_subject = _render(admin_subject_tpl, admin_vars)
        admin_body = _render(admin_body_tpl, admin_vars)
        admin_html = _email_wrapper(admin_body, title=admin_vars["title"], language=admin_lang)
    else:
        admin_subject = subject
        admin_html = html
    admin_subject = "New Order #" + str(order.get("id", "")) + " — " + str(order.get("customer_name", ""))
    _send_admin_notification(admin_subject, admin_html)
    return True


def send_order_confirmed(order, language=None):
    """Email sent when admin confirms an order."""
    if not order.get("customer_email"):
        return False
    lang = _resolve_language(language, order)
    labels = get_labels(lang)

    items_html = _items_table_html(order.get("items", []), labels)
    preferred_date_block = ""
    if order.get("preferred_date"):
        label = labels.get("preferred_date_label", "Preferred date")
        preferred_date_block = (
            '<p style="margin:6px 0 0;font-size:0.88em;color:#444;">' + label +
            ': <strong style="color:#b8860b;">' + str(order["preferred_date"]) + '</strong></p>'
        )

    subject_tpl, body_tpl = _load_template("order_confirmed", lang)
    vars_dict = {
        "customer_name": order.get("customer_name", ""),
        "order_id": order.get("id", ""),
        "total_price": "%.2f" % float(order.get("total_price", 0)),
        "items_table": items_html,
        "preferred_date_block": preferred_date_block,
        "title": get_default_title("order_confirmed", lang),
    }
    subject = _render(subject_tpl, vars_dict)
    body_html = _render(body_tpl, vars_dict)
    html = _email_wrapper(body_html, title=vars_dict["title"], language=lang)
    return _send_email(order["customer_email"], subject, html)


def send_order_completed(order, language=None):
    """Email sent when an order is marked completed (also serves as review request)."""
    if not order.get("customer_email"):
        return False
    lang = _resolve_language(language, order)

    review_links = _review_links_html(order.get("items", []))
    subject_tpl, body_tpl = _load_template("order_completed", lang)
    vars_dict = {
        "customer_name": order.get("customer_name", ""),
        "order_id": order.get("id", ""),
        "total_price": "%.2f" % float(order.get("total_price", 0)),
        "review_links_block": review_links,
        "title": get_default_title("order_completed", lang),
    }
    subject = _render(subject_tpl, vars_dict)
    body_html = _render(body_tpl, vars_dict)
    html = _email_wrapper(body_html, title=vars_dict["title"], language=lang)
    return _send_email(order["customer_email"], subject, html)


def send_loyalty_code(to_email, code, customer_name=None, ttl_minutes=15, language=None):
    """Send a 6-digit verification code so the customer can redeem loyalty points."""
    if not to_email:
        return False
    lang = _resolve_language(language)
    labels = get_labels(lang)
    if customer_name:
        greeting = labels.get("greeting_with_name", "Hi {name},").format(name=customer_name)
    else:
        greeting = labels.get("greeting_no_name", "Hi,")

    subject_tpl, body_tpl = _load_template("loyalty_code", lang)
    vars_dict = {
        "customer_name": customer_name or "",
        "greeting": greeting,
        "code": code,
        "ttl_minutes": ttl_minutes,
        "title": get_default_title("loyalty_code", lang),
    }
    subject = _render(subject_tpl, vars_dict)
    body_html = _render(body_tpl, vars_dict)
    html = _email_wrapper(body_html, title=vars_dict["title"], language=lang)
    return _send_email(to_email, subject, html)


# ── Preview helper for the admin editor ──

def render_preview(template_type, language, sample_overrides=None):
    """Render a template using sample data so admin can preview the result.
    Returns dict with subject and full html (wrapped)."""
    sample_orders = {
        "order_placed": {
            "id": 1234,
            "customer_name": "Sample Customer",
            "customer_email": "sample@example.com",
            "items": [
                {"key": "samsa", "name": "Samsa (Beef)", "quantity": 4, "subtotal": 80.0},
                {"key": "manti", "name": "Manti", "quantity": 2, "subtotal": 60.0},
            ],
            "total_price": 132.0,
            "delivery_type": "delivery",
            "delivery_address": "Tetouan, Wilaya",
            "preferred_date": "2026-05-02",
            "promo_code": "WELCOME10",
            "discount_amount": 8.0,
        },
        "order_confirmed": {
            "id": 1234,
            "customer_name": "Sample Customer",
            "customer_email": "sample@example.com",
            "items": [
                {"key": "samsa", "name": "Samsa (Beef)", "quantity": 4, "subtotal": 80.0},
            ],
            "total_price": 80.0,
            "preferred_date": "2026-05-02",
        },
        "order_completed": {
            "id": 1234,
            "customer_name": "Sample Customer",
            "customer_email": "sample@example.com",
            "items": [
                {"key": "samsa", "name": "Samsa (Beef)", "quantity": 4, "subtotal": 80.0},
                {"key": "manti", "name": "Manti", "quantity": 2, "subtotal": 60.0},
            ],
            "total_price": 140.0,
        },
    }

    # Capture send_email calls instead of really sending
    captured = {}
    real_send = globals().get("_send_email")
    real_admin = globals().get("_send_admin_notification")
    def fake_send(to, subject, html, cc=None):
        captured["subject"] = subject
        captured["html"] = html
        return True
    def fake_admin(subject, html):
        captured.setdefault("subject", subject)
        captured.setdefault("html", html)
        return True
    globals()["_send_email"] = fake_send
    globals()["_send_admin_notification"] = fake_admin
    try:
        if template_type == "order_placed":
            send_order_placed(sample_orders["order_placed"],
                              loyalty_earned=7, loyalty_redeemed_pts=20,
                              loyalty_redeemed_mad=10.0, language=language)
        elif template_type == "order_confirmed":
            send_order_confirmed(sample_orders["order_confirmed"], language=language)
        elif template_type == "order_completed":
            send_order_completed(sample_orders["order_completed"], language=language)
        elif template_type == "contact_inquiry":
            send_contact_inquiry("Sample Visitor", "visitor@example.com",
                                 "I would like to ask about gluten-free options.",
                                 language=language)
        elif template_type == "loyalty_code":
            send_loyalty_code("customer@example.com", "482917",
                              customer_name="Sample Customer", ttl_minutes=15,
                              language=language)
    finally:
        globals()["_send_email"] = real_send
        globals()["_send_admin_notification"] = real_admin
    return captured
