# Micronutrient Tracking — Implementation Scope

**Status:** Proposed / not started
**Author:** drafted with Claude, 3 Aug 2026
**Goal:** Let Balance track vitamins and minerals (not just macros + sodium) so daily intake can be compared against RDAs.

---

## 1. Motivation & current state

Balance today records **no vitamins or minerals except sodium**. When a barcode is scanned, `backend/services/openfoodfacts.py::_extract_nutrition` pulls only 7 per-100 g fields (calories, protein, carbs, fat, fiber, sugar, sodium) from Open Food Facts; everything else in the payload is discarded. There are no micronutrient columns on `FoodLog`, `FoodItemCache`, `RecipeItem`, or target fields on `NutrientGoals`.

**Why barcodes alone can't fix this:**
- A Nutrition Facts label legally carries only 4 micros (vitamin D, calcium, iron, potassium), so barcode/label sources are structurally incapable of full micronutrient data.
- Fresh whole foods (fruit, veg, meat, grains) — the bulk of intake — frequently have **no barcode** or aren't in Open Food Facts.

**Chosen approach — hybrid lookup:**
- **Keep** barcode → Open Food Facts for packaged convenience foods (macros).
- **Add** USDA **FoodData Central name search** for whole foods, backed by lab-analyzed datasets (Foundation Foods, SR Legacy) that carry complete micronutrient panels.

---

## 2. Nutrients to add

Target set (aligns with US label + common tracking; extend later if wanted):

**Fat-soluble vitamins:** A (µg RAE), D (µg), E (mg), K (µg)
**Water-soluble vitamins:** C (mg), B1 thiamin (mg), B2 riboflavin (mg), B3 niacin (mg), B6 (mg), B9 folate (µg DFE), B12 (µg)
**Minerals:** calcium (mg), iron (mg), magnesium (mg), phosphorus (mg), potassium (mg), zinc (mg), selenium (µg)
*(sodium already exists)*

Store each on the food entry as an **absolute amount for that logged quantity** (consistent with how `FoodLog` already stores calories/protein/etc.), computed from the source's per-100 g value × grams eaten.

---

## 3. Data model changes

Additive, all nullable — no destructive migration.

| Model | Change |
|---|---|
| `FoodLogBase` | add the ~18 nutrient columns above (Optional[float]) |
| `FoodItemCache` | add `<nutrient>_per_100g` columns; add `fdc_id: Optional[int]` and widen `source` to include `"usda_fdc"` |
| `RecipeItem` | add same nutrient columns (so recipes roll up micros) |
| `NutrientGoalsBase` | add target/RDA fields per nutrient (defaults = adult-male RDAs, see §7) |

**Migration:** SQLite `ALTER TABLE ADD COLUMN` for each (nullable, no backfill). A small idempotent startup migration in `backend/database.py` (check `PRAGMA table_info`, add missing columns) fits the existing single-file-DB style. Note `foreign_keys` is deliberately OFF in this app — no FK work needed here.

---

## 4. USDA FoodData Central integration

New service `backend/services/usda_fdc.py`.

