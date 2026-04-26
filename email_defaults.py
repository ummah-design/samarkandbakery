"""
Default email template content (seed data).

These are loaded into the `email_templates` SQLite table on first run.
Admin can edit them via the admin Email Templates page; defaults can also be
restored individually from there.

Placeholders use the {{name}} syntax and are substituted by emailer.py.
The branded header/footer is wrapped around `body_html` automatically — these
templates only need to contain the inner card content.

Available placeholders by template type:

  order_placed           {{customer_name}}, {{order_id}}, {{total_price}},
                         {{items_table}}, {{delivery_info}},
                         {{preferred_date_block}}, {{discount_block}},
                         {{loyalty_block}}, {{title}}

  order_confirmed        {{customer_name}}, {{order_id}}, {{total_price}},
                         {{items_table}}, {{preferred_date_block}}, {{title}}

  order_completed        {{customer_name}}, {{order_id}}, {{total_price}},
                         {{review_links_block}}, {{title}}

  contact_inquiry        {{name}}, {{email}}, {{message}}, {{title}}

  loyalty_code           {{customer_name}}, {{greeting}}, {{code}},
                         {{ttl_minutes}}, {{title}}
"""

# ── Title strings used by the wrapper card heading ──

_TITLES = {
    "order_placed":     {"en": "Order Received!",          "fr": "Commande reçue !",            "ar": "تم استلام الطلب!"},
    "order_confirmed":  {"en": "Order Confirmed!",         "fr": "Commande confirmée !",        "ar": "تم تأكيد الطلب!"},
    "order_completed":  {"en": "Your Opinion Matters",     "fr": "Votre avis compte",           "ar": "رأيك يهمنا"},
    "contact_inquiry":  {"en": "New Contact Inquiry",      "fr": "Nouveau message de contact",  "ar": "استفسار جديد"},
    "loyalty_code":     {"en": "Loyalty Points Verification", "fr": "Vérification des points fidélité", "ar": "رمز التحقق من نقاط الولاء"},
}


def get_default_title(template_type, language):
    """Title shown as the H2 heading inside the email card."""
    return _TITLES.get(template_type, {}).get(language) or _TITLES.get(template_type, {}).get("en", "")


# ── Subjects ──

_SUBJECTS = {
    "order_placed": {
        "en": "Order #{{order_id}} Received — Samarkand Bakery",
        "fr": "Commande #{{order_id}} reçue — Samarkand Bakery",
        "ar": "تم استلام الطلب #{{order_id}} — Samarkand Bakery",
    },
    "order_confirmed": {
        "en": "Order #{{order_id}} Confirmed — Samarkand Bakery",
        "fr": "Commande #{{order_id}} confirmée — Samarkand Bakery",
        "ar": "تم تأكيد الطلب #{{order_id}} — Samarkand Bakery",
    },
    "order_completed": {
        "en": "Your Opinion Matters — Samarkand Bakery",
        "fr": "Votre avis compte — Samarkand Bakery",
        "ar": "رأيك يهمنا — Samarkand Bakery",
    },
    "contact_inquiry": {
        "en": "New Inquiry from {{name}} — Samarkand Bakery",
        "fr": "Nouveau message de {{name}} — Samarkand Bakery",
        "ar": "استفسار جديد من {{name}} — Samarkand Bakery",
    },
    "loyalty_code": {
        "en": "Your Samarkand Bakery loyalty code: {{code}}",
        "fr": "Votre code fidélité Samarkand Bakery : {{code}}",
        "ar": "رمز نقاط الولاء الخاص بك من Samarkand Bakery: {{code}}",
    },
}


# ── Bodies (inner card HTML) ──

