"""Finance blueprint: dashboard, property plan, affordability, saved plans."""
import json
import os
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app

from models import db, FinancialProfile, PropertyFinanceScenario, SavedPlan
from finance import (
    mortgage_monthly_payment,
    affordability_dti,
    savings_plan,
    equity_after_years,
)

finance_bp = Blueprint("finance", __name__, template_folder="../templates")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            session["next"] = request.url
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def load_properties():
    return getattr(current_app, "load_properties", lambda: [])()


def _get_profile(user_id):
    return FinancialProfile.query.filter_by(user_id=user_id).first()


def _scenario_presets(price):
    """Conservative: 30% down, 20y. Balanced: 20% down, 25y. Aggressive: 10% down, 30y."""
    return {
        "conservative": {"down_pct": 30, "years": 20},
        "balanced": {"down_pct": 20, "years": 25},
        "aggressive": {"down_pct": 10, "years": 30},
    }


@finance_bp.route("/")
@login_required
def dashboard():
    user_id = session["user_id"]
    profile = _get_profile(user_id)
    scenarios = PropertyFinanceScenario.query.filter_by(user_id=user_id).order_by(
        PropertyFinanceScenario.created_at.desc()
    ).limit(10).all()
    saved = SavedPlan.query.filter_by(user_id=user_id).order_by(SavedPlan.created_at.desc()).limit(10).all()

    # Affordability score and budget range (from profile)
    affordability = None
    if profile and profile.total_income and profile.monthly_expenses is not None:
        capacity = profile.savings_capacity()
        # Suggested max monthly = 35% of income
        max_monthly = profile.total_income * 0.35
        affordability = {
            "score": "complete" if profile.monthly_income else "incomplete",
            "max_monthly": round(max_monthly, 0),
            "savings_capacity": round(capacity, 0),
        }

    return render_template(
        "finance/dashboard.html",
        profile=profile,
        scenarios=scenarios,
        saved_plans=saved,
        affordability=affordability,
    )


@finance_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session["user_id"]
    profile = _get_profile(user_id) or FinancialProfile(user_id=user_id)
    if request.method == "POST":
        profile.monthly_income = max(0, float(request.form.get("monthly_income") or 0))
        profile.other_income = max(0, float(request.form.get("other_income") or 0))
        profile.monthly_expenses = max(0, float(request.form.get("monthly_expenses") or 0))
        profile.savings = max(0, float(request.form.get("savings") or 0))
        profile.existing_debt = max(0, float(request.form.get("existing_debt") or 0))
        profile.risk_tolerance = request.form.get("risk_tolerance") or "balanced"
        if not profile.id:
            db.session.add(profile)
        db.session.commit()
        flash("Financial profile saved.", "success")
        return redirect(url_for("finance.dashboard"))
    return render_template("finance/profile.html", profile=profile)


@finance_bp.route("/property/<property_id>")
@login_required
def property_plan(property_id):
    properties = load_properties()
    prop = next((p for p in properties if str(p.get("id")) == str(property_id)), None)
    if not prop:
        flash("Property not found.", "error")
        return redirect(url_for("finance.dashboard"))
    price = float(prop.get("price_jod", 0) or 0)
    profile = _get_profile(session["user_id"])
    presets = _scenario_presets(price)
    return render_template(
        "finance/property_plan.html",
        property=prop,
        property_price=price,
        profile=profile,
        presets=presets,
    )


