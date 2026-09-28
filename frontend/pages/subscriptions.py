"""The subscriptions page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    Category,
    Subscription,
    Transaction,
)

from ..common import (
    CUR,
    NON_SUBSCRIPTION_CATEGORIES,
    _category_label,
    detect_recurring_transactions,
    format_date_header,
)
from ..components import (
    badge,
    card_box,
    date_field,
    empty_state,
    page_header,
    section_header,
    segmented,
    summary_strip,
)
from ..theme import (
    AMBER,
    EMERALD,
    INDIGO,
    SURFACE_2,
    TEXT,
    TEXT_DIM,
)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
def subscriptions_page():
    page_header("Subscriptions", "Recurring spend and what's due next.", icon="autorenew")

    @ui.refreshable
    def content():
      with Session(engine) as session:
        subs = session.exec(select(Subscription)).all()
        categories = session.exec(select(Category)).all()
      category_options = {c.id: _category_label(c, categories) for c in categories}
      default_sub_category = next((c.id for c in categories if c.name == "Subscriptions"), None)
      active_subs = [s for s in subs if s.active]
      monthly_total = sum(s.amount if s.billing_cycle == "monthly" else s.amount / 12 for s in active_subs)
      installments = [s for s in active_subs if s.total_payments]
      remaining_owed = sum(s.amount * max(s.total_payments - s.payments_made, 0) for s in installments)

      summary_strip([
          ("Active subs", str(len(active_subs)), INDIGO),
          ("Monthly total", f"{CUR}{monthly_total:,.2f}", EMERALD),
          ("Owed on installments", f"{CUR}{remaining_owed:,.2f}", AMBER) if installments else None,
      ])

      # --- detected recurring payments not yet tracked as subscriptions ---
      with Session(engine) as session:
        all_transactions = session.exec(select(Transaction)).all()
      everyday_ids = frozenset(c.id for c in categories if c.name in NON_SUBSCRIPTION_CATEGORIES)
      detected = detect_recurring_transactions(all_transactions, [s.name for s in subs], everyday_ids)

      def add_detected_subscription(cand):
        with Session(engine) as session:
            session.add(Subscription(
                name=cand["merchant"],
                amount=cand["typical_amount"],
                billing_cycle=cand["cadence"],
                category_id=cand["category_id"],
                payments_made=0,
            ))
            session.commit()
        ui.notify(f"Added {cand['merchant']} as a subscription.", type="positive")
        content.refresh()

      def mark_payment_made(sid):
        with Session(engine) as session:
            sub = session.get(Subscription, sid)
            if not sub:
                return
            category_id = sub.category_id
            if category_id is None:
                fallback = session.exec(select(Category).where(Category.name == "Subscriptions")).first()
                category_id = fallback.id if fallback else None
            session.add(Transaction(
                date=date.today(), amount=sub.amount, merchant=sub.name,
                category_id=category_id, payment_method="Card",
                notes=f"Subscription payment ({sub.billing_cycle})",
                is_subscription_payment=True,
            ))
            if sub.total_payments is not None:
                sub.payments_made += 1
                if sub.payments_made >= sub.total_payments:
                    sub.active = False
            if sub.next_payment_date and sub.active:
                if sub.billing_cycle == "monthly":
                    month = sub.next_payment_date.month + 1
                    year = sub.next_payment_date.year + (1 if month > 12 else 0)
                    month = month if month <= 12 else 1
                    day = min(sub.next_payment_date.day, 28)
                    sub.next_payment_date = date(year, month, day)
                else:
                    sub.next_payment_date = date(sub.next_payment_date.year + 1, sub.next_payment_date.month, sub.next_payment_date.day)
            session.add(sub)
            session.commit()
        content.refresh()

      def set_sub_active(sid, active):
        with Session(engine) as session:
            sub = session.get(Subscription, sid)
            if sub:
                sub.active = active
                session.add(sub)
                session.commit()
        content.refresh()

      def delete_sub(sid):
        with Session(engine) as session:
            sub = session.get(Subscription, sid)
            if sub:
                session.delete(sub)
                session.commit()
        content.refresh()

      if detected:
        with card_box().classes("w-full"):
            section_header(
                "Possible recurring payments", icon="auto_awesome", icon_color=AMBER,
                subtitle="Merchants you're charged by on a regular cadence but haven't set up as a subscription yet.",
            )
            for cand in detected:
                cadence_word = "month" if cand["cadence"] == "monthly" else "year"
                with card_box().classes("w-full py-3 flex-row items-center justify-between gap-3").style(f"background:{SURFACE_2}"):
                    with ui.column().classes("gap-0"):
                        ui.label(f"{cand['merchant']} · {CUR}{cand['typical_amount']:,.2f}/{cadence_word}").classes("font-semibold")
                        ui.label(
                            f"Seen {cand['count']} times · {cand['cadence']} · last {format_date_header(cand['last_seen']).lower()}"
                        ).classes("text-xs").style(f"color:{TEXT_DIM}")
                    ui.button(
                        "Add as subscription", icon="add",
                        on_click=lambda _, c=cand: add_detected_subscription(c),
                    ).props("flat dense no-caps color=primary")

      with ui.expansion("Add subscription", icon="add").classes("w-full"):
        with ui.column().classes("gap-1 max-w-xl w-full"):
            name_input = ui.input(label="Name (e.g. Amazon Prime, or 'Sofa installments')").props("dense").classes("w-full")
            # Caption above (not a floating label): the big text-2xl value would
            # otherwise overlap a floating field label.
            ui.label("Amount per payment").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
            amount_input = ui.number(placeholder="0.00", format="%.2f").props(
                f'prefix="{CUR}" input-class="text-2xl font-bold"'
            ).classes("w-full")
            cycle_select = segmented("Billing cycle", {"monthly": "Monthly", "yearly": "Yearly"}, "monthly")
            with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1 mt-2"):
                next_date_input = date_field("Next payment date")
                category_select = ui.select(category_options, value=default_sub_category, label="Category").props("dense options-dense").classes("w-full")

            installment_toggle = ui.switch("Fixed-term (installment plan, not ongoing)", value=False).props("dense color=primary").classes("mt-2")
            ui.label(
                "e.g. an item paid off over 5 monthly payments -- tracks progress and stops "
                "counting once it's paid off, instead of continuing forever like a real subscription."
            ).classes("text-xs -mt-1 mb-1").style(f"color:{TEXT_DIM}")
            total_payments_input = ui.number(label="Total number of payments", value=3, format="%.0f").props("dense").classes("w-40")
            total_payments_input.set_visibility(False)
            installment_toggle.on_value_change(lambda e: total_payments_input.set_visibility(e.value))

            def add_sub():
                with Session(engine) as session:
                    sub = Subscription(
                        name=name_input.value or "Unnamed",
                        amount=amount_input.value or 0,
                        billing_cycle=cycle_select.value,
                        next_payment_date=date.fromisoformat(next_date_input.value) if next_date_input.value else None,
                        category_id=category_select.value,
                        total_payments=int(total_payments_input.value) if installment_toggle.value and total_payments_input.value else None,
                        payments_made=0,
                    )
                    session.add(sub)
                    session.commit()
                ui.notify("Subscription added.", type="positive")
                content.refresh()

            ui.button("Add subscription", on_click=add_sub).props("color=primary unelevated")

      if not subs:
        with card_box().classes("w-full"):
            empty_state("No subscriptions yet -- add one above, or check \"Possible recurring payments\" if you have regular charges.", "autorenew")

      for s in subs:
        is_installment = s.total_payments is not None
        is_completed = is_installment and s.payments_made >= s.total_payments
        row_icon = "check_circle" if is_completed else ("pause_circle" if not s.active else ("receipt_long" if is_installment else "autorenew"))
        row_color = EMERALD if is_completed else (TEXT_DIM if not s.active else (AMBER if is_installment else INDIGO))
        with card_box().classes("w-full py-3 flex-row items-center justify-between gap-2 no-wrap"):
            with ui.row().classes("flex-1 items-center gap-3 min-w-0 no-wrap"):
                ui.icon(row_icon).classes("text-2xl shrink-0").style(f"color:{row_color}")
                with ui.column().classes("gap-0 min-w-0"):
                    with ui.row().classes("items-center gap-2 min-w-0 no-wrap w-full"):
                        ui.label(s.name).classes("font-semibold truncate" + ("" if s.active else " line-through")).style(
                            f"color:{TEXT if s.active else TEXT_DIM}"
                        )
                        if is_completed:
                            badge("Paid off", EMERALD)
                        elif not s.active:
                            badge("Paused", TEXT_DIM)
                        elif is_installment:
                            badge("Installment", AMBER)
                    ui.label(f"{CUR}{s.amount:,.2f} / {s.billing_cycle}").classes("text-xs").style(f"color:{TEXT_DIM}")
                    if is_installment:
                        remaining = max(s.total_payments - s.payments_made, 0)
                        ui.label(f"Payment {min(s.payments_made + 1, s.total_payments)} of {s.total_payments} · {CUR}{remaining * s.amount:,.2f} left").classes("text-xs").style(f"color:{TEXT_DIM}")
            with ui.row().classes("items-center gap-1 shrink-0 no-wrap"):
                if s.active and not is_completed:
                    ui.button("Mark paid", icon="check", on_click=lambda _, sid=s.id: mark_payment_made(sid)).props("flat dense no-caps color=primary")
                if not is_installment:
                    ui.switch(value=s.active, on_change=lambda e, sid=s.id: set_sub_active(sid, e.value)).props(
                        "color=primary dense"
                    ).tooltip("Active / Paused")
                ui.button(icon="delete", on_click=lambda _, sid=s.id: delete_sub(sid)).props("flat round dense color=red")

    content()
