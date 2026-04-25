"""
Samarkand Bakery — Email Notification System
Sends transactional emails for order lifecycle events.
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# SMTP Configuration — update these with real credentials
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
    """Send notification to admin with CC."""
    return _send_email(ADMIN_EMAIL, subject, html_body, cc=ADMIN_CC)


def _email_wrapper(content_html, title=""):
    """Wrap content in a branded email template."""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f0eb;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">
<div style="max-width:560px;margin:0 auto;padding:24px 16px;">
    <!-- Header -->
    <div style="text-align:center;padding:24px 0 20px;">
        <img src="{SITE_URL}/static/profile-pic.png" alt="Samarkand Bakery" style="width:64px;height:64px;border-radius:50%;">
        <h1 style="font-family:Georgia,serif;font-size:1.4em;color:#1e2a4a;margin:12px 0 4px;">Samarkand Turkic Bakery</h1>
        <p style="color:#9a9aad;font-size:0.85em;margin:0;">Fresh Uzbek & Turkish Baked Goods</p>
    </div>

    <!-- Content card -->
    <div style="background:#ffffff;border-radius:12px;padding:28px;box-shadow:0 2px 8px rgba(30,42,74,0.06);">
        {'<h2 style="font-family:Georgia,serif;font-size:1.3em;color:#1e2a4a;margin:0 0 16px;">' + title + '</h2>' if title else ''}
        {content_html}
    </div>

    <!-- Footer -->
    <div style="text-align:center;padding:24px 0;color:#9a9aad;font-size:0.78em;">
        <p>Samarkand Turkic Bakery — Tetouan, Morocco</p>
        <p><a href="tel:+212680342679" style="color:#1e2a4a;text-decoration:none;">+212 680 342 679</a> &bull;
        <a href="https://www.instagram.com/SamarkandBakery" style="color:#1e2a4a;text-decoration:none;">@SamarkandBakery</a></p>
    </div>
</div>
</body>
</html>"""


def send_contact_inquiry(name, email, message):
    """Send contact form inquiry to admin."""
    content = f"""
    <p style="color:#666;margin:0 0 16px;">New inquiry from the website contact form:</p>
    <table style="width:100%;border-collapse:collapse;">
        <tr style="border-bottom:1px solid #f0ebe3;">
            <td style="padding:10px 0;color:#888;width:80px;">Name</td>
            <td style="padding:10px 0;color:#1e2a4a;font-weight:600;">{name}</td>
        </tr>
        <tr style="border-bottom:1px solid #f0ebe3;">
            <td style="padding:10px 0;color:#888;">Email</td>
            <td style="padding:10px 0;"><a href="mailto:{email}" style="color:#1e2a4a;">{email}</a></td>
        </tr>
        <tr>
            <td style="padding:10px 0;color:#888;vertical-align:top;">Message</td>
            <td style="padding:10px 0;color:#444;line-height:1.6;">{message}</td>
        </tr>
    </table>
    <div style="margin-top:20px;padding:12px 16px;background:#f5f0eb;border-radius:8px;font-size:0.85em;color:#888;">
        Reply directly to this email or contact the customer at {email}
    </div>
    """
    subject = "New Inquiry from " + name + " — Samarkand Bakery"
    html = _email_wrapper(content, title="New Contact Inquiry")
    return _send_admin_notification(subject, html)


def _order_items_html(items):
    """Render order items as HTML table rows."""
    rows = ""
    for item in items:
        rows += f"""<tr style="border-bottom:1px solid #f0ebe3;">
            <td style="padding:10px 0;color:#444;">{item['name']}</td>
            <td style="padding:10px 8px;text-align:center;color:#888;">x{item['quantity']}</td>
            <td style="padding:10px 0;text-align:right;font-weight:600;color:#1e2a4a;">{item['subtotal']:.2f} MAD</td>
        </tr>"""
    return rows


