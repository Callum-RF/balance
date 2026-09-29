"""Design tokens: Light / Dark with indigo, every colour a CSS variable."""
import re

from nicegui import ui

# ---------------------------------------------------------------------------
# Design tokens: Light and Dark, with indigo -- the same cream / charcoal
# palettes as Medley, Cadence and Crescendo, so the four Ensemble apps read as
# one family.
#
# Every token is a CSS variable (var(--b-...)), defined once per mode in
# inject_theme(). So the tokens are constants: pages read them inside
# f-strings exactly as before, they're safe to import from any module, and
# switching mode is purely a CSS change. The hex values live in THEMES, for the
# few places CSS can't reach: ECharts draws on a canvas (see echart()), and the
# browser's theme-color meta tag.
# ---------------------------------------------------------------------------
_TOKEN_KEYS = ("BG", "SURFACE", "SURFACE_2", "BORDER", "TEXT", "TEXT_DIM",
               "INDIGO", "EMERALD", "AMBER", "RED", "SKY", "VIOLET")

THEMES = {
    "dark": dict(label="Dark", dark=True,
                 BG="#0E1117", SURFACE="#181C23", SURFACE_2="#212630", BORDER="#2A3039",
                 TEXT="#E7EAEF", TEXT_DIM="#9BA3B0",
                 INDIGO="#818CF8", EMERALD="#34D399", AMBER="#F59E0B",
                 RED="#F87171", SKY="#38BDF8", VIOLET="#A78BFA"),
    "light": dict(label="Light", dark=False,
                  BG="#F3EDE1", SURFACE="#FDFBF6", SURFACE_2="#ECE5D6", BORDER="#E0D8C6",
                  TEXT="#2C2A22", TEXT_DIM="#5C5647",
                  INDIGO="#4F46E5", EMERALD="#047857", AMBER="#B45309",
                  RED="#DC2626", SKY="#0369A1", VIOLET="#6D28D9"),
}
# Settings saved before the move to Light/Dark name one of the old presets.
_LEGACY_THEMES = {"midnight": "dark", "ocean": "dark", "cream": "light", "lavender": "light"}


def _var(key: str) -> str:
    return f"var(--b-{key.lower().replace('_', '-')})"


BG, SURFACE, SURFACE_2, BORDER, TEXT, TEXT_DIM = (
    _var(k) for k in ("BG", "SURFACE", "SURFACE_2", "BORDER", "TEXT", "TEXT_DIM"))
INDIGO, EMERALD, AMBER, RED, SKY, VIOLET = (
    _var(k) for k in ("INDIGO", "EMERALD", "AMBER", "RED", "SKY", "VIOLET"))


def alpha(color: str, hex_alpha: str) -> str:
    """A token at partial opacity -- what "#6366F1" + "22" used to do, which
    can't be done by appending digits to a CSS variable."""
    pct = round(int(hex_alpha, 16) / 255 * 100)
    return f"color-mix(in srgb, {color} {pct}%, transparent)"


CARD = f"surface-card bg-[{SURFACE}] border border-[{BORDER}] rounded-2xl p-4 sm:p-5 gap-3 w-full"
# Hero/accent variant of CARD: faint accent wash + a touch more lift, for the
# single "look here first" card on a screen (dashboard attention / welcome).
CARD_ACCENT = "surface-card surface-card-accent border rounded-2xl p-4 sm:p-5 gap-3 w-full"
# A bordered surface holding a day's list rows with hairline dividers --
# the "grouped list" look used by Transactions / Food Log / Settings.
LIST_GROUP = f"bg-[{SURFACE}] border border-[{BORDER}] rounded-2xl w-full overflow-hidden gap-0 p-0"
CHART_PALETTE = [INDIGO, EMERALD, AMBER, SKY, RED, VIOLET, "#FB923C", "#2DD4BF"]
PAGE = "w-full max-w-[1240px] mx-auto p-3 sm:p-6 gap-4 sm:gap-6"

ACTIVE_THEME = "dark"
THEME_DARK = True


def apply_theme(name: str):
    """Select Light or Dark (older preset names map onto one of the two).
    Only the mode changes: the tokens are CSS variables either way."""
    global ACTIVE_THEME, THEME_DARK
    name = _LEGACY_THEMES.get(name, name)
    ACTIVE_THEME = name if name in THEMES else "dark"
    THEME_DARK = THEMES[ACTIVE_THEME]["dark"]


def hex_of(token: str) -> str:
    """The current mode's hex for a token (for canvas charts and meta tags)."""
    for key in _TOKEN_KEYS:
        if token == _var(key):
            return THEMES[ACTIVE_THEME][key]
    return token


_VAR_RE = re.compile(r"var\(--b-([a-z0-9-]+)\)")
_MIX_RE = re.compile(r"color-mix\(in srgb, var\(--b-([a-z0-9-]+)\) (\d+)%, transparent\)")


def _solid(value):
    """Swap CSS variables for real colours throughout a chart's options."""
    if isinstance(value, dict):
        return {k: _solid(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_solid(v) for v in value]
    if isinstance(value, str) and "--b-" in value:
        def mix(m):
            h = hex_of(f"var(--b-{m.group(1)})").lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return f"rgba({r},{g},{b},{int(m.group(2)) / 100:.2f})"
        value = _MIX_RE.sub(mix, value)
        return _VAR_RE.sub(lambda m: hex_of(f"var(--b-{m.group(1)})"), value)
    return value


def echart(options: dict):
    """ui.echart, with theme colours resolved: ECharts draws on a canvas, which
    can't read CSS variables."""
    return ui.echart(_solid(options))


apply_theme("dark")