_BODY_ORDER_PLACED = {
    "en": """<p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
    Thank you, <strong style="color:#1e2a4a;">{{customer_name}}</strong>! Your order has been received and is being reviewed.
</p>

<div style="background:#f5f0eb;border-radius:8px;padding:14px 16px;margin-bottom:20px;">
    <p style="margin:0;font-size:0.88em;color:#6b6b80;">
        <strong style="color:#1e2a4a;">Order #{{order_id}}</strong><br>
        {{delivery_info}}
        {{preferred_date_block}}
    </p>
</div>

<table style="width:100%;border-collapse:collapse;font-size:0.92em;margin-bottom:16px;">
    {{items_table}}
    {{discount_block}}
    <tr>
        <td colspan="2" style="padding:14px 0 0;font-weight:700;font-size:1.1em;color:#1e2a4a;border-top:2px solid #1e2a4a;">Total</td>
        <td style="padding:14px 0 0;text-align:right;font-weight:700;font-size:1.1em;color:#b8860b;border-top:2px solid #1e2a4a;">{{total_price}} MAD</td>
    </tr>
</table>

{{loyalty_block}}

<p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:16px 0 0;">
    We will confirm your order shortly. If you have any questions, contact us on WhatsApp at +212 680 342 679.
</p>""",

    "fr": """<p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
    Merci, <strong style="color:#1e2a4a;">{{customer_name}}</strong> ! Votre commande a bien été reçue et est en cours de révision.
</p>

<div style="background:#f5f0eb;border-radius:8px;padding:14px 16px;margin-bottom:20px;">
    <p style="margin:0;font-size:0.88em;color:#6b6b80;">
        <strong style="color:#1e2a4a;">Commande #{{order_id}}</strong><br>
        {{delivery_info}}
        {{preferred_date_block}}
    </p>
</div>

<table style="width:100%;border-collapse:collapse;font-size:0.92em;margin-bottom:16px;">
    {{items_table}}
    {{discount_block}}
    <tr>
        <td colspan="2" style="padding:14px 0 0;font-weight:700;font-size:1.1em;color:#1e2a4a;border-top:2px solid #1e2a4a;">Total</td>
        <td style="padding:14px 0 0;text-align:right;font-weight:700;font-size:1.1em;color:#b8860b;border-top:2px solid #1e2a4a;">{{total_price}} MAD</td>
    </tr>
</table>

{{loyalty_block}}

<p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:16px 0 0;">
    Nous confirmerons votre commande sous peu. Pour toute question, contactez-nous sur WhatsApp au +212 680 342 679.
</p>""",

    "ar": """<p dir="rtl" style="color:#6b6b80;line-height:1.7;margin:0 0 20px;text-align:right;">
    شكرًا لك يا <strong style="color:#1e2a4a;">{{customer_name}}</strong>! تم استلام طلبك ونقوم بمراجعته الآن.
</p>

<div dir="rtl" style="background:#f5f0eb;border-radius:8px;padding:14px 16px;margin-bottom:20px;text-align:right;">
    <p style="margin:0;font-size:0.9em;color:#6b6b80;">
        <strong style="color:#1e2a4a;">طلب رقم #{{order_id}}</strong><br>
        {{delivery_info}}
        {{preferred_date_block}}
    </p>
</div>

<table dir="rtl" style="width:100%;border-collapse:collapse;font-size:0.95em;margin-bottom:16px;">
    {{items_table}}
    {{discount_block}}
    <tr>
        <td colspan="2" style="padding:14px 0 0;font-weight:700;font-size:1.1em;color:#1e2a4a;border-top:2px solid #1e2a4a;">المجموع</td>
        <td style="padding:14px 0 0;text-align:left;font-weight:700;font-size:1.1em;color:#b8860b;border-top:2px solid #1e2a4a;">{{total_price}} درهم</td>
    </tr>
</table>

{{loyalty_block}}

<p dir="rtl" style="color:#9a9aad;font-size:0.85em;line-height:1.6;margin:16px 0 0;text-align:right;">
    سنؤكد طلبك قريبًا. إذا كان لديك أي سؤال، تواصل معنا على واتساب: ‎+212 680 342 679.
</p>""",
}


