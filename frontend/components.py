"""Reusable UI pieces: cards, headers, badges, gauges, meters."""
from contextlib import contextmanager
from datetime import date

from nicegui import ui

from backend.nutrient_info import NUTRIENT_INFO

from .common import expiry_meta
from .theme import (
    AMBER,
    BORDER,
    CARD,
    CARD_ACCENT,
    EMERALD,
    INDIGO,
    RED,
    SURFACE,
    SURFACE_2,
    TEXT,
    TEXT_DIM,
    alpha,
)


def goal_row(label: str, value, info_key: str, unit: str, color: str = None, last: bool = False):
    """One nutrient target as a tidy settings-list row: a colour dot, the name,
    then a slim right-aligned editable value with its unit and the info popover.
    Reads as a list, not a grid of chunky boxes -- and the colour dots give the
    section some variety instead of another wall of identical fields."""
    color = color or INDIGO
    row = ui.row().classes("w-full items-center gap-3 no-wrap py-1.5")
    if not last:
        row.classes(f"border-b border-[{BORDER}]")
    with row:
        ui.element("div").classes("rounded-full shrink-0").style(f"width:7px;height:7px;background:{color}")
        ui.label(label).classes("text-sm flex-1 min-w-0 truncate")
        field = ui.number(value=value).props(
            'dense outlined input-class="text-right"').classes("w-24 shrink-0")
        ui.label(unit).classes("text-xs shrink-0 w-8 text-right").style(f"color:{TEXT_DIM}")
        with ui.element("div").classes("shrink-0"):
            nutrient_info_icon(info_key)
    return field


def card_box():
    return ui.column().classes(CARD)


def card_box_accent():
    """Accent 'hero' card -- same as card_box() but with a faint accent wash and
    a touch more lift, for the one 'look here first' card on a screen."""
    return ui.column().classes(CARD_ACCENT)


def page_header(title: str, subtitle: str = None, icon: str = None):
    """A page's title: large and bold, with an optional one-line subtitle -- the
    same heading as Medley, Cadence and Crescendo. (`icon` is accepted for the
    callers that still pass one; the Ensemble heading doesn't use it.)"""
    with ui.column().classes("gap-1"):
        ui.label(title).classes("b-title")
        if subtitle:
            ui.label(subtitle).classes("b-subtitle")


def summary_strip(stats, width_class: str = ""):
    """A page's headline figures: big numbers under small labels, divided by
    hairlines -- the same figures as Cadence's Stats page. `stats` is a list of
    (label, value, colour) tuples (the colour marks the label), optionally with
    a fourth item: a small line of context under the number. Falsy rows are
    skipped so callers can include figures conditionally."""
    stats = [s for s in stats if s]
    if not stats:
        return
    with ui.element("div").classes(f"b-figs {width_class}"):
        for lbl, val, col, *sub in stats:
            with ui.element("div").classes("b-fig"):
                with ui.element("div").classes("b-fig-label"):
                    ui.element("span").classes("dot").style(f"background:{col}")
                    ui.label(lbl)
                ui.label(str(val)).classes("b-fig-num")
                if sub and sub[0]:
                    ui.label(sub[0]).classes("b-fig-sub")


def date_field(label_text: str = None, value=None):
    """
    Compact, Linear-style date field: a small text input showing the date,
    with a calendar icon that opens a popup date picker on demand -- rather
    than a permanently-expanded inline calendar grid. Returns the ui.input
    element; `.value` holds the ISO date string, same as a plain ui.date.
    """
    with ui.column().classes("gap-1"):
        if label_text:
            ui.label(label_text).classes("text-xs").style(f"color:{TEXT_DIM}")
        with ui.input(value=value).props("dense outlined").classes("w-full") as date_input:
            with ui.menu().props("no-parent-event").classes(f"bg-[{SURFACE}] border border-[{BORDER}] rounded-xl p-1") as menu:
                with ui.date(value=value).bind_value(date_input).props("color=primary").classes("rounded-xl") as picker:
                    with ui.row().classes("justify-between w-full px-2 pb-1"):
                        ui.button("Today", on_click=lambda: picker.set_value(date.today().isoformat())).props("flat dense no-caps").style(f"color:{TEXT_DIM}")
                        ui.button("Done", on_click=menu.close).props("flat dense no-caps").style(f"color:{INDIGO}")
            with date_input.add_slot("append"):
                ui.icon("calendar_today").classes("cursor-pointer text-sm").style(f"color:{TEXT_DIM}").on(
                    "click", menu.open
                )
    return date_input


