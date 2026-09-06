# Balance — Product Reshape Scope

**Status:** Proposed / not started
**Drafted:** after the Aug 2026 build sessions
**Supersedes nothing** — this sits above the feature-level scope docs (`category-ux-followups.md`, `micronutrient-scope.md`) and sets direction for turning Balance from a feature-rich personal tool into a focused, deployable product.

---

## 1. The problem

Balance today is really **two apps in one coat** — a personal-finance tracker *and* a nutrition tracker — plus a third layer of "log stuff / see stuff" ledgers. ~17 nav items, most of which *display* data rather than *act on* it. Two consequences:

1. **No spine** — a new user can't answer "what is this *for*?"
2. **Zero time-to-value** — the app demands input before it gives output; nobody fills forms for 15 minutes on faith.

The fix is not "trim tabs." It's **pick a spine, make the first session pay off**, and let decluttering fall out of that.

## 2. Positioning — the spine

**Balance is the money × health app: track what you spend and what it does to your body, in one place.**
Tagline candidate: *"Eat well without overspending."*

The wedge no mainstream app owns: for most people the **biggest controllable spend (groceries + eating out) is also the biggest health input.** Balance lives in that overlap. The differentiated, defensible features:
- **Cost-per-macro / cost-per-calorie** — e.g. "chicken thighs give protein at £0.03/g; those protein bars are your worst deal." (Directly serves a budget-conscious lean bulk.)
- **Eating-out cost in both currencies** — £ *and* calories/macros over budget.
- **A unified log** — a grocery shop or a meal out is simultaneously a spend *and* a nutrition event.

## 3. Audience & deployment

**Decision: self-host, single-user first.** Each person runs their own instance; data lives in their own local SQLite DB. Multi-user/accounts is **deferred** ("later, only if validated").

Rationale: combined **financial + health** data is maximally sensitive; taking custody of strangers' before validating the product is a bad trade. A polished, one-command-deployable single-user app *is* a real product — with none of that liability.