_BODY_ORDER_CONFIRMED = {
    "en": """<p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
    Great news, <strong style="color:#1e2a4a;">{{customer_name}}</strong>! Your order has been confirmed and we're preparing it.
</p>

<div style="background:#e8f5e9;border-radius:8px;padding:14px 16px;margin-bottom:20px;border-left:4px solid #2d7a4f;">
    <p style="margin:0;font-size:0.92em;color:#2d7a4f;font-weight:600;">
        Order #{{order_id}} — Confirmed
    </p>
    {{preferred_date_block}}
</div>

<table style="width:100%;border-collapse:collapse;font-size:0.92em;margin-bottom:16px;">
    {{items_table}}
    <tr>
        <td colspan="2" style="padding:14px 0 0;font-weight:700;color:#1e2a4a;border-top:2px solid #1e2a4a;">Total</td>
        <td style="padding:14px 0 0;text-align:right;font-weight:700;color:#b8860b;border-top:2px solid #1e2a4a;">{{total_price}} MAD</td>
    </tr>
</table>

<p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
    We'll notify you when your order is ready. Thank you for choosing Samarkand Bakery!
</p>""",

    "fr": """<p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
    Bonne nouvelle, <strong style="color:#1e2a4a;">{{customer_name}}</strong> ! Votre commande est confirmée et nous la préparons.
</p>

<div style="background:#e8f5e9;border-radius:8px;padding:14px 16px;margin-bottom:20px;border-left:4px solid #2d7a4f;">
    <p style="margin:0;font-size:0.92em;color:#2d7a4f;font-weight:600;">
        Commande #{{order_id}} — Confirmée
    </p>
    {{preferred_date_block}}
</div>

<table style="width:100%;border-collapse:collapse;font-size:0.92em;margin-bottom:16px;">
    {{items_table}}
    <tr>
        <td colspan="2" style="padding:14px 0 0;font-weight:700;color:#1e2a4a;border-top:2px solid #1e2a4a;">Total</td>
        <td style="padding:14px 0 0;text-align:right;font-weight:700;color:#b8860b;border-top:2px solid #1e2a4a;">{{total_price}} MAD</td>
    </tr>
</table>

<p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
    Nous vous préviendrons dès que votre commande sera prête. Merci d'avoir choisi Samarkand Bakery !
</p>""",

    "ar": """<p dir="rtl" style="color:#6b6b80;line-height:1.7;margin:0 0 20px;text-align:right;">
    خبر سار يا <strong style="color:#1e2a4a;">{{customer_name}}</strong>! تم تأكيد طلبك ونقوم بتحضيره الآن.
</p>

<div dir="rtl" style="background:#e8f5e9;border-radius:8px;padding:14px 16px;margin-bottom:20px;border-right:4px solid #2d7a4f;text-align:right;">
    <p style="margin:0;font-size:0.95em;color:#2d7a4f;font-weight:600;">
        طلب رقم #{{order_id}} — مؤكَّد
    </p>
    {{preferred_date_block}}
</div>

<table dir="rtl" style="width:100%;border-collapse:collapse;font-size:0.95em;margin-bottom:16px;">
    {{items_table}}
    <tr>
        <td colspan="2" style="padding:14px 0 0;font-weight:700;color:#1e2a4a;border-top:2px solid #1e2a4a;">المجموع</td>
        <td style="padding:14px 0 0;text-align:left;font-weight:700;color:#b8860b;border-top:2px solid #1e2a4a;">{{total_price}} درهم</td>
    </tr>
</table>

<p dir="rtl" style="color:#9a9aad;font-size:0.85em;line-height:1.6;margin:0;text-align:right;">
    سنخبرك عندما يصبح طلبك جاهزًا. شكرًا لاختيارك Samarkand Bakery!
</p>""",
}


