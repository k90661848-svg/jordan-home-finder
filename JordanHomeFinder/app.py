import json
import os
import re
import time
from collections import defaultdict
from functools import wraps
from typing import Any

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(os.path.dirname(__file__), "instance", "jordan_home.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Flask-Mail config (from env)
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", app.config["MAIL_USERNAME"] or "noreply@masar.local")

try:
    from flask_mail import Mail, Message
    mail = Mail(app)
    _has_flask_mail = True
except ImportError:
    mail = None
    _has_flask_mail = False

from models import db, User, FinancialProfile, PropertyFinanceScenario, SavedPlan, ContactSubmission
db.init_app(app)

# Simple rate limit: max 5 contact submissions per IP per hour
_contact_rate_limit: dict[str, list[float]] = defaultdict(list)
CONTACT_RATE_LIMIT = 5
CONTACT_RATE_WINDOW = 3600  # seconds


def _migrate_finance_tables():
    """Add new FinancialProfile columns if missing (migrate from old schema)."""
    from sqlalchemy import text
    with db.engine.connect() as conn:
        for col, typ in [
            ("other_income", "REAL DEFAULT 0"),
            ("savings", "REAL DEFAULT 0"),
            ("existing_debt", "REAL DEFAULT 0"),
            ("risk_tolerance", "VARCHAR(32) DEFAULT 'balanced'"),
            ("created_at", "DATETIME"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE financial_profiles ADD COLUMN {col} {typ}"))
                conn.commit()
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    conn.rollback()
                else:
                    raise


with app.app_context():
    db.create_all()
    try:
        _migrate_finance_tables()
    except Exception as e:
        print("[migrate]", e)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            session["next"] = request.url
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# -------------------------
# PROPERTY DATABASE (JSON)
# -------------------------

def load_properties():
    path = os.path.join(app.root_path, "data", "properties.json")
    if not os.path.exists(path):
        print(f"[ERROR] properties.json not found at: {path}")
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print("[ERROR] Failed to load properties.json:", e)
        return []


app.load_properties = load_properties


# -------------------------
# CHATBOT HELPERS (PARSING + FILTERING)
# -------------------------

def parse_budget_from_text(text: str):
    t = text.lower().replace(",", "").strip()
    m = re.search(r"(under|below|max)\s*(\d{2,6})(k)?", t)
    if m:
        num = int(m.group(2))
        if m.group(3) == "k":
            num *= 1000
        return None, num
    m2 = re.search(r"(\d{2,6})\s*k\b", t)
    if m2:
        return None, int(m2.group(1)) * 1000
    m3 = re.search(r"\b(\d{5,7})\b", t)
    if m3:
        return None, int(m3.group(1))
    return None, None


def parse_bedrooms_from_text(text: str):
    t = text.lower()
    m = re.search(r"(\d+)\s*(bed|beds|bedroom|bedrooms)\b", t)
    if m:
        return int(m.group(1))
    return None


def parse_category_type_from_text(text: str):
    t = text.lower()
    if "apartment" in t or "flat" in t:
        return "residential", "apartment"
    if "villa" in t or "house" in t or "home" in t:
        return "residential", "villa" if "villa" in t else None
    if "office" in t:
        return "commercial", "office"
    if "retail" in t or "shop" in t or "store" in t:
        return "commercial", "retail"
    if "commercial" in t:
        return "commercial", None
    return None, None


LOCATION_SYNONYMS = {
    "jabal amman": "Sweifieh",
    "rainbow street": "Sweifieh",
    "rainbow st": "Sweifieh",
    "jabal": "Sweifieh",
    "downtown amman": "Abdali",
    "airport": "Airport Road",
    "abdali": "Abdali",
    "abdoun": "Abdoun",
    "dabouq": "Dabouq",
    "sweifieh": "Sweifieh",
    "khalda": "Khalda",
    "deir ghbar": "Deir Ghbar",
}


def parse_location_from_text(text: str, properties: list):
    t = text.lower()
    for phrase, actual_loc in LOCATION_SYNONYMS.items():
        if phrase in t:
            return actual_loc
    known_locations = sorted(
        {p.get("location", "").lower() for p in properties if p.get("location")},
        key=len,
        reverse=True,
    )
    for loc in known_locations:
        if not loc or loc not in t:
            continue
        return loc.capitalize() if loc else None
    return None


def parse_studio_from_text(text: str):
    t = text.lower()
    return bool("studio" in t or "studios" in t)


def parse_affordable_from_text(text: str):
    t = text.lower()
    if "affordable" in t or "cheap" in t or "low budget" in t or "budget" in t:
        return 200000
    return None


def parse_garden_from_text(text: str):
    t = text.lower()
    if "garden" in t or "gardens" in t or "yard" in t:
        return "garden"
    return None


def parse_cultural_from_text(text: str):
    t = text.lower()
    if "cultural" in t or "culture" in t or "heritage" in t or "traditional" in t or "classic" in t:
        return "classic"
    return None


def filter_properties(
    properties,
    *,
    location=None,
    category=None,
    prop_type=None,
    min_price=None,
    max_price=None,
    bedrooms=None,
    bedrooms_max=None,
    bathrooms=None,
    min_size=None,
    furnished=None,
    parking=None,
    keyword=None,
    has_images=True,
) -> list[Any]:
    results = []
    for p in properties:
        if has_images:
            if not p.get("images") or len(p.get("images", [])) == 0:
                continue
        p_location = str(p.get("location", "")).lower()
        p_category = str(p.get("category", "")).lower()
        p_type = str(p.get("type", "")).lower()
        p_title = str(p.get("title", "")).lower()
        p_desc = str(p.get("description", "")).lower()
        p_features = " ".join(p.get("features", [])).lower()

        if location and location.lower() not in p_location:
            continue
        if category and category.lower() != p_category:
            continue
        if prop_type and prop_type.lower() != p_type:
            continue
        price = int(p.get("price_jod", 0) or 0)
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        size = int(p.get("size_sqm", 0) or 0)
        if min_size is not None and size < min_size:
            continue
        if (bedrooms is not None or bedrooms_max is not None) and p_category == "residential":
            prop_bedrooms = int(p.get("bedrooms", 0) or 0)
            if bedrooms_max is not None:
                if prop_bedrooms > bedrooms_max:
                    continue
            elif bedrooms is not None:
                if bedrooms >= 5:
                    if prop_bedrooms < 5:
                        continue
                elif prop_bedrooms != bedrooms:
                    continue
        if bathrooms is not None:
            prop_bathrooms = int(p.get("bathrooms", 0) or 0)
            if bathrooms >= 5:
                if prop_bathrooms < 5:
                    continue
            elif prop_bathrooms != bathrooms:
                continue
        if furnished is not None:
            if bool(p.get("furnished", False)) != furnished:
                continue
        if parking is not None:
            if bool(p.get("parking", False)) != parking:
                continue
        if keyword:
            haystack = f"{p_title} {p_desc} {p_features}"
            if keyword.lower() not in haystack:
                continue
        results.append(p)
    return results


def sort_properties(properties, sort_by="price_asc", max_price=None, location=None):
    if sort_by == "price_asc":
        return sorted(properties, key=lambda x: int(x.get("price_jod", 0) or 0))
    if sort_by == "price_desc":
        return sorted(properties, key=lambda x: int(x.get("price_jod", 0) or 0), reverse=True)
    if sort_by == "best_match":
        def score(p):
            price = int(p.get("price_jod", 0) or 0)
            score_val = 0
            if max_price:
                score_val += abs(price - max_price) * 0.001
            if location:
                p_loc = str(p.get("location", "")).lower()
                if location.lower() in p_loc:
                    score_val -= 1000
            score_val += price * 0.0001
            return score_val
        return sorted(properties, key=score)
    return sorted(properties, key=lambda x: int(x.get("price_jod", 0) or 0))


def estimate_monthly_cost(price_jod: int, years=25, rate_pct=7.5, down_pct=20):
    """Monthly mortgage payment (principal + interest) for given params."""
    if price_jod <= 0:
        return 0
    loan = price_jod * (1 - down_pct / 100)
    if loan <= 0:
        return 0
    r = rate_pct / 100 / 12
    n = years * 12
    return loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def compute_loan_plan(price_jod, down_pct, rate_pct, years):
    """Returns dict with monthly, total_interest, loan_amount, etc."""
    loan = price_jod * (1 - down_pct / 100)
    if loan <= 0:
        return {"monthly": 0, "total_interest": 0, "loan_amount": 0, "total_payment": 0}
    r = rate_pct / 100 / 12
    n = years * 12
    monthly = loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    total_payment = monthly * n
    total_interest = total_payment - loan
    return {
        "monthly": round(monthly, 2),
        "total_interest": round(total_interest, 2),
        "loan_amount": round(loan, 2),
        "total_payment": round(total_payment, 2),
        "down_payment": round(price_jod * down_pct / 100, 2),
    }


def format_property_card(prop, max_monthly=None):
    pid = prop.get("id", "")
    title = prop.get("title", "Property")
    price = f'{int(prop.get("price_jod", 0)):,} JOD'
    location = prop.get("location", "")
    city = prop.get("city", "Amman")
    prop_type = prop.get("type", "").title()
    bedrooms = prop.get("bedrooms", 0)
    bathrooms = prop.get("bathrooms", 0)
    size = prop.get("size_sqm", 0)
    estimated_monthly = estimate_monthly_cost(int(prop.get("price_jod", 0)))
    estimated_monthly_str = f"{estimated_monthly:,.0f} JOD/month"
    affordability = _affordability_badge(estimated_monthly, max_monthly) if max_monthly else None
    afford_label = {"within_budget": "Within Budget", "stretch": "Stretch", "above_budget": "Above Budget"}.get(affordability, "")
    images = prop.get("images", [])
    specs = []
    if bedrooms > 0:
        specs.append(f"{bedrooms} bed")
    specs.append(f"{bathrooms} bath")
    specs.append(f"{size} sqm")
    specs_str = " • ".join(specs)

    afford_badge = f'<span style="display:inline-block; margin-left:8px; padding:2px 8px; border-radius:8px; font-size:0.8em; background:rgba(34,197,94,.2); color:#86efac;">{afford_label}</span>' if afford_label and affordability == "within_budget" else (f'<span style="display:inline-block; margin-left:8px; padding:2px 8px; border-radius:8px; font-size:0.8em; background:rgba(245,158,11,.2); color:#fcd34d;">{afford_label}</span>' if afford_label and affordability == "stretch" else (f'<span style="display:inline-block; margin-left:8px; padding:2px 8px; border-radius:8px; font-size:0.8em; background:rgba(239,68,68,.2); color:#fca5a5;">{afford_label}</span>' if afford_label else ""))
    if not images:
        return f'''<div style="border:1px solid rgba(255,255,255,0.25); padding:12px 14px; border-radius:12px; margin:8px 0; background:linear-gradient(135deg, rgba(29,78,216,0.12) 0%, rgba(37,99,235,0.08) 100%); display:flex; align-items:flex-start; gap:12px;">
  <div style="width:56px; height:56px; flex-shrink:0; border-radius:10px; background:linear-gradient(135deg, #1D4ED8, #2563EB); display:flex; align-items:center; justify-content:center; color:white; font-size:1.5rem;">🏠</div>
  <div style="flex:1; min-width:0;">
    <b style="font-size:1.05em; color:#fff;">{title}</b>{afford_badge}
    <div style="margin-top:4px;"><span style="color:#60A5FA; font-weight:700;">{price}</span> <span style="color:rgba(255,255,255,0.7); font-size:0.9em;">• Est. {estimated_monthly_str}</span></div>
    <div style="margin-top:6px; color:rgba(255,255,255,0.85); font-size:0.9em;">📍 {location}, {city} • {prop_type} • {specs_str}</div>
    <div style="margin-top:8px;">
      <a href="/property/{pid}" style="color:#60A5FA; text-decoration:none; font-weight:600; font-size:0.9em;">View details →</a>
      <a href="/finance/property/{pid}" style="margin-left:10px; color:#60A5FA; text-decoration:none; font-weight:600; font-size:0.9em;">💰 Plan Financing</a>
    </div>
    <p style="margin-top:8px; font-size:0.85em; color:rgba(255,255,255,0.75);">Check affordability or compare financing strategies for this home.</p>
  </div>
</div>'''

    image_html = ""
    for img in images[:2]:
        img_path = f'/static/images/{img}'
        image_html += f'<img src="{img_path}" alt="{title}" style="height:100px; width:auto; border-radius:8px; object-fit:cover; flex-shrink:0;" onerror="this.style.display=\'none\';">'
    card_html = f'''
<div style="border:1px solid rgba(255,255,255,0.2); padding:12px; border-radius:12px; margin:10px 0; background:rgba(255,255,255,0.05);">
  <div style="display:flex; gap:10px; overflow:auto; margin-bottom:8px;">
    {image_html}
  </div>
  <div>
    <b style="font-size:1.05em; color:#fff;">{title}</b>{afford_badge}
    <div style="margin-top:4px;"><span style="color:#60A5FA; font-weight:bold;">{price}</span> <span style="color:rgba(255,255,255,0.65); font-size:0.85em;">• Est. {estimated_monthly_str}</span></div>
    <div style="margin-top:2px; color:rgba(255,255,255,0.85); font-size:0.9em;">📍 {location}, {city} • {prop_type} • {specs_str}</div>
    <a href="/property/{pid}" style="display:inline-block; margin-top:6px; color:#60A5FA; text-decoration:none; font-weight:500;">View details →</a>
    <a href="/finance/property/{pid}" style="display:inline-block; margin-top:4px; margin-left:12px; color:#60A5FA; text-decoration:none; font-weight:500;">💰 Plan Financing</a>
    <p style="margin-top:8px; font-size:0.85em; color:rgba(255,255,255,0.75);">Check affordability or compare financing strategies for this home.</p>
  </div>
</div>'''
    return card_html


def format_property_suggestions(props, limit=3, max_monthly=None):
    if not props:
        suggestions = [
            "Try: <strong>apartment in Dabouq under 220k</strong>",
            "Try: <strong>villa in Abdoun under 650k</strong>",
            "Try: <strong>3 bedroom apartment in Sweifieh</strong>",
        ]
        return (
            "I couldn't find a match in the current database.<br><br>"
            "Here are some suggestions:<br>" + "<br>".join(suggestions)
        )
    props_sorted = sorted(props, key=lambda p: len(p.get("images", [])) > 0, reverse=True)
    lines = ["<strong>Here are the best matches:</strong>"]
    for p in props_sorted[:limit]:
        lines.append(format_property_card(p, max_monthly=max_monthly))
    lines.append("<br><small style='color:rgba(255,255,255,0.65);'>Want me to narrow it more? Tell me: area + budget + bedrooms.</small>")
    return "".join(lines)


# -------------------------
# ROUTES
# -------------------------

@app.route("/")
def welcome():
    return render_template("welcome.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or not password:
            flash("Name, email, and password are required.", "error")
            return render_template("index.html")
        if User.query.filter_by(email=email).first():
            flash("An account with this email already exists.", "error")
            return render_template("index.html")
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        flash("Account created successfully.", "success")
        return redirect(url_for("home_page"))
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("index.html", login_mode=True)
        session["user_id"] = user.id
        next_url = session.pop("next", None) or request.args.get("next") or url_for("home_page")
        return redirect(next_url)
    return render_template("index.html", login_mode=True)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("welcome"))


@app.route("/about")
def about_page():
    return render_template("about.html")


def _check_contact_rate_limit(ip: str) -> bool:
    """Return True if under limit, False if rate limited."""
    now = time.time()
    # Prune old entries
    _contact_rate_limit[ip] = [t for t in _contact_rate_limit[ip] if now - t < CONTACT_RATE_WINDOW]
    if len(_contact_rate_limit[ip]) >= CONTACT_RATE_LIMIT:
        return False
    _contact_rate_limit[ip].append(now)
    return True


@app.route("/contact", methods=["GET", "POST"])
def contact_page():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email_addr = (request.form.get("email") or "").strip()
        subject = (request.form.get("subject") or "").strip()
        message = (request.form.get("message") or "").strip()
        phone = (request.form.get("phone") or "").strip() or None

        errors = []
        if not full_name:
            errors.append("Full name is required.")
        if not email_addr:
            errors.append("Email is required.")
        elif not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email_addr):
            errors.append("Please enter a valid email address.")
        if not subject:
            errors.append("Please select a subject.")
        if not message:
            errors.append("Message is required.")

        if errors:
            flash(" ".join(errors), "error")
            return render_template(
                "contact.html",
                full_name=full_name,
                email=email_addr,
                subject=subject,
                message=message,
                phone=phone or "",
            )

        # Rate limit
        client_ip = request.remote_addr or "unknown"
        if not _check_contact_rate_limit(client_ip):
            flash("Too many submissions. Please try again later.", "error")
            return render_template(
                "contact.html",
                full_name=full_name,
                email=email_addr,
                subject=subject,
                message=message,
                phone=phone or "",
            )

        contact_email = "contact.almasar@gmail.com"
        user_id = session.get("user_id")
        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        email_body = f"""Full Name: {full_name}
Email: {email_addr}
Subject: {subject}
Phone: {phone or '(not provided)'}
User ID: {user_id if user_id else '(not logged in)'}
Timestamp: {timestamp_str}

Message:
{message}
"""

        email_subject = f"[Masar Contact] - {subject} - {full_name}"

        email_sent = False
        if app.config["MAIL_SERVER"] and app.config["MAIL_USERNAME"] and app.config["MAIL_PASSWORD"]:
            try:
                import smtplib
                from email.mime.text import MIMEText
                from email.utils import formataddr
                msg = MIMEText(email_body, "plain", "utf-8")
                msg["Subject"] = email_subject
                msg["From"] = formataddr(("Masar Contact", app.config["MAIL_USERNAME"]))
                msg["To"] = contact_email
                msg["Reply-To"] = email_addr
                with smtplib.SMTP(app.config["MAIL_SERVER"], app.config["MAIL_PORT"]) as smtp:
                    if app.config["MAIL_USE_TLS"]:
                        smtp.starttls()
                    smtp.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
                    smtp.sendmail(app.config["MAIL_USERNAME"], [contact_email], msg.as_string())
                email_sent = True
            except Exception as e:
                app.logger.error("[contact] Email send failed: %s", e)
                print("[contact] Email send failed:", e)

        if not email_sent:
            try:
                sub = ContactSubmission(
                    full_name=full_name,
                    email=email_addr,
                    subject=subject,
                    message=message,
                    phone=phone,
                )
                db.session.add(sub)
                db.session.commit()
            except Exception as e:
                app.logger.error("[contact] DB save failed: %s", e)
                print("[contact] DB save failed:", e)
                flash(
                    "We could not send your message. Please try again later or email us directly at contact.almasar@gmail.com.",
                    "error",
                )
                return render_template(
                    "contact.html",
                    full_name=full_name,
                    email=email_addr,
                    subject=subject,
                    message=message,
                    phone=phone or "",
                )
            flash(
                "Your message was saved but we could not send email. We will contact you soon.",
                "success",
            )
        else:
            flash(
                "Your message has been successfully sent. We will contact you within 24–48 hours.",
                "success",
            )
        return redirect(url_for("contact_page"))

    return render_template("contact.html")


@app.route("/home")
@login_required
def home_page():
    all_props = load_properties()
    with_images = [p for p in all_props if p.get("images") and len(p.get("images", [])) > 0]
    with_images.sort(key=lambda x: len(x.get("images", [])), reverse=True)
    slide_properties = with_images[:8]
    return render_template("home.html", slide_properties=slide_properties)


@app.route("/chatbot")
@login_required
def chatbot_page():
    return render_template("chatbot.html")


@app.route("/filters")
@login_required
def filters_page():
    max_monthly = None
    if session.get("user_id"):
        profile = _get_profile(session["user_id"])
        if profile and profile.total_income:
            max_monthly = round(profile.total_income * 0.35, 0)
    return render_template("filters.html", max_monthly=max_monthly)


@app.route("/listings")
@login_required
def listings_page():
    properties = load_properties()
    location = request.args.get("location", "").strip() or None
    category = request.args.get("category", "").strip() or None
    min_price = request.args.get("min_price", type=int)
    max_price = request.args.get("max_price", type=int)
    bedrooms = request.args.get("bedrooms", type=int)
    if bedrooms == 5:
        bedrooms = 5  # 5+ means 5 or more
    if location or category or min_price or max_price or bedrooms is not None:
        properties = filter_properties(
            properties,
            location=location,
            category=category,
            min_price=min_price,
            max_price=max_price,
            bedrooms=bedrooms,
            has_images=False,
        )
    properties = sorted(properties, key=lambda p: len(p.get("images", [])), reverse=True)
    max_monthly = None
    if session.get("user_id"):
        profile = _get_profile(session["user_id"])
        if profile and profile.total_income:
            max_monthly = round(profile.total_income * 0.35, 0)
    for p in properties:
        em = estimate_monthly_cost(int(p.get("price_jod", 0) or 0))
        p["estimated_monthly"] = em
        p["affordability_badge"] = _affordability_badge(em, max_monthly) if max_monthly else None
    return render_template("listings.html", properties=properties)


def _affordability_badge(est_monthly, max_monthly):
    """Return Within Budget / Stretch / Above Budget from estimated monthly vs max (35% income)."""
    if max_monthly is None or max_monthly <= 0:
        return None
    if est_monthly <= max_monthly * 0.28:
        return "within_budget"
    if est_monthly <= max_monthly:
        return "stretch"
    return "above_budget"


@app.route("/property/<property_id>")
@login_required
def property_detail_page(property_id):
    properties = load_properties()
    prop = next((p for p in properties if str(p.get("id")) == str(property_id)), None)
    if not prop:
        return "Property not found", 404
    price = int(prop.get("price_jod", 0) or 0)
    est_monthly = estimate_monthly_cost(price)
    down_20 = round(price * 0.20, 0)
    months_to_goal = None
    affordability_badge = None
    if session.get("user_id"):
        profile = _get_profile(session["user_id"])
        if profile and (profile.monthly_income or profile.other_income) and profile.monthly_expenses is not None:
            from finance import savings_plan
            target_down = down_20
            closing_est = price * 0.02
            sp = savings_plan(
                target_down, closing_est, 0,
                profile.savings or 0,
                profile.savings_capacity(),
                None,
            )
            if sp.get("months_to_goal") is not None:
                months_to_goal = sp["months_to_goal"]
            max_monthly = profile.total_income * 0.35
            affordability_badge = _affordability_badge(est_monthly, max_monthly)
    return render_template(
        "property.html",
        property=prop,
        est_monthly=est_monthly,
        down_20=down_20,
        months_to_goal=months_to_goal,
        affordability_badge=affordability_badge,
    )


@app.route("/api/search")
def api_search():
    if not session.get("user_id"):
        return jsonify({"properties": [], "count": 0, "error": "unauthorized"}), 401
    properties = load_properties()
    location = request.args.get("location", "").strip() or None
    category = request.args.get("category", "").strip() or None
    prop_type = request.args.get("type", "").strip() or None
    min_price = request.args.get("min_price", type=int)
    max_price = request.args.get("max_price", type=int)
    bedrooms = request.args.get("bedrooms", type=int)
    bathrooms = request.args.get("bathrooms", type=int)
    min_size = request.args.get("min_size", type=int)
    keyword = request.args.get("keyword", "").strip() or None
    furnished_raw = request.args.get("furnished", "").strip().lower()
    parking_raw = request.args.get("parking", "").strip().lower()
    sort_by = request.args.get("sort_by", "price_asc")
    has_images_param = request.args.get("has_images", "true").lower()
    has_images = has_images_param not in ("false", "0", "all")
    furnished = (furnished_raw == "true") if furnished_raw in ("true", "false") else None
    parking = (parking_raw == "true") if parking_raw in ("true", "false") else None

    results = filter_properties(
        properties,
        location=location,
        category=category,
        prop_type=prop_type,
        min_price=min_price,
        max_price=max_price,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        min_size=min_size,
        furnished=furnished,
        parking=parking,
        keyword=keyword,
        has_images=has_images,
    )
    results = sort_properties(results, sort_by=sort_by, max_price=max_price, location=location)
    results.sort(key=lambda p: len(p.get("images", [])), reverse=True)
    for p in results:
        p["estimated_monthly"] = estimate_monthly_cost(int(p.get("price_jod", 0) or 0))
    return jsonify({"properties": results, "count": len(results)})


@app.route("/search")
def search_page():
    return redirect(url_for("filters_page"))


def _get_profile(user_id):
    return FinancialProfile.query.filter_by(user_id=user_id).first()


from routes.finance import finance_bp
app.register_blueprint(finance_bp, url_prefix="/finance")


@app.route("/api/chatbot", methods=["POST"])
def chatbot_api():
    if not session.get("user_id"):
        return jsonify({"reply": "Please log in to use the chatbot.", "error": "unauthorized"}), 401
    data = request.get_json() or {}
    user_msg = (data.get("message", "") or "").strip()
    properties = load_properties()
    if not properties:
        return jsonify({"reply": "Your properties database is empty or missing. Make sure data/properties.json exists."})

    bedrooms = parse_bedrooms_from_text(user_msg)
    bedrooms_max = None
    if parse_studio_from_text(user_msg):
        bedrooms = None
        bedrooms_max = 1
    category, prop_type = parse_category_type_from_text(user_msg)
    _, max_price = parse_budget_from_text(user_msg)
    if max_price is None and parse_affordable_from_text(user_msg):
        max_price = parse_affordable_from_text(user_msg)
    location = parse_location_from_text(user_msg, properties)
    user_lower = user_msg.lower()
    if ("house" in user_lower or "home" in user_lower) and category is None:
        category = "residential"
        if location and prop_type is None:
            prop_type = None
    keyword = None
    if parse_garden_from_text(user_msg):
        keyword = "garden"
    elif parse_cultural_from_text(user_msg):
        keyword = parse_cultural_from_text(user_msg)
    else:
        prefs = ["balcony", "smart", "parking", "elevator", "security", "view", "modern", "new"]
        if any(k in user_lower for k in prefs):
            keyword = user_msg

    matches = filter_properties(
        properties,
        location=location,
        category=category,
        prop_type=prop_type,
        max_price=max_price,
        bedrooms=bedrooms,
        bedrooms_max=bedrooms_max,
        keyword=keyword,
        has_images=True,
    )
    if not matches:
        if bedrooms is not None or bedrooms_max is not None:
            matches = filter_properties(
                properties,
                location=location,
                category=category,
                prop_type=prop_type,
                max_price=max_price,
                bedrooms=None,
                bedrooms_max=None,
                keyword=keyword,
                has_images=True,
            )
    if not matches and prop_type:
        matches = filter_properties(
            properties,
            location=location,
            category=category,
            prop_type=None,
            max_price=max_price,
            bedrooms=bedrooms,
            bedrooms_max=bedrooms_max,
            keyword=keyword,
            has_images=True,
        )
    if not matches:
        matches = filter_properties(
            properties,
            location=location,
            category=category,
            prop_type=prop_type,
            max_price=max_price,
            bedrooms=bedrooms,
            bedrooms_max=bedrooms_max,
            keyword=keyword,
            has_images=False,
        )

    if matches:
        matches = sort_properties(matches, sort_by="best_match", max_price=max_price, location=location)
        matches.sort(key=lambda x: len(x.get("images", [])), reverse=True)
    matches = matches[:3]
    max_monthly = None
    if session.get("user_id"):
        profile = _get_profile(session["user_id"])
        if profile and profile.total_income:
            max_monthly = profile.total_income * 0.35
    reply = format_property_suggestions(matches, limit=3, max_monthly=max_monthly)
    return jsonify({"reply": reply})

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port)
