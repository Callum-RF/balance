"""Regression tests for the theme design tokens.

Guards the class of bug fixed in this session: a theme missing a token, or
low-contrast text (the cream/lavender subtitles that failed WCAG, and the
section titles that were frozen to the midnight color). Adding a new theme
now fails these tests unless it is complete and readable.

Run from the project root:  python -m pytest tests/ -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frontend.ui import THEMES, _TOKEN_KEYS  # noqa: E402


# ---- WCAG relative-luminance contrast -------------------------------------
def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexs):
    h = hexs.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---- tests -----------------------------------------------------------------
def test_every_theme_has_all_tokens():
    required = set(_TOKEN_KEYS) | {"label", "dark"}
    for name, theme in THEMES.items():
        missing = required - set(theme)
        assert not missing, f"theme '{name}' is missing tokens: {sorted(missing)}"


def test_body_and_dim_text_meet_wcag_aa():
    # TEXT (titles/body) and TEXT_DIM (subtitles) must clear AA (4.5:1) on the
    # backgrounds they actually sit on -- the page (BG) and cards (SURFACE).
    for name, t in THEMES.items():
        for bg_key in ("BG", "SURFACE"):
            r_text = _contrast(t["TEXT"], t[bg_key])
            assert r_text >= 4.5, f"{name}: TEXT on {bg_key} = {r_text:.1f}:1 (< 4.5)"
            r_dim = _contrast(t["TEXT_DIM"], t[bg_key])
            assert r_dim >= 4.5, f"{name}: TEXT_DIM on {bg_key} = {r_dim:.1f}:1 (< 4.5)"


def test_accent_colors_are_usable():
    # accents carry big values, icons and meters -- require the 3:1 minimum for
    # large text / non-text UI on the card surface.
    for name, t in THEMES.items():
        for accent in ("INDIGO", "EMERALD", "AMBER", "RED", "SKY", "VIOLET"):
            r = _contrast(t[accent], t["SURFACE"])
            assert r >= 3.0, f"{name}: {accent} on SURFACE = {r:.1f}:1 (< 3.0)"


def test_swatch_label_readable_on_its_own_background():
    # each Settings theme swatch shows its label (theme TEXT) on the theme BG.
    for name, t in THEMES.items():
        r = _contrast(t["TEXT"], t["BG"])
        assert r >= 4.5, f"{name}: swatch label TEXT on BG = {r:.1f}:1 (< 4.5)"