_BODY_ORDER_COMPLETED = {
    "en": """<p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
    Hi <strong style="color:#1e2a4a;">{{customer_name}}</strong>, your order has been completed! We hope you enjoy everything.
</p>

<div style="background:#e3f2fd;border-radius:8px;padding:14px 16px;margin-bottom:20px;border-left:4px solid #1565c0;">
    <p style="margin:0;font-size:0.92em;color:#1565c0;font-weight:600;">
        Order #{{order_id}} — Completed
    </p>
    <p style="margin:6px 0 0;font-size:0.88em;color:#444;">Total: <strong>{{total_price}} MAD</strong></p>
</div>

<div style="background:#faf6f1;border-radius:8px;padding:20px;margin-bottom:16px;text-align:center;">
    <p style="font-family:Georgia,serif;font-size:1.1em;color:#1e2a4a;margin:0 0 8px;font-weight:600;">How was your order?</p>
    <p style="color:#6b6b80;font-size:0.88em;margin:0 0 14px;">We'd love to hear your feedback! Leave a review for the products you tried:</p>
    <div>{{review_links_block}}</div>
</div>

<p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
    Thank you for ordering from Samarkand Bakery! We look forward to serving you again.
</p>""",

    "fr": """<p style="color:#6b6b80;line-height:1.6;margin:0 0 20px;">
    Bonjour <strong style="color:#1e2a4a;">{{customer_name}}</strong>, votre commande a été terminée ! Nous espérons que vous apprécierez tout.
</p>

<div style="background:#e3f2fd;border-radius:8px;padding:14px 16px;margin-bottom:20px;border-left:4px solid #1565c0;">
    <p style="margin:0;font-size:0.92em;color:#1565c0;font-weight:600;">
        Commande #{{order_id}} — Terminée
    </p>
    <p style="margin:6px 0 0;font-size:0.88em;color:#444;">Total : <strong>{{total_price}} MAD</strong></p>
</div>

<div style="background:#faf6f1;border-radius:8px;padding:20px;margin-bottom:16px;text-align:center;">
    <p style="font-family:Georgia,serif;font-size:1.1em;color:#1e2a4a;margin:0 0 8px;font-weight:600;">Comment était votre commande ?</p>
    <p style="color:#6b6b80;font-size:0.88em;margin:0 0 14px;">Votre avis nous intéresse ! Laissez un commentaire pour les produits que vous avez essayés :</p>
    <div>{{review_links_block}}</div>
</div>

<p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
    Merci d'avoir commandé chez Samarkand Bakery ! Nous serions ravis de vous servir à nouveau.
</p>""",

    "ar": """<p dir="rtl" style="color:#6b6b80;line-height:1.7;margin:0 0 20px;text-align:right;">
    مرحبًا <strong style="color:#1e2a4a;">{{customer_name}}</strong>، تم إكمال طلبك! نتمنى أن يعجبك كل شيء.
</p>

<div dir="rtl" style="background:#e3f2fd;border-radius:8px;padding:14px 16px;margin-bottom:20px;border-right:4px solid #1565c0;text-align:right;">
    <p style="margin:0;font-size:0.95em;color:#1565c0;font-weight:600;">
        طلب رقم #{{order_id}} — مكتمل
    </p>
    <p style="margin:6px 0 0;font-size:0.9em;color:#444;">المجموع: <strong>{{total_price}} درهم</strong></p>
</div>

<div dir="rtl" style="background:#faf6f1;border-radius:8px;padding:20px;margin-bottom:16px;text-align:center;">
    <p style="font-family:Georgia,serif;font-size:1.15em;color:#1e2a4a;margin:0 0 8px;font-weight:600;">كيف كان طلبك؟</p>
    <p style="color:#6b6b80;font-size:0.9em;margin:0 0 14px;">يسعدنا سماع رأيك! اترك تقييمًا للمنتجات التي جربتها:</p>
    <div>{{review_links_block}}</div>
</div>

<p dir="rtl" style="color:#9a9aad;font-size:0.85em;line-height:1.6;margin:0;text-align:right;">
    شكرًا لطلبك من Samarkand Bakery! نتطلع إلى خدمتك مرة أخرى.
</p>""",
}