def send_order_placed(order, loyalty_earned=0, loyalty_redeemed_pts=0, loyalty_redeemed_mad=0.0):
    """Email sent when customer places an order."""
    if not order.get("customer_email"):
        return False

    items_html = _order_items_html(order["items"])
    discount_html = ""
    disc_amt = order.get("discount_amount", 0) or 0
    if order.get("promo_code"):
        discount_html = f"""<tr style="border-bottom:1px solid #f0ebe3;">
            <td colspan="2" style="padding:10px 0;color:#2d7a4f;font-weight:600;">Discount ({order['promo_code']})</td>
            <td style="padding:10px 0;text-align:right;color:#2d7a4f;font-weight:600;">-{disc_amt:.2f} MAD</td>
        </tr>"""
    elif disc_amt > 0:
        discount_html = f"""<tr style="border-bottom:1px solid #f0ebe3;">
            <td colspan="2" style="padding:10px 0;color:#2d7a4f;font-weight:600;">Order discount</td>
            <td style="padding:10px 0;text-align:right;color:#2d7a4f;font-weight:600;">-{disc_amt:.2f} MAD</td>
        </tr>"""

    delivery_info = "Pickup from Wilaya Centre"
    if order.get("delivery_type") == "delivery":
        delivery_info = "Delivery to your location"
        if order.get("delivery_address"):
            delivery_info += f" ({order['delivery_address']})"

    loyalty_html = ""
    if loyalty_redeemed_pts > 0 or loyalty_earned > 0:
        loyalty_html = '<div style="margin-top:16px;padding:14px 16px;background:#faf6f1;border-radius:8px;border-left:3px solid #b8860b;">'
        loyalty_html += '<p style="margin:0 0 4px;font-size:0.82em;color:#9a9aad;text-transform:uppercase;letter-spacing:0.05em;font-weight:600;">Loyalty Points</p>'
        if loyalty_redeemed_pts > 0:
            loyalty_html += f'<p style="margin:4px 0;font-size:0.9em;color:#c0392b;">&#9733; <strong>{loyalty_redeemed_pts} points redeemed</strong> &mdash; {loyalty_redeemed_mad:.2f} MAD off this order</p>'
        if loyalty_earned > 0:
            loyalty_html += f'<p style="margin:4px 0;font-size:0.9em;color:#2d7a4f;">&#9733; <strong>+{loyalty_earned} points earned</strong> on this order</p>'
        loyalty_html += '</div>'

    content = f"""
    <p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
        Thank you, <strong style="color:#1e2a4a;">{order['customer_name']}</strong>! Your order has been received and is being reviewed.
    </p>

    <div style="background:#f5f0eb;border-radius:8px;padding:14px 16px;margin-bottom:20px;">
        <p style="margin:0;font-size:0.88em;color:#6b6b80;">
            <strong style="color:#1e2a4a;">Order #{order['id']}</strong><br>
            {delivery_info}<br>
            {"Preferred date: <strong style='color:#b8860b;'>" + str(order.get('preferred_date', 'Not specified')) + "</strong>" if order.get('preferred_date') else ''}
        </p>
    </div>

    <table style="width:100%;border-collapse:collapse;font-size:0.92em;margin-bottom:16px;">
        {items_html}
        {discount_html}
        <tr>
            <td colspan="2" style="padding:14px 0 0;font-weight:700;font-size:1.1em;color:#1e2a4a;border-top:2px solid #1e2a4a;">Total</td>
            <td style="padding:14px 0 0;text-align:right;font-weight:700;font-size:1.1em;color:#b8860b;border-top:2px solid #1e2a4a;">{order['total_price']:.2f} MAD</td>
        </tr>
    </table>

    {loyalty_html}

    <p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:{'16px' if loyalty_html else '0'} 0 0;">
        We will confirm your order shortly. If you have any questions, contact us on WhatsApp at +212 680 342 679.
    </p>
    """

    html = _email_wrapper(content, "Order Received!")
    subject = "Order #" + str(order["id"]) + " Received — Samarkand Bakery"
    # Send to customer
    _send_email(order["customer_email"], subject, html)
    # Notify admin
    _send_admin_notification("New Order #" + str(order["id"]) + " — " + order["customer_name"], html)
    return True


