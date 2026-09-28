"""The food page."""
from datetime import date

from nicegui import ui
from sqlmodel import Session, select

from backend.database import engine
from backend.models import (
    Category,
    FoodLog,
    NutrientGoals,
    Transaction,
)
from backend.services.openfoodfacts import lookup_barcode

from ..common import (
    CUR,
    MEAL_ICONS,
    TAG_OPTIONS,
    format_date_header,
    group_by_date,
    set_page_refresh,
)
from ..components import (
    date_field,
    empty_state,
    form_frame,
    list_row,
    page_header,
    pill_toggle,
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
    alpha,
)


# ---------------------------------------------------------------------------
# Add / list food log
# ---------------------------------------------------------------------------
def render_add_food_form(on_saved=None, compact=False):
    """Builds the add-food form in whatever container is currently active.
    Reused by both the standalone /add-food page and the Add tab on the
    merged /food-log page."""
    with form_frame("Add Food Entry", "restaurant", INDIGO, compact):

        date_input = date_field("Date", value=date.today().isoformat())
        meal_select = segmented(
            "Meal", {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}, "lunch"
        )

        with ui.column().classes("w-full gap-1 mt-2"):
            ui.label("Quantity (g)").classes("text-xs").style(f"color:{TEXT_DIM}")
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                quantity_input = ui.number(value=100, format="%g").props("dense").classes("flex-grow")
                for q in [50, 100, 150, 200]:
                    ui.button(f"{q}", on_click=lambda _, v=q: quantity_input.set_value(v)).props(
                        "flat dense no-caps"
                    ).classes("text-xs min-w-0 px-2").style(f"color:{INDIGO}")

        tag_select = ui.select(TAG_OPTIONS, value="", label="Tag (context)").props("dense options-dense").classes("w-full mt-2")
        eaten_out_toggle = ui.switch("Eaten out (restaurant / takeaway)", value=False).props("dense color=primary").classes("mt-1")

        # Unified spend+meal log: when eaten out, optionally record the spend too,
        # so one entry captures both the meal (health) and the transaction (money).
        with Session(engine) as _s:
            _out_cats = {c.id: c.name for c in _s.exec(select(Category)).all()
                         if c.name in ("Eating Out", "Groceries")}
        _default_out_cat = next((cid for cid, n in _out_cats.items() if n == "Eating Out"), None)
        with ui.column().classes("w-full gap-1 mt-1 pl-3 border-l-2").style(f"border-color:{alpha(INDIGO, '55')}") as out_spend_section:
            ui.label("Also log the spend").classes("text-xs").style(f"color:{TEXT_DIM}")
            with ui.row().classes("w-full items-end gap-2 flex-wrap"):
                out_amount = ui.number(label="Amount", format="%.2f").props(f'prefix="{CUR}" dense').classes("w-28")
                out_merchant = ui.input(label="Where").props("dense").classes("flex-grow min-w-[120px]")
                out_cat = ui.select(_out_cats, value=_default_out_cat, label="Category").props("dense options-dense").classes("w-36")
        out_spend_section.bind_visibility_from(eaten_out_toggle, "value")

        with ui.row().classes("w-full items-end gap-2 mt-2"):
            barcode_input = ui.input(label="Barcode (scan or type)").props("dense").classes("flex-grow")
            ui.button(icon="qr_code_scanner", on_click=lambda: scan_barcode()).props("outline dense round").tooltip("Scan with camera")
            ui.button(icon="search", on_click=lambda: do_lookup()).props("outline dense round").tooltip("Look up typed barcode")
        lookup_status = ui.label().classes("text-xs").style(f"color:{TEXT_DIM}")

        name_input = ui.input(label="Food name").props("dense").classes("w-full mt-1")

        ui.label("Calories").classes("text-xs mt-2").style(f"color:{TEXT_DIM}")
        calories_input = ui.number(placeholder="0").props(
            'suffix="kcal" input-class="text-2xl font-bold"'
        ).classes("w-full")
        with ui.grid().classes("w-full grid-cols-3 gap-x-3 gap-y-1 mt-1"):
            protein_input = ui.number(label="Protein (g)").props("dense").classes("w-full")
            carbs_input = ui.number(label="Carbs (g)").props("dense").classes("w-full")
            fat_input = ui.number(label="Fat (g)").props("dense").classes("w-full")

        with ui.expansion("More nutrients (optional)").classes("w-full mt-1"):
            with ui.grid().classes("w-full grid-cols-2 gap-x-3 gap-y-1"):
                sugar_input = ui.number(label="Sugar (g)").props("dense").classes("w-full")
                fiber_input = ui.number(label="Fiber (g)").props("dense").classes("w-full")
                sodium_input = ui.number(label="Sodium (mg)").props("dense").classes("w-full")
                satfat_input = ui.number(label="Saturated fat (g)").props("dense").classes("w-full")
                transfat_input = ui.number(label="Trans fat (g)").props("dense").classes("w-full")
                addedsugar_input = ui.number(label="Added sugar (g)").props("dense").classes("w-full")
                alcohol_input = ui.number(label="Alcohol (g)").props("dense").classes("w-full")
                caffeine_input = ui.number(label="Caffeine (mg)").props("dense").classes("w-full")

        result_label = ui.label().style(f"color:{EMERALD}")

        def do_lookup():
            barcode = barcode_input.value
            if not barcode:
                return
            with Session(engine) as session:
                item = lookup_barcode(session, barcode)
            if not item or item.calories_per_100g is None:
                lookup_status.set_text("Not found in Open Food Facts")
                return
            factor = (quantity_input.value or 100) / 100.0
            name_input.value = item.name or ""
            calories_input.value = round((item.calories_per_100g or 0) * factor, 1)
            protein_input.value = round((item.protein_per_100g or 0) * factor, 1)
            carbs_input.value = round((item.carbs_per_100g or 0) * factor, 1)
            fat_input.value = round((item.fat_per_100g or 0) * factor, 1)
            sugar_input.value = round((item.sugar_per_100g or 0) * factor, 1)
            fiber_input.value = round((item.fiber_per_100g or 0) * factor, 1)
            sodium_input.value = round((item.sodium_per_100g or 0) * factor, 1)
            satfat_input.value = round((item.saturated_fat_per_100g or 0) * factor, 1)
            transfat_input.value = round((item.trans_fat_per_100g or 0) * factor, 1)
            caffeine_input.value = round((item.caffeine_per_100g or 0) * factor, 1)
            lookup_status.set_text(f"Found: {item.name}")

        async def scan_barcode():
            scan_js = """
                return await new Promise((resolve) => {
                    if (typeof Html5Qrcode === 'undefined') {
                        resolve({error: 'Scanner library did not load. Check your internet connection.'});
                        return;
                    }
                    const overlay = document.createElement('div');
                    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:#0B0B0F;'
                        + 'display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px;';
                    const readerDiv = document.createElement('div');
                    readerDiv.id = 'balance-barcode-reader';
                    readerDiv.style.cssText = 'width:100%;max-width:480px;border-radius:12px;overflow:hidden;';
                    const hint = document.createElement('div');
                    hint.innerText = 'Point the camera at a barcode';
                    hint.style.cssText = 'color:#E4E4E7;margin-bottom:12px;font-family:sans-serif;font-size:14px;';
                    const cancelBtn = document.createElement('button');
                    cancelBtn.innerText = 'Cancel';
                    cancelBtn.style.cssText = 'margin-top:16px;padding:10px 28px;border-radius:10px;'
                        + 'background:#1C1C22;color:#E4E4E7;border:1px solid #26262E;font-size:14px;';
                    overlay.appendChild(hint);
                    overlay.appendChild(readerDiv);
                    overlay.appendChild(cancelBtn);
                    document.body.appendChild(overlay);

                    let finished = false;
                    const html5QrCode = new Html5Qrcode('balance-barcode-reader');

                    function cleanup() {
                        if (document.body.contains(overlay)) document.body.removeChild(overlay);
                    }
                    function finish(value) {
                        if (finished) return;
                        finished = true;
                        html5QrCode.stop().catch(() => {}).finally(() => {
                            cleanup();
                            resolve(value);
                        });
                    }

                    html5QrCode.start(
                        { facingMode: 'environment' },
                        { fps: 10, qrbox: 250 },
                        (decodedText) => finish({code: decodedText}),
                        () => { /* ignore per-frame no-match, keep scanning */ }
                    ).catch((err) => {
                        cleanup();
                        resolve({error: 'Could not access camera: ' + err});
                    });

                    cancelBtn.onclick = () => finish({code: null});
                });
            """
            try:
                result = await ui.run_javascript(scan_js, timeout=60.0)
            except Exception as exc:
                ui.notify(f"Camera scan failed or timed out: {exc}", type="warning")
                return
            if not result:
                return
            if result.get("error"):
                ui.notify(result["error"], type="negative")
                return
            code = result.get("code")
            if code:
                barcode_input.value = code
                do_lookup()

        def submit():
            with Session(engine) as session:
                entry = FoodLog(
                    date=date.fromisoformat(date_input.value),
                    meal_type=meal_select.value,
                    food_name=name_input.value or "Unnamed food",
                    barcode=barcode_input.value or None,
                    quantity_g=quantity_input.value or 100,
                    tag=tag_select.value or None,
                    eaten_out=eaten_out_toggle.value,
                    calories=calories_input.value,
                    protein_g=protein_input.value,
                    carbs_g=carbs_input.value,
                    fat_g=fat_input.value,
                    sugar_g=sugar_input.value,
                    fiber_g=fiber_input.value,
                    sodium_mg=sodium_input.value,
                    saturated_fat_g=satfat_input.value,
                    trans_fat_g=transfat_input.value,
                    added_sugar_g=addedsugar_input.value,
                    alcohol_g=alcohol_input.value,
                    caffeine_mg=caffeine_input.value,
                )
                session.add(entry)
                session.commit()
                also_spent = bool(eaten_out_toggle.value and out_amount.value)
                if also_spent:
                    session.add(Transaction(
                        date=date.fromisoformat(date_input.value),
                        amount=out_amount.value,
                        merchant=(out_merchant.value or name_input.value or "Meal out")[:200],
                        category_id=out_cat.value,
                        payment_method="Card",
                        notes="Logged with a meal",
                    ))
                    session.commit()
            result_label.set_text("Saved — meal + spend logged!" if also_spent else "Saved!")
            # reset for the next entry rather than leaving stale values behind
            barcode_input.value = ""
            name_input.value = ""
            quantity_input.value = 100
            calories_input.value = None
            protein_input.value = None
            carbs_input.value = None
            fat_input.value = None
            out_amount.value = None
            out_merchant.value = ""
            lookup_status.set_text("")
            if on_saved:
                on_saved()

        ui.button("Save food entry", on_click=submit).props("color=primary unelevated")