_BODY_CONTACT_INQUIRY = {
    "en": """<p style="color:#666;margin:0 0 16px;">New inquiry from the website contact form:</p>
<table style="width:100%;border-collapse:collapse;">
    <tr style="border-bottom:1px solid #f0ebe3;">
        <td style="padding:10px 0;color:#888;width:80px;">Name</td>
        <td style="padding:10px 0;color:#1e2a4a;font-weight:600;">{{name}}</td>
    </tr>
    <tr style="border-bottom:1px solid #f0ebe3;">
        <td style="padding:10px 0;color:#888;">Email</td>
        <td style="padding:10px 0;"><a href="mailto:{{email}}" style="color:#1e2a4a;">{{email}}</a></td>
    </tr>
    <tr>
        <td style="padding:10px 0;color:#888;vertical-align:top;">Message</td>
        <td style="padding:10px 0;color:#444;line-height:1.6;">{{message}}</td>
    </tr>
</table>
<div style="margin-top:20px;padding:12px 16px;background:#f5f0eb;border-radius:8px;font-size:0.85em;color:#888;">
    Reply directly to this email or contact the customer at {{email}}
</div>""",

    "fr": """<p style="color:#666;margin:0 0 16px;">Nouveau message depuis le formulaire de contact :</p>
<table style="width:100%;border-collapse:collapse;">
    <tr style="border-bottom:1px solid #f0ebe3;">
        <td style="padding:10px 0;color:#888;width:80px;">Nom</td>
        <td style="padding:10px 0;color:#1e2a4a;font-weight:600;">{{name}}</td>
    </tr>
    <tr style="border-bottom:1px solid #f0ebe3;">
        <td style="padding:10px 0;color:#888;">E-mail</td>
        <td style="padding:10px 0;"><a href="mailto:{{email}}" style="color:#1e2a4a;">{{email}}</a></td>
    </tr>
    <tr>
        <td style="padding:10px 0;color:#888;vertical-align:top;">Message</td>
        <td style="padding:10px 0;color:#444;line-height:1.6;">{{message}}</td>
    </tr>
</table>
<div style="margin-top:20px;padding:12px 16px;background:#f5f0eb;border-radius:8px;font-size:0.85em;color:#888;">
    Répondez directement à cet e-mail ou contactez le client à {{email}}
</div>""",

    "ar": """<p dir="rtl" style="color:#666;margin:0 0 16px;text-align:right;">استفسار جديد من نموذج التواصل في الموقع:</p>
<table dir="rtl" style="width:100%;border-collapse:collapse;">
    <tr style="border-bottom:1px solid #f0ebe3;">
        <td style="padding:10px 0;color:#888;width:90px;">الاسم</td>
        <td style="padding:10px 0;color:#1e2a4a;font-weight:600;">{{name}}</td>
    </tr>
    <tr style="border-bottom:1px solid #f0ebe3;">
        <td style="padding:10px 0;color:#888;">البريد الإلكتروني</td>
        <td style="padding:10px 0;"><a href="mailto:{{email}}" style="color:#1e2a4a;">{{email}}</a></td>
    </tr>
    <tr>
        <td style="padding:10px 0;color:#888;vertical-align:top;">الرسالة</td>
        <td style="padding:10px 0;color:#444;line-height:1.7;">{{message}}</td>
    </tr>
</table>
<div dir="rtl" style="margin-top:20px;padding:12px 16px;background:#f5f0eb;border-radius:8px;font-size:0.88em;color:#888;text-align:right;">
    يمكنك الرد مباشرة على هذه الرسالة أو التواصل مع العميل عبر {{email}}
</div>""",
}


_BODY_LOYALTY_CODE = {
    "en": """<p style="color:#6b6b80;line-height:1.6;margin:0 0 18px;">
    {{greeting}} use the code below to confirm your loyalty points redemption at checkout.
</p>

<div style="text-align:center;margin:24px 0;padding:24px 0;background:#faf6f1;border-radius:10px;">
    <p style="margin:0 0 8px;color:#9a9aad;font-size:0.78em;letter-spacing:0.08em;text-transform:uppercase;">Your verification code</p>
    <div style="font-family:'Courier New',monospace;font-size:2.2em;font-weight:700;color:#1e2a4a;letter-spacing:0.4em;padding-left:0.4em;">{{code}}</div>
    <p style="margin:10px 0 0;color:#9a9aad;font-size:0.78em;">Valid for {{ttl_minutes}} minutes</p>
</div>

<p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
    If you did not request this code, you can safely ignore this email — your points are still safe.
</p>""",

    "fr": """<p style="color:#6b6b80;line-height:1.6;margin:0 0 18px;">
    {{greeting}} utilisez le code ci-dessous pour confirmer l'utilisation de vos points fidélité à la caisse.
</p>

<div style="text-align:center;margin:24px 0;padding:24px 0;background:#faf6f1;border-radius:10px;">
    <p style="margin:0 0 8px;color:#9a9aad;font-size:0.78em;letter-spacing:0.08em;text-transform:uppercase;">Votre code de vérification</p>
    <div style="font-family:'Courier New',monospace;font-size:2.2em;font-weight:700;color:#1e2a4a;letter-spacing:0.4em;padding-left:0.4em;">{{code}}</div>
    <p style="margin:10px 0 0;color:#9a9aad;font-size:0.78em;">Valable pendant {{ttl_minutes}} minutes</p>
</div>

<p style="color:#9a9aad;font-size:0.82em;line-height:1.5;margin:0;">
    Si vous n'avez pas demandé ce code, vous pouvez ignorer cet e-mail — vos points restent sécurisés.
</p>""",

    "ar": """<p dir="rtl" style="color:#6b6b80;line-height:1.7;margin:0 0 18px;text-align:right;">
    {{greeting}} استخدم الرمز أدناه لتأكيد استبدال نقاط الولاء عند الدفع.
</p>

<div style="text-align:center;margin:24px 0;padding:24px 0;background:#faf6f1;border-radius:10px;">
    <p style="margin:0 0 8px;color:#9a9aad;font-size:0.85em;letter-spacing:0.05em;">رمز التحقق الخاص بك</p>
    <div style="font-family:'Courier New',monospace;font-size:2.2em;font-weight:700;color:#1e2a4a;letter-spacing:0.4em;padding-left:0.4em;">{{code}}</div>
    <p style="margin:10px 0 0;color:#9a9aad;font-size:0.85em;">صالح لمدة {{ttl_minutes}} دقيقة</p>
</div>

<p dir="rtl" style="color:#9a9aad;font-size:0.85em;line-height:1.6;margin:0;text-align:right;">
    إذا لم تطلب هذا الرمز، يمكنك تجاهل هذه الرسالة بأمان — نقاطك لا تزال محفوظة.
</p>""",
}