def nutrient_tooltip(key: str) -> str:
    """Builds a fuller tooltip from NUTRIENT_INFO: summary plus the relevant
    too-little/too-much (for targets) or short/long-term (for limits) detail."""
    info = NUTRIENT_INFO.get(key)
    if not info:
        return ""
    parts = [info["summary"]]
    if info["kind"] == "target":
        parts.append(f"Too little: {info['too_little']}")
        parts.append(f"Too much: {info['too_much']}")
    else:
        parts.append(f"Short-term: {info['short_term']}")
        parts.append(f"Long-term: {info['long_term']}")
    return "  ".join(parts)


def nutrient_info_icon(key: str):
    """A small ⓘ that opens a compact, structured popover (tap or hover) with
    the nutrient's summary and its two labeled facts -- replacing the single
    bulky tooltip blob. Works on touch since it opens on click."""
    info = NUTRIENT_INFO.get(key)
    if not info:
        return
    icon = ui.icon("info").classes("text-sm cursor-pointer").style(f"color:{TEXT_DIM}")
    if info["kind"] == "target":
        facts = [("Too little", info["too_little"], AMBER), ("Too much", info["too_much"], RED)]
    else:
        facts = [("Short-term", info["short_term"], AMBER), ("Long-term", info["long_term"], RED)]
    with icon:
        with ui.menu().props("anchor='bottom middle' self='top middle'"):
            with ui.column().classes("p-3 gap-2").style("max-width:16rem"):
                ui.label(info["label"]).classes("text-sm font-semibold").style(f"color:{TEXT}")
                ui.label(info["summary"]).classes("text-xs leading-snug").style(f"color:{TEXT_DIM}")
                for lbl, text, col in facts:
                    with ui.row().classes("items-start gap-2 no-wrap"):
                        badge(lbl, col)
                        ui.label(text).classes("text-xs leading-snug").style(f"color:{TEXT_DIM}")


def progress_row(label: str, current: float, goal: float, unit: str, is_limit: bool = False,
                 info: str = None, info_key: str = None):
    """A labeled progress bar; for limits, going over goal turns red.
    Pass `info_key` (a NUTRIENT_INFO key) for the structured info popover, or
    `info` for a plain-text tooltip (legacy)."""
    current = current or 0
    goal = goal or 0
    pct = min((current / goal) * 100, 999) if goal else 0
    if is_limit:
        color = RED if current > goal else (AMBER if pct > 80 else EMERALD)
    else:
        color = EMERALD if pct >= 90 else (INDIGO if pct >= 40 else TEXT_DIM)

    with ui.column().classes("w-full gap-1"):
        with ui.row().classes("w-full justify-between items-center"):
            with ui.row().classes("items-center gap-1"):
                ui.label(label).classes("text-sm").style(f"color:{TEXT}")
                if info_key:
                    nutrient_info_icon(info_key)
                elif info:
                    ui.icon("info").classes("text-xs cursor-pointer").style(f"color:{TEXT_DIM}").tooltip(info)
            ui.label(f"{current:,.0f} / {goal:,.0f}{unit}").classes("text-xs").style(f"color:{TEXT_DIM}")
        with ui.element("div").classes("w-full rounded-full h-2").style(f"background:{SURFACE_2}"):
            ui.element("div").classes("rounded-full h-2").style(
                f"background:{color}; width:{min(pct,100)}%"
            )


