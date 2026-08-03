"""Monthly report: a summary of spending, budget adherence and nutrition for a
given month, plus a self-contained printable HTML export.
"""
from calendar import monthrange
from datetime import date

from sqlmodel import Session, select

from backend.models import (
    BudgetTarget, Category, FoodLog, Income, NutrientGoals, Transaction,
)


def monthly_report(session: Session, year: int, month: int) -> dict:
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    txns = session.exec(select(Transaction).where(Transaction.date >= start, Transaction.date <= end)).all()
    incs = session.exec(select(Income).where(Income.date >= start, Income.date <= end)).all()
    foods = session.exec(select(FoodLog).where(FoodLog.date >= start, FoodLog.date <= end)).all()
    cats = {c.id: c.name for c in session.exec(select(Category)).all()}
    budgets = session.exec(select(BudgetTarget)).all()
    goals = session.exec(select(NutrientGoals)).first()

    total_spent = sum(t.amount for t in txns)
    total_income = sum(i.amount for i in incs)

    by_cat = {}
    for t in txns:
        name = cats.get(t.category_id, "Uncategorized")
        by_cat[name] = by_cat.get(name, 0) + t.amount
    by_cat = dict(sorted(by_cat.items(), key=lambda kv: -kv[1]))

    merchants = {}
    for t in txns:
        if t.merchant:
            merchants[t.merchant] = merchants.get(t.merchant, 0) + t.amount
    top_merchants = [(m, round(a, 2)) for m, a in sorted(merchants.items(), key=lambda kv: -kv[1])[:5]]

    overall_budget = next((b.monthly_amount for b in budgets if b.category_id is None), None)

    days_logged = len({f.date for f in foods if f.calories})

    def avg(field):
        total = sum(getattr(f, field) or 0 for f in foods)
        return round(total / days_logged, 1) if days_logged else 0

    return {
        "year": year, "month": month,
        "start": start, "end": end,
        "total_spent": round(total_spent, 2),
        "total_income": round(total_income, 2),
        "net": round(total_income - total_spent, 2),
        "transaction_count": len(txns),
        "by_category": {k: round(v, 2) for k, v in by_cat.items()},
        "top_merchants": top_merchants,
        "overall_budget": overall_budget,
        "over_under_budget": round(total_spent - overall_budget, 2) if overall_budget else None,
        "nutrition": {
            "days_logged": days_logged,
            "avg_calories": avg("calories"),
            "avg_protein": avg("protein_g"),
            "avg_carbs": avg("carbs_g"),
            "avg_fat": avg("fat_g"),
        },
        "goals": {
            "calories": goals.calories if goals else None,
            "protein_g": goals.protein_g if goals else None,
        },
    }


def report_html(data: dict, currency: str = "£") -> str:
    """A self-contained, printable HTML document for the given report dict."""
    m = date(data["year"], data["month"], 1).strftime("%B %Y")
    c = currency

    def money(v):
        return f"{c}{v:,.2f}"

    cat_rows = "".join(
        f"<tr><td>{name}</td><td class='r'>{money(amt)}</td></tr>"
        for name, amt in data["by_category"].items()
    ) or "<tr><td colspan='2'>No spending recorded.</td></tr>"
    merch_rows = "".join(
        f"<tr><td>{name}</td><td class='r'>{money(amt)}</td></tr>"
        for name, amt in data["top_merchants"]
    ) or "<tr><td colspan='2'>—</td></tr>"

    n = data["nutrition"]
    budget_line = ""
    if data["overall_budget"] is not None:
        ou = data["over_under_budget"]
        state = f"{money(abs(ou))} {'over' if ou > 0 else 'under'} budget"
        budget_line = f"<p>Budget {money(data['overall_budget'])} — <b>{state}</b>.</p>"

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Balance report — {m}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 0; }}
  h2 {{ font-size: 1.1rem; margin-top: 1.6rem; border-bottom: 2px solid #eee; padding-bottom: .3rem; }}
  .sub {{ color: #777; margin-top: .2rem; }}
  .kpis {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }}
  .kpi {{ flex: 1; min-width: 140px; border: 1px solid #eee; border-radius: 10px; padding: .8rem 1rem; }}
  .kpi .v {{ font-size: 1.4rem; font-weight: 700; }}
  .kpi .l {{ color: #777; font-size: .8rem; text-transform: uppercase; letter-spacing: .03em; }}
  table {{ width: 100%; border-collapse: collapse; margin: .5rem 0; }}
  td {{ padding: .35rem .2rem; border-bottom: 1px solid #f0f0f0; }}
  td.r {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .neg {{ color: #c0392b; }} .pos {{ color: #27ae60; }}
</style></head><body>
<h1>Balance — Monthly Report</h1>
<p class="sub">{m}</p>
<div class="kpis">
  <div class="kpi"><div class="l">Income</div><div class="v pos">{money(data['total_income'])}</div></div>
  <div class="kpi"><div class="l">Spent</div><div class="v neg">{money(data['total_spent'])}</div></div>
  <div class="kpi"><div class="l">Net</div><div class="v {'pos' if data['net'] >= 0 else 'neg'}">{money(data['net'])}</div></div>
</div>
{budget_line}
<h2>Spending by category</h2>
<table>{cat_rows}</table>
<h2>Top merchants</h2>
<table>{merch_rows}</table>
<h2>Nutrition</h2>
<p>{n['days_logged']} day(s) logged. Daily averages:
  <b>{n['avg_calories']:,.0f} kcal</b>
  (goal {data['goals']['calories'] or '—'}),
  protein {n['avg_protein']:,.0f} g, carbs {n['avg_carbs']:,.0f} g, fat {n['avg_fat']:,.0f} g.</p>
<p class="sub">Generated by Balance. {data['transaction_count']} transactions in {m}.</p>
</body></html>"""