@finance_bp.route("/property/<property_id>/save", methods=["POST"])
@login_required
def property_save_scenario(property_id):
    properties = load_properties()
    prop = next((p for p in properties if str(p.get("id")) == str(property_id)), None)
    if not prop:
        return redirect(url_for("finance.dashboard"))
    user_id = session["user_id"]
    price = float(prop.get("price_jod", 0) or 0)
    down = max(0, float(request.form.get("down_payment", 0) or 0))
    loan_amount = max(0, price - down)
    years = max(1, min(40, int(request.form.get("loan_years", 25) or 25)))
    rate = max(0, min(30, float(request.form.get("interest_rate", 7.5) or 7.5)))
    scenario_type = request.form.get("scenario_type") or "custom"
    name = (request.form.get("name") or "").strip() or f"{prop.get('title', 'Property')[:40]} Plan"

    monthly = mortgage_monthly_payment(loan_amount, rate, years)
    total_payment = monthly * years * 12
    profile = _get_profile(user_id)
    capacity = profile.savings_capacity() if profile else 0
    remaining = max(0, down - (profile.savings if profile else 0))
    savings_monthly_target = (remaining / (years * 12)) if years and remaining else 0
    years_to_afford = (remaining / capacity) / 12 if capacity and remaining else 0

    scenario = PropertyFinanceScenario(
        user_id=user_id,
        property_id=str(property_id),
        property_price=price,
        down_payment=down,
        loan_amount=loan_amount,
        interest_rate=rate,
        loan_years=years,
        monthly_payment=round(monthly, 2),
        total_payment=round(total_payment, 2),
        savings_monthly_target=round(savings_monthly_target, 2),
        years_to_afford=round(years_to_afford, 1),
        scenario_type=scenario_type,
    )
    db.session.add(scenario)
    db.session.commit()

    # Optionally create SavedPlan
    plan_name = request.form.get("plan_name") or name
    saved = SavedPlan(user_id=user_id, scenario_id=scenario.id, name=plan_name)
    db.session.add(saved)
    db.session.commit()
    flash("Scenario saved.", "success")
    return redirect(url_for("finance.saved_plans"))


@finance_bp.route("/scenario/<int:scenario_id>")
@login_required
def scenario_view(scenario_id):
    """View a saved scenario (read-only summary)."""
    user_id = session["user_id"]
    scenario = PropertyFinanceScenario.query.filter_by(id=scenario_id, user_id=user_id).first_or_404()
    prop = None
    if scenario.property_id:
        properties = load_properties()
        prop = next((p for p in properties if str(p.get("id")) == str(scenario.property_id)), None)
    return render_template(
        "finance/scenario_view.html",
        scenario=scenario,
        property=prop,
    )


@finance_bp.route("/saved")
@login_required
def saved_plans():
    user_id = session["user_id"]
    plans = SavedPlan.query.filter_by(user_id=user_id).order_by(SavedPlan.created_at.desc()).all()
    plans_with_scenario = sum(1 for p in plans if getattr(p, "scenario", None) is not None)
    return render_template(
        "finance/saved_plans.html",
        plans=plans,
        compare_available=(plans_with_scenario >= 1),
        need_more_plans=(plans_with_scenario < 2),
    )


@finance_bp.route("/saved/<int:plan_id>/delete", methods=["POST"])
@login_required
def saved_plan_delete(plan_id):
    plan = SavedPlan.query.get_or_404(plan_id)
    if plan.user_id != session["user_id"]:
        return "Forbidden", 403
    db.session.delete(plan)
    db.session.commit()
    flash("Plan removed.", "success")
    return redirect(url_for("finance.saved_plans"))


@finance_bp.route("/affordability")
@login_required
def affordability():
    profile = _get_profile(session["user_id"])
    return render_template("finance/affordability.html", profile=profile)