def stat_card(title: str, value: str, subtitle: str = "", accent: str = None, icon: str = None):
    # accent defaults to the *live* INDIGO token (resolved here, not baked into
    # the signature at import time -- otherwise it freezes to the midnight theme).
    if accent is None:
        accent = INDIGO
    with card_box().classes("flex-1 min-w-[180px]"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            if icon:
                icon_chip(icon, accent, size="text-base")
            ui.label(title).classes("text-xs uppercase tracking-wide").style(f"color:{TEXT_DIM}")
        ui.label(value).classes("text-3xl font-bold").style(f"color:{accent}")
        if subtitle:
            ui.label(subtitle).classes("text-xs").style(f"color:{TEXT_DIM}")


# ---------------------------------------------------------------------------
# Shared design-system components. These define the app's visual language --
# icon-led headers, status pills, KPI tiles, thin meters, empty states -- so
# every page can be built from the same vocabulary rather than hand-styled.
# ---------------------------------------------------------------------------
def badge(text: str, color: str = None):
    """A small rounded status pill: colored text on a translucent tint of the
    same color. Used for statuses, urgency, counts, cadence labels, etc."""
    if color is None:  # resolve the live token, not the one baked at import
        color = TEXT_DIM
    ui.label(text).classes("text-xs px-2 py-0.5 rounded-full whitespace-nowrap font-medium").style(
        f"background:{alpha(color, '22')}; color:{color};"
    )


def icon_chip(icon: str, color: str = None, size: str = "text-xl"):
    """A rounded, tinted square holding a single icon -- the leading glyph on
    section headers and KPI tiles."""
    if color is None:  # resolve the live token, not the one baked at import
        color = INDIGO
    with ui.element("div").classes("flex items-center justify-center rounded-xl shrink-0").style(
        f"background:{alpha(color, '1f')}; width:2.25rem; height:2.25rem;"
    ):
        ui.icon(icon).classes(size).style(f"color:{color}")


def section_header(title: str, icon: str = None, icon_color: str = None,
                   count=None, subtitle: str = None, accent: str = None):
    """Standard card/section heading: optional icon chip, title (+ optional
    count pill and subtitle), and a right-aligned slot returned for callers
    that want to drop a control or figure on the far side. Use inside a card;
    add trailing content with `with section_header(...): ...`."""
    # Resolve tokens to their *live* values here. Baking them into the default
    # args freezes them to whatever theme was active at import (midnight), which
    # renders the title near-white on the light themes (cream/lavender).
    if icon_color is None:
        icon_color = INDIGO
    if accent is None:
        accent = TEXT
    # `icon` / `icon_color` are still accepted from older callers, but the
    # Ensemble heading is plain text -- a chip on every card was just noise.
    with ui.row().classes("w-full items-center gap-3 no-wrap"):
        # min-w-0 + truncate so a long title/subtitle ellipsizes within the
        # space it has rather than growing and shoving the trailing controls
        # (which made the dashboard day-nav chevrons drift on narrow screens).
        with ui.column().classes("gap-0 min-w-0 flex-1"):
            with ui.row().classes("items-center gap-2 min-w-0 no-wrap w-full"):
                ui.label(title).classes("text-lg font-semibold leading-tight truncate").style(f"color:{accent}")
                if count is not None:
                    with ui.element("div").classes("shrink-0"):
                        badge(str(count), TEXT_DIM)
            if subtitle:
                ui.label(subtitle).classes("text-xs truncate w-full").style(f"color:{TEXT_DIM}")
        # trailing slot: the flex-1 title column above fills the space and
        # truncates, so this sits at the right with a fixed width. (No ml-auto --
        # an auto margin eats the free space before flex-grow, which stops the
        # title from truncating and lets it overlap this slot on narrow screens.)
        trailing = ui.row().classes("items-center gap-2 shrink-0")
    return trailing


def thin_meter(current: float, goal: float, color: str, height: str = "h-1.5"):
    """A slim rounded progress bar with no label -- for KPI tiles and compact
    inline meters. Caps the fill at 100% width."""
    current = current or 0
    goal = goal or 0
    pct = min((current / goal) * 100, 100) if goal else 0
    with ui.element("div").classes(f"w-full rounded-full {height} mt-1").style(f"background:{SURFACE_2}"):
        ui.element("div").classes(f"rounded-full {height}").style(f"background:{color}; width:{pct}%")


def ring_gauge(label: str, current: float, goal: float, unit: str, color: str, size: int = 108):
    """A donut gauge -- a coloured arc of current/goal around a faint track with
    the value in the centre and label + goal beneath. The dashboard's headline
    health read: rings rather than flat bars, and the round shape is a
    deliberate break from the app's rectangles."""
    current = current or 0
    goal = goal or 0
    pct = min(current / goal, 1.0) if goal else 0.0
    r = 42
    circ = 2 * 3.141592653589793 * r
    dash = circ * pct
    val = f"{current:,.0f}"
    goal_txt = f"of {goal:,.0f} {unit}" if goal else f"{unit} (no goal)"
    svg = f'''
      <svg viewBox="0 0 100 100" style="width:{size}px;height:{size}px">
        <circle cx="50" cy="50" r="{r}" fill="none" style="stroke:{BORDER}" stroke-width="8"/>
        <circle cx="50" cy="50" r="{r}" fill="none" style="stroke:{color}" stroke-width="8"
                stroke-linecap="round" stroke-dasharray="{dash:.2f} {circ - dash:.2f}"
                transform="rotate(-90 50 50)"/>
        <text x="50" y="47" text-anchor="middle" font-size="20" font-weight="700" style="fill:{TEXT}">{val}</text>
        <text x="50" y="64" text-anchor="middle" font-size="10" style="fill:{TEXT_DIM}">{unit}</text>
      </svg>'''
    with ui.column().classes("items-center gap-0.5"):
        ui.html(svg)
        ui.label(label).classes("text-sm font-semibold leading-tight")
        ui.label(goal_txt).classes("text-xs").style(f"color:{TEXT_DIM}")


def kpi_tile(label: str, value: str, icon: str, accent: str = None,
             sub: str = None, meter=None):
    """Compact headline metric: icon chip, small label, big value, optional
    sub-line and thin meter. `meter` is an optional (current, goal) tuple."""
    if accent is None:  # resolve the live token, not the one baked at import
        accent = INDIGO
    with ui.element("div").classes(
        f"surface-card flex-1 min-w-[150px] rounded-2xl p-3 sm:p-4 flex flex-col gap-1"
    ).style(f"background:{SURFACE}; border:1px solid {BORDER};"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            icon_chip(icon, accent, size="text-base")
            ui.label(label).classes("text-xs uppercase tracking-wide").style(f"color:{TEXT_DIM}")
        ui.label(value).classes("text-2xl sm:text-3xl font-bold leading-tight").style(f"color:{accent}")
        if sub:
            ui.label(sub).classes("text-xs").style(f"color:{TEXT_DIM}")
        if meter is not None:
            thin_meter(meter[0], meter[1], accent)


def empty_state(text: str, icon: str = "inbox"):
    """Consistent centered empty-state for lists with nothing to show."""
    with ui.column().classes("w-full items-center justify-center py-8 gap-2"):
        ui.icon(icon).classes("text-4xl").style(f"color:{BORDER}")
        ui.label(text).classes("text-sm text-center max-w-sm").style(f"color:{TEXT_DIM}")


def undo_banner(container, message: str, on_undo):
    """Show a dismissible 'deleted -- undo' bar in `container`.

    Quasar notification actions are serialized to JSON, so they cannot carry a
    Python callback; this renders a real element with a working button instead.
    """
    container.clear()
    with container:
        with ui.row().classes("w-full items-center gap-2 px-3 py-2 rounded-xl").style(
            f"background:{SURFACE_2}; border:1px solid {BORDER};"
        ):
            ui.icon("delete_outline").classes("text-base").style(f"color:{TEXT_DIM}")
            ui.label(message).classes("text-xs").style(f"color:{TEXT_DIM}")
            ui.space()

            def do_undo():
                on_undo()
                container.clear()

            ui.button("Undo", on_click=do_undo).props("flat dense no-caps").classes("text-xs")
            ui.button(icon="close", on_click=container.clear).props("flat round dense size=sm")


def segmented(label: str, options, value):
    """A labeled segmented (chip) selector for small fixed choice sets -- one
    tap with every option visible, instead of a dropdown you open and scroll.
    `options` is a list or a {value: label} dict; returns the toggle whose
    `.value` reads exactly like the ui.select it replaces."""
    with ui.column().classes("gap-1 w-full"):
        if label:
            ui.label(label).classes("text-xs").style(f"color:{TEXT_DIM}")
        toggle = ui.toggle(options, value=value).props(
            "no-caps unelevated spread dense toggle-color=primary"
        ).classes("seg-toggle w-full text-xs").style(
            f"border:1px solid {BORDER}; border-radius:10px; background:{SURFACE_2};"
        )
    return toggle


def period_delta_badge(current, previous, higher_is_worse=True, neutral=False):
    """Render a small 'vs previous period' change pill next to a headline
    figure. Coloring reflects whether the direction is good or bad for that
    metric (spending up = bad; income up = good); pass neutral=True for
    metrics where neither direction is inherently good or bad (e.g. calories)."""
    if not previous:
        return
    change = (current - previous) / previous * 100
    if abs(change) < 0.5:
        badge("≈ same as previous", TEXT_DIM)
        return
    up = change > 0
    arrow = "▲" if up else "▼"
    if neutral:
        color = TEXT_DIM
    else:
        is_bad = up if higher_is_worse else not up
        color = AMBER if is_bad else EMERALD
    badge(f"{arrow} {abs(change):.0f}% vs previous", color)


def render_expiry_badge(exp_date):
    """Render a small colored pill for an item's expiry, if it has one."""
    meta = expiry_meta(exp_date)
    if not meta:
        return
    label, color = meta
    badge(label, color)


@contextmanager
def form_frame(title: str, icon: str, color: str, compact: bool = False):
    """The frame around an add form: a card with a heading on its own page, or
    nothing at all inside the quick-add sheet (which has its own heading)."""
    if compact:
        with ui.column().classes("w-full gap-3"):
            yield
    else:
        with card_box().classes("w-full max-w-xl"):
            section_header(title, icon=icon, icon_color=color)
            yield


def pill_toggle(options: dict, value, on_change):
    """A row of pill buttons, one active -- the Ensemble tab / filter control.
    Returns a setter so the caller can change the selection itself."""
    state = {"value": value}
    pills = {}
    with ui.element("div").classes("b-pills"):
        for key, label in options.items():
            el = ui.element("div").classes("b-pill" + (" active" if key == value else ""))
            with el:
                ui.label(label)
            pills[key] = el

    def select(key, notify=True):
        state["value"] = key
        for k, el in pills.items():
            el.classes(add="active") if k == key else el.classes(remove="active")
        if notify:
            on_change(key)

    for key, el in pills.items():
        el.on("click", lambda k=key: select(k))
    return select


def list_row(icon: str, color: str, title: str, subtitle: str, value: str, on_click,
             tooltip: str = "Open"):
    """One entry in a day's list: a tinted icon, the name and details, the
    amount on the right. The whole row opens the entry -- editing, deleting and
    anything else live there, not as a strip of icons on every row."""
    with ui.element("div").classes("b-row").on("click", on_click).tooltip(tooltip):
        with ui.element("div").classes("b-row-icon").style(
                f"background:{alpha(color, '22')}; color:{color}"):
            ui.icon(icon)
        with ui.element("div").classes("b-row-text"):
            ui.label(title).classes("b-row-title")
            ui.label(subtitle).classes("b-row-sub")
        ui.label(value).classes("b-row-value")


SUMMARY_PERIODS = {"weekly": "Week", "monthly": "Month", "6month": "6 months", "yearly": "Year",
                   "2year": "2 years", "all_time": "All time"}


def period_pills(on_change, value: str = "monthly"):
    """The Summary views' period picker, as pills. Returns a getter for the
    current period key."""
    state = {"value": value}

    def changed(key):
        state["value"] = key
        on_change()

    pill_toggle(SUMMARY_PERIODS, value, changed)
    return lambda: state["value"]


@contextmanager
def setting_row(icon: str, color: str, title: str, sub: str = None, on_click=None):
    """A settings-list row: tinted icon, title and one line of detail, and a
    slot on the right for its control (a switch, a select, a value). Rows with
    `on_click` open something and show a chevron instead. Yields the detail
    label (None without `sub`) so a caller can update it later."""
    row = ui.element("div").classes("b-row")
    if on_click:
        row.on("click", on_click)
    else:
        row.style("cursor:default")
    with row:
        with ui.element("div").classes("b-row-icon").style(f"background:{alpha(color, '22')}; color:{color}"):
            ui.icon(icon)
        with ui.element("div").classes("b-row-text"):
            ui.label(title).classes("b-row-title")
            sub_label = ui.label(sub).classes("b-row-sub") if sub else None
        with ui.element("div").classes("b-row-end"):
            yield sub_label
            if on_click:
                ui.icon("chevron_right").classes("text-xl").style(f"color:{TEXT_DIM}")