**API — ✅ VERIFIED against the live API 3 Aug 2026 (see §11):**
- Base: `https://api.nal.usda.gov/fdc/v1`
- `GET /foods/search?query=<text>&dataType=Foundation,SR%20Legacy&pageSize=…` → candidate foods with `fdcId`
- `GET /food/{fdcId}` → full `foodNutrients` list (detail format)
- `GET|POST /foods/list` → paged abridged list
- Auth: free key from api.data.gov (sign up via FDC) passed as `?api_key=`; `DEMO_KEY` works for testing. **Rate limit confirmed: 1,000 req/hr/IP for a real key; DEMO_KEY = 30/hr + 50/day; HTTP 429 on exceed, `X-RateLimit-*` headers.**
- Public domain data (no attribution obligation, unlike OFF's ODbL).

**Dataset preference order** when searching: Foundation → SR Legacy → Survey (FNDDS) → Branded. Foundation/SR give the real micro panels; Branded is label-only (last resort, roughly equivalent to OFF).

**Nutrient mapping — ⚠️ CORRECTED:** in the `/food/{fdcId}` detail response each row is `{ "nutrient": { "id", "number", "name", "unitName", "rank" }, "amount": <per-100g> }`. The 1000-series codes I want are the **`nutrient.id`** field, **NOT** `nutrient.number` (which is a separate legacy INFOODS code — e.g. Vitamin A RAE has `id=1106`, `number="320"`). **Map on `nutrient.id`, never on name** (names carry suffixes like "Vitamin C, total ascorbic acid", "Sodium, Na"). Verified id/unit pairs: 1106 Vit A RAE (µg), 1165 thiamin (mg), 1166 riboflavin (mg), 1167 niacin (mg), 1175 B6 (mg), 1177 folate (µg), 1178 B12 (µg). Confirm the remaining ids (1162 Vit C, 1114 Vit D, 1109 Vit E, 1185 Vit K, 1087 Ca, 1089 Fe, 1090 Mg, 1091 P, 1092 K, 1095 Zn, 1103 Se, 1093 Na) with one detail call at build time — trivial now that the shape is known. Units come back as µg/mg (normalise IU→µg only if a Branded row ever uses IU).

**Caching:** reuse the `FoodItemCache` pattern keyed additionally by `fdc_id` (barcode PK stays for OFF). Cache per-100 g values; compute logged amounts at log time.

---

## 5. Backend endpoints

- `GET /api/food/search?q=` → USDA name search (proxied, cached), returns candidates with a nutrient preview.
- `GET /api/food/usda/{fdc_id}` → full per-100 g nutrient set (cache-through).
- Existing `GET /api/barcode/{barcode}` unchanged (macros path).
- `FoodLogCreate` accepts the new nutrient fields; when logging from a USDA pick, backend scales per-100 g × `quantity_g`.
- `GET /api/goals` / `PUT /api/goals` extended for the new RDA target fields (already generic — just new columns).

---

## 6. Frontend

- **Food log entry:** add a "Search foods (USDA)" path alongside the current barcode/manual entry, with a name box → results list → pick → auto-filled micros. Barcode stays for packaged items.
- **Nutrient goals screen:** add micro targets (grouped vitamins / minerals) editable like existing goals.
- **Dashboard / food-log day view:** micro progress vs RDA (compact bars, collapsible so it doesn't crowd the macro view). Reuse existing goal-progress components.

---

## 7. RDA reference defaults (adult male 19–30)

Sensible `NutrientGoals` defaults; user can override:

Vit A 900 µg · Vit C 90 mg · Vit D 15 µg · Vit E 15 mg · Vit K 120 µg ·
B1 1.2 mg · B2 1.3 mg · B3 16 mg · B6 1.3 mg · Folate 400 µg · B12 2.4 µg ·
Calcium 1000 mg · Iron 8 mg · Magnesium 400 mg · Phosphorus 700 mg · Potassium 3400 mg · Zinc 11 mg · Selenium 55 µg.

*(These are age/sex-specific; keep them editable rather than hard-coded, since Callum's real DOB/sex drive them.)*

---

## 8. Phased rollout

1. **Schema + migration** (columns everywhere, nullable) — ships invisibly, safe.
2. **USDA service + search endpoints + cache** — verify API key, rate limits, nutrient map first.
3. **Food-log UI: name search + micro capture.**
4. **Goals RDA targets + dashboard progress.**
5. **Recipes roll-up micros** (nice-to-have once ingredients carry micros).

Steps 1–2 are backend-only and low-risk; UI (3–4) is where most effort sits.

---

## 11. Live verification log (3 Aug 2026)

Checked against the running API with `DEMO_KEY`:
- `GET /foods/search?query=apple raw with skin&dataType=SR Legacy` → returned `fdcId=171689`, dataType "SR Legacy".
- `GET /food/171689` → **110 nutrient rows** with real vitamin/mineral values (the lab-analysed depth barcodes lack). Confirmed row shape `{nutrient:{id,number,name,unitName,rank}, amount}`; confirmed `nutrient.id` = the 1000-series code and is the correct join key (see §4). Sanity note: apple returned folate & B12 = 0, which is correct — so the data is trustworthy, not missing.
- Rate limits/endpoints/dataTypes confirmed per §4.

Net: **no technical blocker.** The data source is high-quality, free, public-domain, and easy to integrate.

## 9. Risks & open questions

- ~~API details unverified~~ — **RESOLVED** (§11). Only the remaining nutrient-id sanity check stays, and that's a one-call task at build time.
- **Name ambiguity** — "apple" returns many entries; needs a good default pick + clear result labels. Generic foods won't match a specific brand's recipe (acceptable trade-off for micros).
- **Unit normalisation** — USDA mixes µg/mg/IU historically; must normalise (e.g. vitamin A/D as µg RAE/µg, not IU).
- **Rate limiting / offline** — cache aggressively; degrade to macros-only when the API is unreachable (mirror the existing OFF fallback behaviour).
- **DB backup size** — more columns × many food rows is negligible for SQLite; no concern.
- **Testing** — extend `tests/test_features.py`: migration idempotency, USDA parse/scale math (mock the HTTP call), goal-progress with micros.

---

## 10. Effort estimate (rough)

- Schema + migration: small
- USDA service + endpoints + cache: medium (most of it is the verified nutrient map + tests)
- Frontend search + micro display: medium–large (largest piece)
- Goals + dashboard: small–medium

A first usable slice (schema + USDA search + log micros, no fancy dashboard) is a **medium** effort; full polish is **medium–large**.
