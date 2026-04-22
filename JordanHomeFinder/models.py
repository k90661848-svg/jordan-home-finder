"""SQLAlchemy models for JordanHomeFinder."""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    financial_profile = db.relationship("FinancialProfile", backref="user", uselist=False, cascade="all, delete-orphan")
    property_scenarios = db.relationship("PropertyFinanceScenario", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    saved_plans = db.relationship("SavedPlan", backref="user", lazy="dynamic", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class FinancialProfile(db.Model):
    __tablename__ = "financial_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    monthly_income = db.Column(db.Float, default=0)
    other_income = db.Column(db.Float, default=0)
    monthly_expenses = db.Column(db.Float, default=0)
    savings = db.Column(db.Float, default=0)
    existing_debt = db.Column(db.Float, default=0)
    risk_tolerance = db.Column(db.String(32), default="balanced")  # conservative, balanced, aggressive
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def total_income(self):
        return (self.monthly_income or 0) + (self.other_income or 0)

    def savings_capacity(self):
        return max(0, self.total_income - (self.monthly_expenses or 0))


class PropertyFinanceScenario(db.Model):
    __tablename__ = "property_finance_scenarios"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    property_id = db.Column(db.String(32), nullable=True)
    property_price = db.Column(db.Float, nullable=False)
    down_payment = db.Column(db.Float, nullable=False)
    loan_amount = db.Column(db.Float, nullable=False)
    interest_rate = db.Column(db.Float, default=7.5)
    loan_years = db.Column(db.Integer, default=25)
    monthly_payment = db.Column(db.Float, default=0)
    total_payment = db.Column(db.Float, default=0)
    savings_monthly_target = db.Column(db.Float, default=0)
    years_to_afford = db.Column(db.Float, default=0)
    scenario_type = db.Column(db.String(32), default="custom")  # conservative, aggressive, custom
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    saved_plans = db.relationship("SavedPlan", backref="scenario", lazy="dynamic", cascade="all, delete-orphan")


class SavedPlan(db.Model):
    __tablename__ = "saved_plans"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    scenario_id = db.Column(db.Integer, db.ForeignKey("property_finance_scenarios.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ContactSubmission(db.Model):
    """Stores contact form submissions when email is not configured."""
    __tablename__ = "contact_submissions"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(64), nullable=False)
    message = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
