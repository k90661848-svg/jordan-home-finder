"""Financial calculation engine for JordanHomeFinder."""
from __future__ import annotations
from typing import Any


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def mortgage_monthly_payment(principal: float, annual_rate_pct: float, years: int) -> float:
    """Monthly P+I payment. principal in currency, rate 0-30, years 5-40."""
    if principal <= 0 or years <= 0:
        return 0.0
    r = clamp(annual_rate_pct / 100 / 12, 0, 0.03)
    n = years * 12
    if r < 1e-10:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def total_monthly_housing_cost(
    principal: float,
    annual_rate_pct: float,
    years: int,
    property_tax_annual: float = 0,
    insurance_annual: float = 0,
    hoa_monthly: float = 0,
    pmi_monthly: float = 0,
) -> dict[str, float]:
    """Full monthly housing cost breakdown."""
    pi = mortgage_monthly_payment(principal, annual_rate_pct, years)
    tax_m = property_tax_annual / 12
    ins_m = insurance_annual / 12
    total = pi + tax_m + ins_m + hoa_monthly + pmi_monthly
    return {
        "principal_interest": pi,
        "property_tax": tax_m,
        "insurance": ins_m,
        "hoa": hoa_monthly,
        "pmi": pmi_monthly,
        "total": total,
    }


def amortization_schedule(
    principal: float,
    annual_rate_pct: float,
    years: int,
    max_months: int | None = None,
) -> list[dict[str, Any]]:
    """Monthly amortization schedule. Each row: month, balance, principal, interest, payment."""
    if principal <= 0 or years <= 0:
        return []
    r = annual_rate_pct / 100 / 12
    n = years * 12
    pmt = mortgage_monthly_payment(principal, annual_rate_pct, years)
    schedule = []
    bal = principal
    month = 0
    limit = (max_months or n) + 1
    while month < limit and bal > 0.01:
        month += 1
        interest = bal * r
        princ_pay = min(pmt - interest, bal)
        bal = max(0, bal - princ_pay)
        schedule.append({
            "month": month,
            "balance": round(bal, 2),
            "principal_paid": round(princ_pay, 2),
            "interest_paid": round(interest, 2),
            "payment": round(pmt, 2),
        })
    return schedule


def balance_after_months(principal: float, annual_rate_pct: float, years: int, months: int) -> float:
    """Remaining loan balance after N months. Returns 0 if months >= full term."""
    principal = float(principal or 0)
    annual_rate_pct = float(annual_rate_pct or 0)
    years = int(years or 0)
    months = int(months or 0)
    if principal <= 0 or years <= 0 or months <= 0:
        return principal
    schedule = amortization_schedule(principal, annual_rate_pct, years, max_months=months)
    if not schedule:
        return principal
    return schedule[-1]["balance"]


def equity_after_years(
    property_price: float,
    down_payment: float,
    loan_amount: float,
    annual_rate_pct: float,
    years: int,
    after_years: int,
) -> float:
    """Equity = property value minus remaining balance after N years."""
    property_price = float(property_price or 0)
    loan_amount = float(loan_amount or 0)
    annual_rate_pct = float(annual_rate_pct or 0)
    years = int(years or 25)
    after_years = int(after_years or 0)
    if property_price <= 0 or loan_amount <= 0 or years <= 0:
        return max(0, property_price - loan_amount) if after_years >= years else property_price * 0
    months = after_years * 12
    bal = balance_after_months(loan_amount, annual_rate_pct, years, months)
    return max(0, property_price - bal)


def affordability_dti(
    monthly_debt: float,
    monthly_payment: float,
    monthly_income: float,
) -> dict[str, Any]:
    """Debt-to-income: (Debts + Monthly Payment) / Monthly Income. Returns risk level and recommendation."""
    if monthly_income <= 0:
        return {"dti_pct": 0, "risk": "unknown", "recommendation": "Enter your income in the financial profile."}
    dti = ((monthly_debt or 0) + (monthly_payment or 0)) / monthly_income * 100
    if dti < 30:
        risk, rec = "safe", "Your debt-to-income is in a safe range."
    elif dti < 40:
        risk, rec = "moderate", "Your DTI is moderate. Consider a larger down payment to reduce the monthly burden."
    elif dti < 50:
        risk, rec = "risky", "Your DTI is high. We recommend a lower budget or longer savings timeline."
    else:
        risk, rec = "not_recommended", "DTI is too high for this payment. Lower the loan amount or increase your down payment."
    return {"dti_pct": round(dti, 1), "risk": risk, "recommendation": rec}


def affordability_metrics(
    monthly_housing: float,
    monthly_income: float,
    monthly_expenses: float,
) -> dict[str, Any]:
    """Housing ratio, savings capacity, and soft recommendations."""
    if monthly_income <= 0:
        return {
            "housing_ratio": 0,
            "savings_capacity": 0,
            "recommendation": "Enter your income in the profile to see affordability.",
        }
    ratio = (monthly_housing / monthly_income) * 100
    savings_cap = monthly_income - monthly_expenses
    rec = None
    if ratio > 35:
        rec = "Monthly housing cost is above 35% of income. Consider a lower price or longer term."
    elif ratio > 28:
        rec = "Housing cost is in the upper range of typical budgets (28–35%)."
    else:
        rec = "Monthly housing cost is within common affordability guidelines."
    if savings_cap < monthly_housing and savings_cap > 0:
        rec = (rec or "") + " Your savings capacity is below the housing payment."
    return {
        "housing_ratio": round(ratio, 1),
        "savings_capacity": round(savings_cap, 2),
        "recommendation": rec or "",
    }