def add_food_page():
    render_add_food_form()


# The fields carried over when an entry is logged again.
NUTRIENT_COPY_FIELDS = (
    "food_name", "barcode", "quantity_g", "calories", "protein_g", "carbs_g", "fat_g",
    "fiber_g", "sugar_g", "sodium_mg", "saturated_fat_g", "trans_fat_g",
    "added_sugar_g", "alcohol_g", "caffeine_mg",
)


def relog_food(eid):
    """Copy an existing entry onto today, keeping all its nutrition -- the most
    common food-logging action by far. Returns the food's name."""
    with Session(engine) as session:
        src = session.get(FoodLog, eid)
        if not src:
            return None
        data = {f: getattr(src, f) for f in NUTRIENT_COPY_FIELDS}
        data.update(date=date.today(), meal_type=src.meal_type, tag=src.tag)
        session.add(FoodLog(**data))
        session.commit()
    return data["food_name"]


def recent_foods(limit: int = 8):
    """Your most recently logged distinct foods, for one-tap re-logging."""
    with Session(engine) as session:
        recent = session.exec(
            select(FoodLog).order_by(FoodLog.date.desc(), FoodLog.id.desc()).limit(120)
        ).all()
    seen, favourites = set(), []
    for e in recent:
        key = (e.food_name or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        favourites.append(e)
        if len(favourites) >= limit:
            break
    return favourites


MEALS = {None: "All", "breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"}


def food_log_page():
    page_header("Food Log", "What you ate today, measured against your targets.")

    @ui.refreshable
    def figures():
        today = date.today()
        with Session(engine) as s:
            tf = s.exec(select(FoodLog).where(FoodLog.date == today)).all()
            g = s.exec(select(NutrientGoals)).first() or NutrientGoals()
        cal = sum(f.calories or 0 for f in tf)
        pro = sum(f.protein_g or 0 for f in tf)
        summary_strip([
            ("Calories today", f"{cal:,.0f}" + (f" / {g.calories:,.0f}" if g.calories else ""), INDIGO),
            ("Protein today", f"{pro:,.0f}g" + (f" / {g.protein_g:,.0f}g" if g.protein_g else ""), EMERALD),
            ("Meals logged", str(len(tf)), AMBER),
        ])

    figures()
    state = {"meal": None}

    # --- toolbar: search and meal pills ---
    with ui.element("div").classes("b-toolbar mt-1"):
        search_input = ui.input(placeholder="Search food or tag").props(
            "dense outlined clearable debounce=300").classes("b-field")
        with search_input.add_slot("prepend"):
            ui.icon("search").classes("text-lg").style(f"color:{TEXT_DIM}")
    pill_toggle({k or "all": v for k, v in MEALS.items()}, "all",
                lambda k: (state.update(meal=None if k == "all" else k), refresh()))
    result_summary = ui.label().classes("b-count")
    undo_container = ui.column().classes("w-full")
    list_container = ui.column().classes("w-full gap-0")

    def query_food():
        with Session(engine) as session:
            query = select(FoodLog)
            if state["meal"]:
                query = query.where(FoodLog.meal_type == state["meal"])
            entries = session.exec(query.order_by(FoodLog.date.desc()).limit(400)).all()
        term = (search_input.value or "").strip().lower()
        if term:
            entries = [e for e in entries if term in (e.food_name or "").lower() or term in (e.tag or "").lower()]
        return entries

    _DISPLAY = {"limit": 60}

    def render_list():
        list_container.clear()
        entries = query_food()
        filters_active = bool((search_input.value or "").strip() or state["meal"])
        if entries:
            total = sum(e.calories or 0 for e in entries)
            result_summary.set_text(f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} · {total:,.0f} kcal")
        else:
            result_summary.set_text("")
        shown = entries[:_DISPLAY["limit"]]
        with list_container:
            if not entries:
                if filters_active:
                    empty_state("No food matches these filters.", "search_off")
                else:
                    empty_state("No food logged yet -- tap + to log your first entry.", "restaurant")
            for group_date, day_entries in group_by_date(shown):
                day_total = sum(e.calories or 0 for e in day_entries)
                with ui.element("div").classes("b-day"):
                    ui.label(format_date_header(group_date))
                    ui.label(f"{day_total:,.0f} kcal")
                with ui.column().classes(LIST_GROUP):
                    for e in day_entries:
                        icon, icon_color = MEAL_ICONS.get(e.meal_type, ("restaurant", TEXT_DIM))
                        sub = f"{(e.meal_type or 'meal').capitalize()}"
                        if e.protein_g:
                            sub += f" · {e.protein_g:,.0f}g protein"
                        if e.tag:
                            sub += f" · {e.tag}"
                        list_row(icon, icon_color, e.food_name, sub, f"{e.calories or 0:,.0f} kcal",
                                 lambda _, eid=e.id: open_edit_food(eid))
            remaining = len(entries) - len(shown)
            if remaining > 0:
                def _more():
                    _DISPLAY["limit"] += 100
                    render_list()
                ui.button(f"Show more ({remaining} remaining)", icon="expand_more", on_click=_more).props(
                    "flat no-caps color=primary").classes("self-center mt-2")

    def refresh():
        _DISPLAY["limit"] = 60   # reset to the top whenever filters change
        render_list()

    def refresh_all():
        figures.refresh()
        refresh()

    def open_edit_food(eid):
        """The whole entry: edit it, log it again today, or delete it."""
        with Session(engine) as session:
            e = session.get(FoodLog, eid)
            if not e:
                return
            cur = {f: getattr(e, f) for f in NUTRIENT_COPY_FIELDS}
            cur.update(date=e.date.isoformat(), meal_type=e.meal_type or "lunch", tag=e.tag or "")

        with ui.dialog() as dialog, ui.card().classes(f"bg-[{SURFACE}] border border-[{BORDER}] gap-2 w-full max-w-md"):
            section_header("Food entry", icon="edit", icon_color=INDIGO)
            e_date = date_field("Date", value=cur["date"])
            e_meal = segmented("Meal", {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner", "snack": "Snack"},
                               cur["meal_type"] if cur["meal_type"] in ("breakfast", "lunch", "dinner", "snack") else "lunch")
            e_name = ui.input(label="Food name", value=cur["food_name"]).classes("w-full")
            e_qty = ui.number(label="Quantity (g)", value=cur["quantity_g"], format="%g").classes("w-full")
            e_cal = ui.number(label="Calories", value=cur["calories"]).props(
                'suffix="kcal" input-class="text-xl font-bold"'
            ).classes("w-full")
            with ui.grid().classes("w-full grid-cols-3 gap-x-3 gap-y-1"):
                e_prot = ui.number(label="Protein (g)", value=cur["protein_g"]).classes("w-full")
                e_carb = ui.number(label="Carbs (g)", value=cur["carbs_g"]).classes("w-full")
                e_fat = ui.number(label="Fat (g)", value=cur["fat_g"]).classes("w-full")
            e_tag = ui.select(TAG_OPTIONS, value=cur["tag"], label="Tag (context)").classes("w-full")

            def save_edit():
                with Session(engine) as session:
                    obj = session.get(FoodLog, eid)
                    if obj:
                        obj.date = date.fromisoformat(e_date.value)
                        obj.meal_type = e_meal.value
                        obj.food_name = e_name.value or obj.food_name
                        obj.quantity_g = e_qty.value or 0
                        obj.calories = e_cal.value
                        obj.protein_g = e_prot.value
                        obj.carbs_g = e_carb.value
                        obj.fat_g = e_fat.value
                        obj.tag = e_tag.value or None
                        session.add(obj)
                        session.commit()
                dialog.close()
                ui.notify("Food entry updated.", type="positive")
                refresh_all()

            def again():
                dialog.close()
                name = relog_food(eid)
                ui.notify(f"Logged {name} for today.", type="positive")
                refresh_all()

            def delete_it():
                dialog.close()
                delete_entry(eid)

            ui.button("Log this again today", icon="replay", on_click=again).props(
                "flat dense no-caps color=primary").classes("self-start")
            with ui.row().classes("w-full items-center gap-2 mt-2"):
                ui.button("Delete", icon="delete_outline", on_click=delete_it).props(
                    "flat no-caps color=negative")
                ui.space()
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=save_edit).props("color=primary unelevated no-caps")
        dialog.open()

    def delete_entry(eid):
        with Session(engine) as session:
            obj = session.get(FoodLog, eid)
            if not obj:
                return
            snapshot = {f: getattr(obj, f) for f in NUTRIENT_COPY_FIELDS}
            snapshot.update(date=obj.date, meal_type=obj.meal_type, tag=obj.tag)
            session.delete(obj)
            session.commit()

        def undo_delete():
            with Session(engine) as session:
                session.add(FoodLog(**snapshot))
                session.commit()
            ui.notify("Restored.", type="positive")
            refresh_all()

        refresh_all()
        undo_banner(undo_container, f"Deleted {snapshot['food_name']}.", undo_delete)

    search_input.on_value_change(lambda e: refresh())
    refresh()
    set_page_refresh(refresh_all)
