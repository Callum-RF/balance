# Category UX Follow-ups — Scope

**Status:** Proposed / not started
**Author:** drafted with Claude, 3 Aug 2026
**Context:** Follow-ups after the category taxonomy reorg (26→32) and adding searchable typeahead to the category pickers. Everything below is deferred, captured here so it isn't lost.

Ordered by value. Items 2 and 4 share one underlying capability (**merchant → category inference**) and should be built together.

---

## 1. Quick-pick chips for frequent categories — ✅ BUILT 3 Aug 2026

**Implemented.** The add-transaction form shows a "Quick pick:" row of up to 5 buttons for the most-used categories (by transaction count, via `Counter`); tapping one sets the category select. Hidden when there's no history. Verified in-browser with temp data: chips showed Groceries / Coffee-Snacks / Dining Out / Fuel / Public Transport in frequency order, and tapping set the category correctly.

Original write-up (for reference):

**Now:** the add-transaction form has only the (now searchable) dropdown — every entry is a search/scroll even for the same 4–5 categories used daily.

**Proposal:** above the category select in the single-amount form ([`ui.py` ~1663](../frontend/ui.py)), render ~5 tappable chips of the most-used categories; tapping sets `category_select.value`. One tap covers the bulk of repetitive spend (Groceries, Coffee/Snacks, Dining Out).

**Needs:** a "top categories" query — `SELECT category_id, COUNT(*) FROM 'transaction' GROUP BY category_id ORDER BY 2 DESC LIMIT 5` (optionally windowed to the last ~90 days). Empty today; populates as transactions accrue.

**Effort:** small–medium (query + chip row + wiring to the select). Mobile-friendly.

---

## 2. Merchant → category memory (smart default on manual entry) — ✅ BUILT 3 Aug 2026

**Implemented.** The add-transaction form now builds a merchant→category `history_map` and, on **blur** of the Merchant field, calls `guess_category_id` to pre-select the category — but only if one hasn't already been chosen (never overrides). Verified in-browser: "Tesco Extra" → auto-selects "Food > Groceries", no console errors. Shares the `categorize.py` engine from item 4.

Original write-up (for reference):

**Now:** category always starts blank; you set it every time even for merchants you've logged many times.

**Proposal:** when the Merchant field is filled/blurred, pre-select the category most recently (or most often) used for that merchant. User can still override.

**Needs:** the inference core already exists as of item 4 — `backend/services/categorize.py::guess_category_id` (history + keyword). This item is now just wiring it into `merchant_input.on_value_change` on the manual add form to pre-select `category_select`. Cheap follow-on.

**Effort:** medium. High payoff once there's history; useless until then.

---

## 3. Hide the split-mode help text in single mode — ✅ BUILT 3 Aug 2026

**Implemented.** The split help label is now captured as `split_help` and toggled via `update_mode_visibility()` — hidden in single mode, shown when Split is on. Verified in-browser (hidden by default; appears on toggle).

---

## Bonus — accent/brand colour fix (3 Aug 2026)

While doing the above we found some Quasar components still rendered NiceGUI's **default blue `#5898d4`** (notably `q-uploader__header` on the import page and `q-loading-bar`). Root cause: the app set the accent only via a CSS `--q-primary` override, which reaches components that read that var — but components that bake the **brand** colour into an inline style (uploader, loading bar, ripples, spinners) ignore it. Fix: call `ui.colors(primary=INDIGO)` in `inject_theme()` so Quasar's brand primary is the theme accent too. Verified: 0 default-blue elements remain on the import and add pages; uploader header is now the purple accent. Also converted the import sign-convention toggles to the `segmented()` helper and set the review Expense/Income toggle to `toggle-color=primary`.

Original write-up (for reference):

**Now:** the split explanation ("e.g. one supermarket trip that covered both groceries and a book…", [`ui.py` ~1653](../frontend/ui.py)) is always rendered, padding the form even when the split toggle is off.

**Proposal:** move that label inside `items_section` (or toggle its visibility in `update_mode_visibility()`) so it only shows when Split is on.

**Effort:** trivial (a few lines). Pure layout tidy-up.

---

## 4. Importer: per-row categorisation (fix "everything → Misc") — ✅ BUILT 3 Aug 2026

**Implemented.** New shared service `backend/services/categorize.py` (`guess_category_id` + `build_history_map`, keyword map of common UK merchants). The import review step now gives every row its own category select, pre-filled by: past categorisation of that merchant → keyword guess → blanket default (Misc) as last resort. The old single dropdown became "Set all expenses to… / Apply to all". Income rows hide the category field. Unmatched rows still fall back to Misc (expected). Verified: unit-tested guesses + clean compile + service healthy; the review UI wasn't clicked through end-to-end (file-upload dialog isn't automatable here) — worth one manual smoke test. The keyword map is easily extended as new merchants show up.

Original write-up (for reference):

**Now — root cause of the reported behaviour:** the statement importer applies **one blanket category to all imported expenses**. The review table ([`ui.py` ~2511–2538](../frontend/ui.py)) has no per-row category field; a single "Category for imported expenses" select ([`ui.py:2540`](../frontend/ui.py)) defaults to **Miscellaneous** ([`ui.py:2307`](../frontend/ui.py)) and is written to every row ([`ui.py:2560`](../frontend/ui.py)). So imports dump to Misc unless you change that one dropdown — which then applies to *all* rows equally. (Not a parser bug — `services/statement_import.py` deliberately never assigns categories.)

**Proposal (two parts):**
- **a. Per-row category select** in the review table, so each candidate can be categorised before import. Keep the blanket dropdown as a "set all rows to…" convenience.
- **b. Auto-suggest each row's category** from its description/merchant using the item-2 inference engine, falling back to the blanket default (Misc) only when there's no match. Seed with a small keyword map for common UK merchants (Tesco/Sainsbury's/Aldi/Lidl → Groceries; TFL/Uber/Trainline → Public Transport; Costa/Pret/Greggs/Starbucks → Coffee/Snacks; Shell/BP/Esso → Fuel; …) so it's useful even before there's transaction history.

**Effort:** medium (mostly the review-table UI + the shared inference lookup). This is the item that makes import genuinely useful rather than a bulk-Misc dump.

---

## Suggested sequencing

1. **#3** (trivial layout tidy) — anytime.
2. **#2 + #4b** together — build the merchant→category inference once, use it in both the manual form and the importer. Do this after some real transactions exist (or seed #4b's keyword map so it works from day one).
3. **#4a** (per-row import select) — pairs naturally with #4b.
4. **#1** (quick-pick chips) — once "top categories" has data to draw on.

None are started. Each is additive and independently shippable.