# ── Master dict consumed by database.seed_email_templates() ──

DEFAULT_EMAIL_TEMPLATES = {}
_BODIES = {
    "order_placed":    _BODY_ORDER_PLACED,
    "order_confirmed": _BODY_ORDER_CONFIRMED,
    "order_completed": _BODY_ORDER_COMPLETED,
    "contact_inquiry": _BODY_CONTACT_INQUIRY,
    "loyalty_code":    _BODY_LOYALTY_CODE,
}
for _ttype, _by_lang in _BODIES.items():
    DEFAULT_EMAIL_TEMPLATES[_ttype] = {}
    for _lang, _body in _by_lang.items():
        DEFAULT_EMAIL_TEMPLATES[_ttype][_lang] = {
            "subject": _SUBJECTS[_ttype][_lang],
            "body_html": _body,
        }


# ── Localised auxiliary strings (used by emailer when assembling dynamic blocks) ──

LOCALISED_LABELS = {
    "en": {
        "delivery_pickup":      "Pickup from Wilaya Centre",
        "delivery_to_location": "Delivery to your location",
        "preferred_date_label": "Preferred date",
        "discount_with_code":   "Discount ({code})",
        "discount_generic":     "Order discount",
        "loyalty_heading":      "Loyalty Points",
        "loyalty_redeemed":     "{pts} points redeemed",
        "loyalty_redeemed_off": "{mad} MAD off this order",
        "loyalty_earned":       "+{pts} points earned",
        "loyalty_earned_on":    "on this order",
        "greeting_with_name":   "Hi {name},",
        "greeting_no_name":     "Hi,",
        "qty_prefix":           "x",
        "currency":             "MAD",
    },
    "fr": {
        "delivery_pickup":      "Retrait au Centre Wilaya",
        "delivery_to_location": "Livraison à votre adresse",
        "preferred_date_label": "Date souhaitée",
        "discount_with_code":   "Remise ({code})",
        "discount_generic":     "Remise commande",
        "loyalty_heading":      "Points fidélité",
        "loyalty_redeemed":     "{pts} points utilisés",
        "loyalty_redeemed_off": "{mad} MAD de réduction sur cette commande",
        "loyalty_earned":       "+{pts} points gagnés",
        "loyalty_earned_on":    "sur cette commande",
        "greeting_with_name":   "Bonjour {name},",
        "greeting_no_name":     "Bonjour,",
        "qty_prefix":           "x",
        "currency":             "MAD",
    },
    "ar": {
        "delivery_pickup":      "الاستلام من مركز الولاية",
        "delivery_to_location": "التوصيل إلى موقعك",
        "preferred_date_label": "التاريخ المفضل",
        "discount_with_code":   "خصم ({code})",
        "discount_generic":     "خصم على الطلب",
        "loyalty_heading":      "نقاط الولاء",
        "loyalty_redeemed":     "تم استخدام {pts} نقطة",
        "loyalty_redeemed_off": "{mad} درهم خصم على هذا الطلب",
        "loyalty_earned":       "+{pts} نقطة مكتسبة",
        "loyalty_earned_on":    "على هذا الطلب",
        "greeting_with_name":   "مرحبًا {name},",
        "greeting_no_name":     "مرحبًا,",
        "qty_prefix":           "×",
        "currency":             "درهم",
    },
}


def get_labels(language):
    """Return the localised label dict, falling back to English."""
    return LOCALISED_LABELS.get(language) or LOCALISED_LABELS["en"]
