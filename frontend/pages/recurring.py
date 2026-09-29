"""Recurring: everything that repeats -- subscriptions, and scheduled bills and
income -- as one list, with what's due next."""
from datetime import date, timedelta

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    INCOME_SOURCES,
    Category,
    ScheduledTransaction,
    Subscription,
    Transaction,
)

from ..common import (
    CUR,
    NON_SUBSCRIPTION_CATEGORIES,
    _category_label,
    detect_recurring_transactions,
    format_date_header,
    load_enabled_modules,
    module_enabled,
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
    setting_row,
    sheet_dialog,
    summary_strip,
    undo_banner,
)
from ..theme import (
    AMBER,
    BORDER,
    EMERALD,
    INDIGO,
    LIST_GROUP,
    RED,
    SURFACE,
    TEXT_DIM,
)


def _monthly(amount, cadence):
    return amount * 52 / 12 if cadence == "weekly" else amount / 12 if cadence == "yearly" else amount


def _due_text(d):
    days = (d - date.today()).days
    return ("overdue" if days < 0 else "due today" if days == 0 else "due tomorrow" if days == 1
            else f"due {d.day} {d:%b}")


def recurring_page(tab=None):
    """`tab` is accepted for the old /subscriptions and /scheduled links."""
    from backend.cashflow import cashflow_summary
    from backend.recurring import post_now, skip_next

    enabled = load_enabled_modules()
    subs_on, sched_on = module_enabled("subscriptions", enabled), module_enabled("scheduled", enabled)
    if not (subs_on or sched_on):
        page_header("Recurring", "Turn on Subscriptions or Scheduled in Settings to use this page.")
        return

    adders = {"sub": {}, "sched": {}}
    with sheet_dialog("Add something that repeats") as chooser:
        with ui.column().classes(LIST_GROUP):
            if subs_on:
                with setting_row("autorenew", INDIGO, "A subscription",
                                 "Netflix, the gym, a phone contract — or something paid off in instalments",
                                 on_click=lambda: (chooser.close(), adders["sub"]["open"]())):
                    pass
            if sched_on:
                with setting_row("event_repeat", EMERALD, "A bill or income",
                                 "Rent, council tax, your salary — logged for you on the day, or waiting for a tap",
                                 on_click=lambda: (chooser.close(), adders["sched"]["open"]())):
                    pass

    def open_add():
        if subs_on and sched_on:
            chooser.open()
        else:
            adders["sub" if subs_on else "sched"]["open"]()

    page_header("Recurring", "Everything that repeats, and what's due next.", action=("Add", "add", open_add))
    undo_container = ui.column().classes("w-full")

    @ui.refreshable
    def content():
        today = date.today()
        with Session(engine) as session:
            subs = session.exec(select(Subscription)).all() if subs_on else []
            items = session.exec(select(ScheduledTransaction)).all() if sched_on else []
            categories = session.exec(select(Category)).all()
            all_tx = session.exec(select(Transaction)).all() if subs_on else []
        category_options = {c.id: _category_label(c, categories) for c in categories}
        cats_by_id = {c.id: c for c in categories}
        default_sub_category = next((c.id for c in categories if c.name == "Subscriptions"), None)

        live_subs = [s for s in subs if s.active]
        live_items = [i for i in items if i.active]
        out_month = (sum(_monthly(s.amount, s.billing_cycle) for s in live_subs)
                     + sum(_monthly(i.amount, i.cadence) for i in live_items if i.kind == "expense"))
        in_month = sum(_monthly(i.amount, i.cadence) for i in live_items if i.kind == "income")
        instalments = [s for s in live_subs if s.total_payments]
        owed = sum(s.amount * max(s.total_payments - s.payments_made, 0) for s in instalments)
        cf = cashflow_summary(days=30, today=today)
        summary_strip([
            ("Going out a month", f"{CUR}{out_month:,.0f}", RED),
            ("Coming in a month", f"{CUR}{in_month:,.0f}", EMERALD) if in_month else None,
            ("Next 30 days", f"{'+' if cf['net'] >= 0 else '−'}{CUR}{abs(cf['net']):,.0f}",
             EMERALD if cf["net"] >= 0 else AMBER, f"{CUR}{cf['out']:,.0f} out · {CUR}{cf['in']:,.0f} in"),
            ("Owed on instalments", f"{CUR}{owed:,.0f}", AMBER) if instalments else None,
        ])

        # ---------------------------------------------------------------- actions
        def add_detected(cand):
            with Session(engine) as session:
                session.add(Subscription(name=cand["merchant"], amount=cand["typical_amount"],
                                         billing_cycle=cand["cadence"], category_id=cand["category_id"],
                                         payments_made=0))
                session.commit()
            ui.notify(f"Now tracking {cand['merchant']}.", type="positive")
            content.refresh()

        def mark_paid(sid):
            with Session(engine) as session:
                sub = session.get(Subscription, sid)
                if not sub:
                    return
                category_id = sub.category_id
                if category_id is None:
                    fallback = session.exec(select(Category).where(Category.name == "Subscriptions")).first()
                    category_id = fallback.id if fallback else None
                session.add(Transaction(date=date.today(), amount=sub.amount, merchant=sub.name,
                                        category_id=category_id, payment_method="Card",
                                        notes=f"Subscription payment ({sub.billing_cycle})",
                                        is_subscription_payment=True))
                if sub.total_payments is not None:
                    sub.payments_made += 1
                    if sub.payments_made >= sub.total_payments:
                        sub.active = False
                if sub.next_payment_date and sub.active:
                    nd = sub.next_payment_date
                    if sub.billing_cycle == "monthly":
                        y, m = (nd.year + 1, 1) if nd.month == 12 else (nd.year, nd.month + 1)
                        sub.next_payment_date = date(y, m, min(nd.day, 28))
                    else:
                        sub.next_payment_date = date(nd.year + 1, nd.month, min(nd.day, 28))
                session.add(sub)
                session.commit()
            content.refresh()

        def set_active(model, oid, active):
            with Session(engine) as session:
                obj = session.get(model, oid)
                if obj:
                    obj.active = active
                    session.add(obj)
                    session.commit()
            content.refresh()

        def delete(model, oid, label_of):
            with Session(engine) as session:
                obj = session.get(model, oid)
                if not obj:
                    return
                snapshot = obj.model_dump(exclude={"id"})
                session.delete(obj)
                session.commit()

            def undo():
                with Session(engine) as session:
                    session.add(model(**snapshot))
                    session.commit()
                ui.notify("Restored.", type="positive")
                content.refresh()

            content.refresh()
            undo_banner(undo_container, f"Deleted {label_of(snapshot)}.", undo)

        def post(iid):
            post_now(iid)
            ui.notify("Posted.", type="positive")
            content.refresh()

        def skip(iid):
            skip_next(iid)
            ui.notify("Skipped to the next date.", type="info")
            content.refresh()

        # ---------------------------------------------------------------- one subscription
        def open_sub(sid):
            with Session(engine) as session:
                sub = session.get(Subscription, sid)
                if not sub:
                    return
                cur = sub.model_dump()
            is_inst = cur["total_payments"] is not None
            done = is_inst and cur["payments_made"] >= cur["total_payments"]
            with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                section_header(cur["name"], subtitle="Subscription · " + (
                    "paid off" if done else "paused" if not cur["active"]
                    else f"payment {cur['payments_made'] + 1} of {cur['total_payments']}" if is_inst else "active"))
                if cur["active"] and not done:
                    def paid():
                        dialog.close()
                        mark_paid(sid)
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
                    ui.notify("Saved.", type="positive")
                    content.refresh()

                with ui.row().classes("w-full items-center gap-1 mt-2"):
                    ui.button("Delete", icon="delete_outline",
                              on_click=lambda: (dialog.close(), delete(Subscription, sid, lambda s: s["name"]))).props(
                        "flat no-caps color=negative")
                    if not is_inst:
                        ui.button("Resume" if not cur["active"] else "Pause",
                                  icon="play_arrow" if not cur["active"] else "pause",
                                  on_click=lambda: (dialog.close(), set_active(Subscription, sid, not cur["active"]))).props(
                            "flat no-caps")
                    ui.space()
                    ui.button("Save", on_click=save).props("color=primary unelevated no-caps")
            dialog.open()

        # ---------------------------------------------------------------- one scheduled item
        def open_item(iid):
            with Session(engine) as session:
                row = session.get(ScheduledTransaction, iid)
                if not row:
                    return
                cur = row.model_dump()
            lbl = cur["description"] or ("Income" if cur["kind"] == "income" else "Bill")
            with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
                section_header(lbl, subtitle=(
                    f"{'Income' if cur['kind'] == 'income' else 'Bill'} · {'+' if cur['kind'] == 'income' else '-'}"
                    f"{CUR}{cur['amount']:,.2f} {cur['cadence']} · "
                    + ("logged automatically" if cur["auto_post"] else "waits for you to confirm")))
                if cur["next_date"]:
                    ui.label(f"Next: {cur['next_date']:%A %d %B}").classes("text-sm")
                if cur["active"]:
                    with ui.column().classes("w-full gap-1 mt-1"):
                        ui.button("Log it now", icon="check",
                                  on_click=lambda: (dialog.close(), post(iid))).props(
                            "unelevated no-caps color=primary").classes("self-start")
                        ui.button("Skip the next one", icon="skip_next",
                                  on_click=lambda: (dialog.close(), skip(iid))).props(
                            "flat no-caps color=primary").classes("self-start")
                with ui.row().classes("w-full items-center gap-2 mt-2"):
                    ui.button("Delete", icon="delete_outline",
                              on_click=lambda: (dialog.close(), delete(
                                  ScheduledTransaction, iid, lambda s: s["description"] or "the scheduled item"))).props(
                        "flat no-caps color=negative")
                    ui.button("Resume" if not cur["active"] else "Pause",
                              icon="play_arrow" if not cur["active"] else "pause",
                              on_click=lambda: (dialog.close(), set_active(ScheduledTransaction, iid, not cur["active"]))).props(
                        "flat no-caps")
                    ui.space()
                    ui.button("Close", on_click=dialog.close).props("flat no-caps")
            dialog.open()

        # ---------------------------------------------------------------- needs a look
        detected = []
        if subs_on:
            everyday = frozenset(c.id for c in categories if c.name in NON_SUBSCRIPTION_CATEGORIES)
            detected = detect_recurring_transactions(all_tx, [s.name for s in subs], everyday)
        due = sorted([i for i in live_items if not i.auto_post and i.next_date and i.next_date <= today],
                     key=lambda i: i.next_date)
        if detected or due:
            with card_box_accent().classes("w-full gap-1"):
                section_header("Needs a look")
                with ui.column().classes("w-full gap-0"):
                    for i in due:
                        lbl = i.description or ("Income" if i.kind == "income" else "Bill")
                        with ui.element("div").classes("b-nudge").style("cursor:default"):
                            ui.element("span").classes("dot").style(f"background:{AMBER}")
                            with ui.column().classes("b-nudge-text gap-0"):
                                ui.label(f"{lbl} · {'+' if i.kind == 'income' else '-'}{CUR}{i.amount:,.2f}").classes(
                                    "font-semibold")
                                ui.label(f"Due {format_date_header(i.next_date).lower()} — confirm to log it").classes(
                                    "text-xs").style(f"color:{TEXT_DIM}")
                            ui.button("Skip", on_click=lambda _, iid=i.id: skip(iid)).props(
                                "flat dense no-caps").style(f"color:{TEXT_DIM}")
                            ui.button("Log", icon="check", on_click=lambda _, iid=i.id: post(iid)).props(
                                "unelevated dense no-caps color=primary")
                    for cand in detected:
                        per = "month" if cand["cadence"] == "monthly" else "year"
                        with ui.element("div").classes("b-nudge").on("click", lambda c=cand: add_detected(c)):
                            ui.element("span").classes("dot").style(f"background:{INDIGO}")
                            with ui.column().classes("b-nudge-text gap-0"):
                                ui.label(f"{cand['merchant']} · {CUR}{cand['typical_amount']:,.2f}/{per}").classes(
                                    "font-semibold")
                                ui.label(f"Looks like a subscription — seen {cand['count']} times, last "
                                         f"{cand['last_seen'].day} {cand['last_seen']:%b}").classes(
                                    "text-xs").style(f"color:{TEXT_DIM}")
                            with ui.element("div").classes("b-nudge-cta"):
                                ui.label("Track")
                                ui.icon("chevron_right")

        # ---------------------------------------------------------------- add sheets
        if subs_on:
            with sheet_dialog("Add a subscription", adder=adders["sub"]):
                s_name = ui.input(label="Name (e.g. Amazon Prime, or 'Sofa instalments')").props("dense").classes("w-full")
                ui.label("Amount per payment").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
                s_amount = ui.number(placeholder="0.00", format="%.2f").props(
                    f'dense outlined prefix="{CUR}" input-class="text-2xl font-bold"').classes("w-full")
                s_cycle = segmented("Billing cycle", {"monthly": "Monthly", "yearly": "Yearly"}, "monthly")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
                    s_next = date_field("Next payment date")
                    s_cat = ui.select(category_options, value=default_sub_category, label="Category").props(
                        "dense options-dense").classes("w-full")
                s_inst = ui.switch("Paid off in instalments (ends after a set number)", value=False).props(
                    "dense color=primary")
                s_total = ui.number(label="Number of payments", value=3, format="%.0f").props("dense").classes("w-40")
                s_total.bind_visibility_from(s_inst, "value")

                def add_sub():
                    with Session(engine) as session:
                        session.add(Subscription(
                            name=s_name.value or "Unnamed", amount=s_amount.value or 0, billing_cycle=s_cycle.value,
                            next_payment_date=date.fromisoformat(s_next.value) if s_next.value else None,
                            category_id=s_cat.value,
                            total_payments=int(s_total.value) if s_inst.value and s_total.value else None,
                            payments_made=0))
                        session.commit()
                    adders["sub"]["close"]()
                    ui.notify("Subscription added.", type="positive")
                    content.refresh()

                with ui.row().classes("w-full justify-end"):
                    ui.button("Add subscription", on_click=add_sub).props("color=primary unelevated no-caps")

        if sched_on:
            with sheet_dialog("Add a bill or income", adder=adders["sched"]):
                k_kind = segmented("", {"expense": "A bill", "income": "Income"}, "expense")
                ui.label("Amount").classes("text-xs mt-1").style(f"color:{TEXT_DIM}")
                k_amount = ui.number(placeholder="0.00", format="%.2f").props(
                    f'dense outlined prefix="{CUR}" input-class="text-2xl font-bold"').classes("w-full")
                k_desc = ui.input(label="Who to / from (e.g. Landlord, Acme Corp)").props("dense").classes("w-full")
                with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1"):
                    k_cadence = segmented("Repeats", {"weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"},
                                          "monthly")
                    k_next = date_field("Next date", value=today.isoformat())
                k_cat = ui.select(category_options, label="Category", with_input=True).props(
                    "dense options-dense").classes("w-full")
                k_source = ui.select(INCOME_SOURCES, value="Other", label="Income source").props(
                    "dense options-dense").classes("w-full")
                k_source.set_visibility(False)

                def sync_kind(e):
                    k_cat.set_visibility(e.value != "income")
                    k_source.set_visibility(e.value == "income")
                k_kind.on_value_change(sync_kind)
                k_auto = ui.switch("Log it automatically on the day", value=True).props("dense color=primary")
                ui.label("Off: it waits under Needs a look for you to confirm (good for amounts that vary).").classes(
                    "text-xs -mt-1").style(f"color:{TEXT_DIM}")

                def add_item():
                    if not k_amount.value:
                        ui.notify("Enter an amount.", type="warning")
                        return
                    if not k_next.value:
                        ui.notify("Pick the next date.", type="warning")
                        return
                    is_income = k_kind.value == "income"
                    with Session(engine) as session:
                        session.add(ScheduledTransaction(
                            kind=k_kind.value, amount=k_amount.value, description=k_desc.value or None,
                            category_id=None if is_income else k_cat.value,
                            source=k_source.value if is_income else None,
                            cadence=k_cadence.value, next_date=date.fromisoformat(k_next.value),
                            auto_post=k_auto.value))
                        session.commit()
                    adders["sched"]["close"]()
                    ui.notify("Scheduled.", type="positive")
                    content.refresh()

                with ui.row().classes("w-full justify-end"):
                    ui.button("Add", on_click=add_item).props("color=primary unelevated no-caps")

        # ---------------------------------------------------------------- the one list
        rows = []   # (group, sort date, draw)

        def sub_row(sub):
            is_inst = sub.total_payments is not None
            done = is_inst and sub.payments_made >= sub.total_payments
            icon, color = (("check_circle", EMERALD) if done else ("pause_circle", TEXT_DIM) if not sub.active
                           else ("receipt_long", AMBER) if is_inst else ("autorenew", INDIGO))
            per = "mo" if sub.billing_cycle == "monthly" else "yr"
            bits = ["Instalments" if is_inst else "Subscription"]
            if done:
                bits.append("paid off")
            elif not sub.active:
                bits.append("paused")
            elif is_inst:
                bits.append(f"{sub.payments_made} of {sub.total_payments} paid")
            if sub.active and sub.next_payment_date:
                bits.append(_due_text(sub.next_payment_date))
            list_row(icon, color, sub.name, " · ".join(bits), f"{CUR}{sub.amount:,.2f}/{per}",
                     lambda _, sid=sub.id: open_sub(sid))

        def item_row(i):
            is_income = i.kind == "income"
            bits = ["Income" if is_income else "Bill", i.cadence]
            if not is_income and i.category_id in cats_by_id:
                bits.append(cats_by_id[i.category_id].name)
            if i.active and i.next_date:
                bits.append(_due_text(i.next_date))
            elif not i.active:
                bits.append("paused")
            if not i.auto_post:
                bits.append("you confirm")
            list_row("south_west" if is_income else "north_east",
                     (EMERALD if is_income else RED) if i.active else TEXT_DIM,
                     i.description or ("Income" if is_income else "Bill"), " · ".join(bits),
                     f"{'+' if is_income else '-'}{CUR}{i.amount:,.2f}", lambda _, iid=i.id: open_item(iid))

        horizon = today + timedelta(days=30)
        for s in subs:
            nd = s.next_payment_date if s.active else None
            group = "rest" if not s.active else "soon" if nd and nd <= horizon else "later"
            rows.append((group, nd or date.max, lambda s=s: sub_row(s)))
        for i in items:
            nd = i.next_date if i.active else None
            group = "rest" if not i.active else "soon" if nd and nd <= horizon else "later"
            rows.append((group, nd or date.max, lambda i=i: item_row(i)))

        if not rows:
            with card_box().classes("w-full"):
                empty_state("Nothing here yet — tap Add for a subscription, a regular bill or your salary.",
                            "event_repeat")
        for key, title in (("soon", "Next 30 days"), ("later", "Later"), ("rest", "Paused & paid off")):
            group = sorted([r for r in rows if r[0] == key], key=lambda r: r[1])
            if not group:
                continue
            with ui.element("div").classes("b-day"):
                ui.label(title)
                ui.label(str(len(group)))
            with ui.column().classes(LIST_GROUP):
                for _, _, draw in group:
                    draw()

    content()