def savings_plan(
    target_down_payment: float,
    closing_costs: float,
    buffer: float,
    existing_savings: float,
    monthly_savings_capacity: float,
    target_months: int | None = None,
) -> dict[str, Any]:
    """Months to goal or required monthly savings for target date."""
    target_total = max(0, target_down_payment + closing_costs + buffer - existing_savings)
    if monthly_savings_capacity <= 0:
        return {
            "months_to_goal": None,
            "required_monthly": None,
            "target_total": target_total,
            "message": "Increase income or reduce expenses to build savings capacity.",
        }
    months = max(0, target_total / monthly_savings_capacity)
    req_monthly = None
    if target_months and target_months > 0 and target_total > 0:
        req_monthly = target_total / target_months
    return {
        "months_to_goal": round(months, 1),
        "required_monthly": round(req_monthly, 2) if req_monthly else None,
        "target_total": target_total,
        "message": f"Est. {months:.0f} months to reach goal at current savings rate."
        if months < 1000
        else "Goal may take many years at current savings rate.",
    }


def rent_vs_buy(
    home_price: float,
    down_payment: float,
    loan_term_years: int,
    interest_rate: float,
    property_tax_annual: float,
    insurance_annual: float,
    hoa_monthly: float,
    pmi_monthly: float,
    closing_costs: float,
    maintenance_pct: float,
    monthly_rent: float,
    years_horizon: int,
    appreciation_rate: float,
    rent_growth_rate: float,
    investment_return: float,
) -> dict[str, Any]:
    """5–10 year rent vs buy comparison. Returns cumulative costs over years."""
    principal = home_price - down_payment
    pmt = mortgage_monthly_payment(principal, interest_rate, loan_term_years)
    tax_m = property_tax_annual / 12
    ins_m = insurance_annual / 12
    maint_annual = home_price * (maintenance_pct / 100)
    maint_m = maint_annual / 12

    buy_monthly = pmt + tax_m + ins_m + hoa_monthly + pmi_monthly + maint_m
    buy_upfront = down_payment + closing_costs

    rent_cumulative = 0.0
    buy_cumulative = float(buy_upfront)
    rent_vals = [0.0]
    buy_vals = [float(buy_upfront)]
    rent = monthly_rent

    for y in range(1, years_horizon + 1):
        for _ in range(12):
            rent_cumulative += rent
            buy_cumulative += buy_monthly
            rent *= 1 + rent_growth_rate / 100 / 12
        rent_vals.append(round(rent_cumulative, 2))
        buy_vals.append(round(buy_cumulative, 2))

    return {
        "years": list(range(years_horizon + 1)),
        "rent_cumulative": rent_vals,
        "buy_cumulative": buy_vals,
        "rent_total": round(rent_cumulative, 2),
        "buy_total": round(buy_cumulative, 2),
        "buy_upfront": buy_upfront,
    }


def stress_test(
    principal: float,
    annual_rate_pct: float,
    years: int,
    property_tax_annual: float,
    insurance_annual: float,
    hoa_monthly: float,
    pmi_monthly: float,
    monthly_income: float,
) -> dict[str, Any]:
    """+1%, +2% rate; -10% income scenarios."""
    base = total_monthly_housing_cost(
        principal, annual_rate_pct, years,
        property_tax_annual, insurance_annual, hoa_monthly, pmi_monthly,
    )
    plus1 = total_monthly_housing_cost(
        principal, annual_rate_pct + 1, years,
        property_tax_annual, insurance_annual, hoa_monthly, pmi_monthly,
    )
    plus2 = total_monthly_housing_cost(
        principal, annual_rate_pct + 2, years,
        property_tax_annual, insurance_annual, hoa_monthly, pmi_monthly,
    )
    income_90 = monthly_income * 0.9 if monthly_income and monthly_income > 0 else 0
    ratio_base = (base["total"] / monthly_income * 100) if monthly_income else 0
    ratio_90 = (base["total"] / income_90 * 100) if income_90 else 0
    return {
        "base": base,
        "rate_plus_1": plus1,
        "rate_plus_2": plus2,
        "income_drop_10_ratio": round(ratio_90, 1),
        "base_ratio": round(ratio_base, 1),
    }


def recommended_max_price(
    monthly_income: float,
    monthly_expenses: float,
    max_housing_ratio_pct: float = 35,
    annual_rate_pct: float = 7.5,
    years: int = 25,
    down_pct: float = 20,
    tax_insurance_hoa_pmi_monthly: float = 0,
) -> float:
    """Max home price given income/expenses and housing ratio cap."""
    if monthly_income <= 0:
        return 0
    max_housing = monthly_income * (max_housing_ratio_pct / 100)
    max_pi = max(0, max_housing - tax_insurance_hoa_pmi_monthly)
    if max_pi <= 0:
        return 0
    r = annual_rate_pct / 100 / 12
    n = years * 12
    if r < 1e-10:
        loan_max = max_pi * n
    else:
        loan_max = max_pi * ((1 + r) ** n - 1) / (r * (1 + r) ** n)
    return loan_max / (1 - down_pct / 100) if down_pct < 100 else 0
