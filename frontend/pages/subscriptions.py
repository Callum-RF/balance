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
)
from ..components import (
    card_box,
    card_box_accent,
    date_field,
    empty_state,
    list_row,
    page_header,
    section_header,
    segmented,
    summary_strip,
    undo_banner,
)
from ..theme import (
    AMBER,
    BORDER,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    SURFACE,
    TEXT_DIM,
)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
def subscriptions_page():
    page_header("Subscriptions", "Recurring spend and what's due next.")
    undo_container = ui.column().classes("w-full")

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
            if not sub:
                return
            snapshot = sub.model_dump(exclude={"id"})
            session.delete(sub)
            session.commit()

        def undo_delete():
            with Session(engine) as session:
                session.add(Subscription(**snapshot))
                session.commit()
            ui.notify("Restored.", type="positive")
            content.refresh()

        content.refresh()
        undo_banner(undo_container, f"Deleted {snapshot['name']}.", undo_delete)

      def open_sub(sid):
        """The whole subscription: mark a payment, pause it, edit or delete it."""
        with Session(engine) as session:
            sub = session.get(Subscription, sid)
            if not sub:
                return
            cur = sub.model_dump()
        is_inst = cur["total_payments"] is not None
        done = is_inst and cur["payments_made"] >= cur["total_payments"]

        with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
            section_header(cur["name"], subtitle=(
                "Paid off" if done else "Paused" if not cur["active"]
                else f"Payment {cur['payments_made'] + 1} of {cur['total_payments']}" if is_inst
                else "Active"))
            if cur["active"] and not done:
                def paid():
                    dialog.close()
                    mark_payment_made(sid)
                    ui.notify(f"Logged a {CUR}{cur['amount']:,.2f} payment to {cur['name']}.", type="positive")
                ui.button("Mark a payment made today", icon="check", on_click=paid).props(
                    "unelevated no-caps color=primary").classes("self-start")
                ui.label("Logs it as a transaction and moves the next payment date on.").classes(
                    "text-xs -mt-1").style(f"color:{TEXT_DIM}")
            e_name = ui.input(label="Name", value=cur["name"]).classes("w-full")
            e_amount = ui.number(label="Amount per payment", value=cur["amount"], format="%.2f").props(
                f'prefix="{CUR}"').classes("w-full")
            e_cycle = segmented("Billing cycle", {"monthly": "Monthly", "yearly": "Yearly"}, cur["billing_cycle"])
            e_next = date_field("Next payment date",
                                value=cur["next_payment_date"].isoformat() if cur["next_payment_date"] else "")
            e_cat = ui.select(category_options, value=cur["category_id"], label="Category").classes("w-full")

            def save():
                with Session(engine) as session:
                    obj = session.get(Subscription, sid)
                    if obj:
                        obj.name = e_name.value or obj.name
                        obj.amount = e_amount.value or 0
                        obj.billing_cycle = e_cycle.value
                        obj.next_payment_date = date.fromisoformat(e_next.value) if e_next.value else None
                        obj.category_id = e_cat.value
                        session.add(obj)
                        session.commit()
                dialog.close()
                ui.notify("Subscription updated.", type="positive")
                content.refresh()

            def toggle_active():
                dialog.close()
                set_sub_active(sid, not cur["active"])

            def remove():
                dialog.close()
                delete_sub(sid)

            with ui.row().classes("w-full items-center gap-1 mt-2"):
                ui.button("Delete", icon="delete_outline", on_click=remove).props("flat no-caps color=negative")
                if not is_inst:
                    ui.button("Resume" if not cur["active"] else "Pause",
                              icon="play_arrow" if not cur["active"] else "pause",
                              on_click=toggle_active).props("flat no-caps")
                ui.space()
                ui.button("Save", on_click=save).props("color=primary unelevated no-caps")
        dialog.open()

      if detected:
        with card_box_accent().classes("w-full gap-1"):
            section_header("Looks like a subscription",
                           subtitle="Charged on a regular cadence but not tracked here yet.")
            with ui.column().classes("w-full gap-0"):
                for cand in detected:
                    cadence_word = "month" if cand["cadence"] == "monthly" else "year"
                    with ui.element("div").classes("b-nudge").on(
                            "click", lambda c=cand: add_detected_subscription(c)):
                        ui.element("span").classes("dot").style(f"background:{AMBER}")
                        with ui.column().classes("b-nudge-text gap-0"):
                            ui.label(f"{cand['merchant']} · {CUR}{cand['typical_amount']:,.2f}/{cadence_word}").classes(
                                "font-semibold")
                            ui.label(f"Seen {cand['count']} times · last charged "
                                     f"{cand['last_seen'].day} {cand['last_seen']:%b}").classes(
                                "text-xs").style(f"color:{TEXT_DIM}")
                        with ui.element("div").classes("b-nudge-cta"):
                            ui.label("Track")
                            ui.icon("chevron_right")

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
            empty_state("No subscriptions yet -- add one above, or track one it has spotted.", "autorenew")

      def sub_row(sub):
        is_inst = sub.total_payments is not None
        done = is_inst and sub.payments_made >= sub.total_payments
        icon, color = (("check_circle", EMERALD) if done else ("pause_circle", TEXT_DIM) if not sub.active
                       else ("receipt_long", AMBER) if is_inst else ("autorenew", INDIGO))
        per = "month" if sub.billing_cycle == "monthly" else "year"
        bits = []
        if done:
            bits.append("Paid off")
        elif not sub.active:
            bits.append("Paused")
        elif is_inst:
            left = max(sub.total_payments - sub.payments_made, 0)
            bits.append(f"{sub.payments_made} of {sub.total_payments} paid · {CUR}{left * sub.amount:,.2f} left")
        if sub.active and sub.next_payment_date:
            nd, days = sub.next_payment_date, (sub.next_payment_date - date.today()).days
            bits.append("overdue" if days < 0 else "due today" if days == 0 else "due tomorrow" if days == 1
                        else f"due {nd.day} {nd:%b}")
        list_row(icon, color, sub.name, " · ".join(bits) or f"every {per}",
                 f"{CUR}{sub.amount:,.2f}/{'mo' if per == 'month' else 'yr'}",
                 lambda _, sid=sub.id: open_sub(sid))

      live = sorted([x for x in subs if x.active], key=lambda x: (x.next_payment_date or date.max, x.name.lower()))
      rest = [x for x in subs if not x.active]
      for title, group in (("Active", live), ("Paused & paid off", rest)):
        if group:
            with ui.element("div").classes("b-day"):
                ui.label(title)
                ui.label(str(len(group)))
            with ui.column().classes(LIST_GROUP):
                for sub in group:
                    sub_row(sub)

    content()