def send_order_confirmed(order):
    """Email sent when admin confirms an order."""
    if not order.get("customer_email"):
        return False

    items_html = _order_items_html(order["items"])

    content = f"""
    <p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
        Great news, <strong style="color:#1e2a4a;">{order['customer_name']}</strong>! Your order has been confirmed and we're preparing it.
    </p>

    <div style="background:#e8f5e9;border-radius:8px;padding:14px 16px;margin-bottom:20px;border-left:4px solid #2d7a4f;">
        <p style="margin:0;font-size:0.92em;color:#2d7a4f;font-weight:600;">
            Order #{order['id']} — Confirmed
        </p>
        {"<p style='margin:6px 0 0;font-size:0.88em;color:#444;'>Delivery date: <strong style='color:#b8860b;'>" + str(order.get('preferred_date', '')) + "</strong></p>" if order.get('preferred_date') else ''}
    </div>

    <table style="width:100%;border-collapse:collapse;font-size:0.92em;margin-bottom:16px;">
        {items_html}
        <tr>
            <td colspan="2" style="padding:14px 0 0;font-weight:700;color:#1e2a4a;border-top:2px solid #1e2a4a;">Total</td>
            <td style="padding:14px 0 0;text-align:right;font-weight:700;color:#b8860b;border-top:2px solid #1e2a4a;">{order['total_price']:.2f} MAD</td>
        </tr>
    </table>

    <p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
        We'll notify you when your order is ready. Thank you for choosing Samarkand Bakery!
    </p>
    """

    html = _email_wrapper(content, "Order Confirmed!")
    return _send_email(order["customer_email"], f"Order #{order['id']} Confirmed — Samarkand Bakery", html)


def send_order_completed(order):
    """Email sent when order is marked as completed."""
    if not order.get("customer_email"):
        return False

    # Build review links for each unique product
    product_keys = list(set(item["key"] for item in order["items"]))
    review_links = ""
    for key in product_keys:
        name = next((i["name"] for i in order["items"] if i["key"] == key), key)
        review_links += f'<a href="{SITE_URL}/product/{key}#review-form" style="display:inline-block;margin:4px 4px 4px 0;padding:8px 16px;background:#1e2a4a;color:#fff;border-radius:6px;text-decoration:none;font-size:0.85em;font-weight:600;">{name}</a> '

    content = f"""
    <p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
        Hi <strong style="color:#1e2a4a;">{order['customer_name']}</strong>, your order has been completed! We hope you enjoy everything.
    </p>

    <div style="background:#e3f2fd;border-radius:8px;padding:14px 16px;margin-bottom:20px;border-left:4px solid #1565c0;">
        <p style="margin:0;font-size:0.92em;color:#1565c0;font-weight:600;">
            Order #{order['id']} — Completed
        </p>
        <p style="margin:6px 0 0;font-size:0.88em;color:#444;">Total: <strong>{order['total_price']:.2f} MAD</strong></p>
    </div>

    <div style="background:#faf6f1;border-radius:8px;padding:20px;margin-bottom:16px;text-align:center;">
        <p style="font-family:Georgia,serif;font-size:1.1em;color:#1e2a4a;margin:0 0 8px;font-weight:600;">How was your order?</p>
        <p style="color:#6b6b80;font-size:0.88em;margin:0 0 14px;">We'd love to hear your feedback! Leave a review for the products you tried:</p>
        <div>{review_links}</div>
    </div>

    <p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
        Thank you for ordering from Samarkand Bakery! We look forward to serving you again.
    </p>
    """

    html = _email_wrapper(content, "Your Opinion Matters")
    return _send_email(order["customer_email"], f"Your Opinion Matters — Samarkand Bakery", html)


def send_loyalty_code(to_email, code, customer_name=None, ttl_minutes=15):
    """Send a 6-digit verification code so the customer can redeem loyalty points."""
    if not to_email:
        return False
    greeting = "Hi " + customer_name + "," if customer_name else "Hi,"
    content = f"""
    <p style="color:#6b6b80;line-height:1.6;margin:0 0 18px;">
        {greeting} use the code below to confirm your loyalty points redemption at checkout.
    </p>

    <div style="text-align:center;margin:24px 0;padding:24px 0;background:#faf6f1;border-radius:10px;">
        <p style="margin:0 0 8px;color:#9a9aad;font-size:0.78em;letter-spacing:0.08em;text-transform:uppercase;">Your verification code</p>
        <div style="font-family:'Courier New',monospace;font-size:2.2em;font-weight:700;color:#1e2a4a;letter-spacing:0.4em;padding-left:0.4em;">{code}</div>
        <p style="margin:10px 0 0;color:#9a9aad;font-size:0.78em;">Valid for {ttl_minutes} minutes</p>
    </div>

    <p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
        If you did not request this code, you can safely ignore this email — your points are still safe.
    </p>
    """
    html = _email_wrapper(content, "Loyalty Points Verification")
    subject = "Your Samarkand Bakery loyalty code: " + code
    return _send_email(to_email, subject, html)