**Compliance posture (local-first):** because each user controls their own data and we never receive it, we are not a GDPR controller/processor, and personal-use tracking is exempt anyway. Guardrails to keep it that way:
- **No telemetry / analytics / crash-reporting phone-home** (or strictly anonymous + opt-in).
- **No hosted option** (that flips us into controller territory).
- **No sending user personal data to third-party APIs** (barcode→OFF is fine; a barcode isn't personal data).
- Keep the existing local hygiene: PIN lock, storage secret, local + mirrored backups.

**One cheap nod now:** don't make a future multi-user path *harder*, but build none of its infra yet.

## 4. The spine as a filter — Core / Optional / Hidden

The spine decides tiering automatically: **Core = touches both money and health; single-sided features become optional.**

- **Core (always on):**
  - Actionable **Dashboard** (see §5)
  - **Log** — one place to add a spend and/or a meal
  - **Food & grocery spend** hero view + the crossover **Insights** (cost-per-macro, eating-out cost, trends)
- **Optional module — Money-only (off by default):** accounts & net worth, income, subscriptions, scheduled transactions, forecast, price/inflation tracking
- **Optional module — Health-only (off by default):** weight, water, recipes, pantry
- **Hidden / power (off by default):** statement import, monthly reports

Nothing is deleted. Power users (e.g. Callum's own instance) flip everything on; the shipped default is lean.

## 5. The actionable dashboard

Principle: answer **"what needs me, and what do I do next?"** — not "here are numbers." Cards, each with a verb and (where possible) a crossover insight only Balance can produce:

- "Grocery budget £210/£250, 8 days left → £5/day to stay under." → *review*
- "Eating out this month: £62 and +3,900 kcal over — cooking these saves ~£40 and the overage." → *see*
- "Today: 40g protein short · £12 spent." → *log a meal*
- "Best protein-per-£ this week: … / worst: …"
- One primary CTA up top; info-only tabs collapse into cards here with drill-down.

Money budget and macro budget shown **side by side** — the visual embodiment of the spine.

## 6. Onboarding / time-to-value

- **No gate.** Land straight in a usable state with sensible defaults.
- **Just-in-time profile** — ask for profile/goals only when a feature needs them, and **estimate** rather than interrogate (infer a calorie target from a couple of taps, not a full form).
- **First action in seconds, first insight immediately** — log one thing → see a real result.
- Success test: a new user understands the "why" and gets a payoff **before** entering meaningful data.

## 7. Mechanism — modules / feature flags

- A **module registry**: each optional area declared with an on/off flag, default off.
- Flags stored in `AppSettings` (already a singleton row) — a "Modules" section in Settings toggles them.
- Nav + dashboard cards render from enabled modules only.
- Keeps one codebase, two experiences (lean default / full power-user).

## 8. Phased plan

1. **Modules infra** — flag system + Settings "Modules" toggles + nav renders from flags. (Low-risk foundation.) **✅ BUILT** — `MODULES` registry + `load_enabled_modules()`/`module_enabled()`/`set_module_enabled()` in `frontend/ui.py`; overrides persisted to `AppSettings.modules_json` (JSON, auto-migrated); nav (drawer + bottom bar) gates on enabled state; Settings > Modules toggles grouped by tier (Money/Health/Power). All modules ship ON in Phase 1 (no visible change); Phase 2 sets the lean defaults. *Known limitation:* only the nav is gated — a disabled module's page is still reachable by direct URL (route guards are a Phase 2 add).
2. **Declutter** — retier nav to Core; move money-only/health-only/power behind modules (off by default). Instant "focused app" feel. **✅ BUILT** — registry moved to shared `backend/modules.py` with **lean defaults (all 12 optional modules OFF)**; fresh install = 5 core nav items (Dashboard, Transactions, Food Log, Profile, Settings). Existing installs auto-backfilled to all-on via `_backfill_modules_defaults` (sentinel `_lean_v2`, runs once) so upgrading hides nothing. **Route guards** added: a disabled module's page renders a "turned off → open Settings" notice instead of the real page (no direct-URL leak). Settings > Modules gains **Enable all / Lean defaults** presets. Verified in-browser: lean = 5 routes, guard blocks `/prices`, presets flip both ways, existing instance preserved at all-on.
3. **Actionable dashboard** — rebuild as verb-driven cards incl. a first cut of the crossover insights (the "why" shows up early). **✅ FIRST CUT BUILT** — added an actionable layer on top of the existing (good) detail cards rather than rewriting them: a **quick-actions row** (Add expense / Log meal / Add income) and a **"Needs your attention"** card of computed, verb-driven nudges with CTAs — grocery/overall budget burn-down ("£200/£250, N days left — £X/day to stay under"), macro gap / "no meals logged today", eating-out spend (money+health framing), and subscriptions-due-this-week (module-gated). Income/Net KPIs + month rows now gate on the income module. Verified in-browser with temp data (nudges + math correct). *Deferred to Phase 5:* the deep crossover (true cost-per-macro, eating-out **calories**) needs the unified spend+meal log / cost-linked food data.
4. **Onboarding / time-to-value** — remove the setup gate; JIT profile; first-win flow.
5. **Deepen the intersection** — cost-per-macro, eating-out money+health, the unified spend+meal log entry.
6. **Package & deploy** — one-command self-host (e.g. Docker image), polish, README/setup.

**Deferred (only if validated):** multi-user + auth + per-user data isolation.

## 9. Non-goals / guardrails

- **No multi-user / accounts / hosted backend now.**
- **No deleting features** — hide behind modules; power-user experience stays intact.
- **No new micro-tracking build** yet (the USDA micronutrient plan stays parked).
- **No telemetry.**
- Don't let "modernize" balloon scope — every change serves *spine clarity* or *time-to-value*; if it serves neither, it waits.

## 10. Open decisions

- **Naming/positioning copy** — confirm the tagline and the one-line "why."
- **How aggressive is the default declutter** — which (if any) money-only or health-only items are common enough to be Core rather than optional.
- **Packaging target** — Docker image vs a simple installer vs both, for the self-host story.
- **Multi-user trigger** — what evidence would justify revisiting the deferred multi-user path.