def _build_scenario_comparison_data(scenario, profile, max_monthly):
    """Build one scenario dict with all comparison fields. Uses finance engine only (no stale DB values)."""
    price = float(scenario.property_price or 0)
    loan_amt = float(scenario.loan_amount or 0)
    rate = float(scenario.interest_rate if scenario.interest_rate is not None else 7.5)
    years = int(scenario.loan_years if scenario.loan_years is not None else 25)
    # Recalculate from engine so comparison never uses stale data
    monthly = mortgage_monthly_payment(loan_amt, rate, years)
    total_repay = monthly * years * 12
    total_interest = max(0, total_repay - loan_amt)
    cost_5y = monthly * 60
    cost_10y = monthly * 120
    equity_5y = equity_after_years(price, scenario.down_payment or 0, loan_amt, rate, years, 5)
    equity_10y = equity_after_years(price, scenario.down_payment or 0, loan_amt, rate, years, 10)
    dti_result = (
        affordability_dti(profile.existing_debt or 0, monthly, profile.total_income)
        if profile and getattr(profile, "total_income", None)
        else {"dti_pct": 0, "risk": "unknown"}
    )
    afford_label = None
    if max_monthly and max_monthly > 0:
        if monthly <= max_monthly * 0.28:
            afford_label = "Within budget"
        elif monthly <= max_monthly:
            afford_label = "Stretch"
        else:
            afford_label = "Above budget"
    risk_label = dti_result.get("risk", "unknown").replace("_", " ").title()
    if risk_label == "Not Recommended":
        risk_label = "Risky"
    return {
        "id": scenario.id,
        "name": None,
        "property_price": price,
        "down_payment": float(scenario.down_payment or 0),
        "loan_amount": loan_amt,
        "interest_rate": rate,
        "loan_years": years,
        "monthly_payment": round(monthly, 2),
        "total_payment": round(total_repay, 2),
        "total_interest": round(max(0, total_interest), 2),
        "cost_5y": round(cost_5y, 0),
        "cost_10y": round(cost_10y, 0),
        "equity_5y": round(equity_5y, 0),
        "equity_10y": round(equity_10y, 0),
        "dti_pct": dti_result.get("dti_pct", 0),
        "affordability": afford_label,
        "risk_label": risk_label,
        "scenario_type": (scenario.scenario_type or "custom").title(),
    }


@finance_bp.route("/compare")
@login_required
def compare():
    """Compare multiple financial scenarios: from ?ids=1,2,3 (saved) or add-scenario UI."""
    user_id = session["user_id"]
    profile = _get_profile(user_id)
    ids_param = request.args.get("ids", "").strip()
    selected_scenarios = []
    if ids_param:
        try:
            scenario_ids = [int(x.strip()) for x in ids_param.split(",") if x.strip()][:4]
            if len(scenario_ids) < 2:
                flash("Select at least 2 scenarios to compare.", "info")
            else:
                scenarios_by_id = {
                    s.id: s
                    for s in PropertyFinanceScenario.query.filter(
                        PropertyFinanceScenario.id.in_(scenario_ids),
                        PropertyFinanceScenario.user_id == user_id,
                    ).all()
                }
                plan_names = {
                    p.scenario_id: p.name
                    for p in SavedPlan.query.filter_by(user_id=user_id).filter(
                        SavedPlan.scenario_id.in_(scenario_ids)
                    ).all()
                }
                max_monthly = (
                    round(profile.total_income * 0.35, 0)
                    if profile and getattr(profile, "total_income", None)
                    else None
                )
                for sid in scenario_ids:
                    s = scenarios_by_id.get(sid)
                    if not s:
                        continue
                    row = _build_scenario_comparison_data(s, profile, max_monthly)
                    row["name"] = plan_names.get(s.id) or f"Scenario {s.id}"
                    selected_scenarios.append(row)
                if len(selected_scenarios) < 2:
                    flash("Some scenarios could not be loaded. Save at least 2 plans to compare.", "warning")
                else:
                    # Debug: ensure comparison inputs are correct before render
                    if current_app.debug:
                        for row in selected_scenarios:
                            current_app.logger.debug(
                                "compare scenario id=%s name=%s monthly=%s total_payment=%s equity_5y=%s",
                                row.get("id"), row.get("name"), row.get("monthly_payment"),
                                row.get("total_payment"), row.get("equity_5y"),
                            )
        except (ValueError, TypeError):
            flash("Invalid scenario IDs.", "warning")

    property_id = request.args.get("property_id", "").strip() or None
    property_price = None
    prop = None
    if property_id:
        properties = load_properties()
        prop = next((p for p in properties if str(p.get("id")) == str(property_id)), None)
        if prop:
            property_price = float(prop.get("price_jod", 0) or 0)
    max_monthly = round(profile.total_income * 0.35, 0) if profile and profile.total_income else None
    return render_template(
        "finance/compare.html",
        profile=profile,
        property=prop,
        property_price=property_price,
        property_id=property_id,
        max_monthly=max_monthly,
        selected_scenarios=selected_scenarios,
    )
