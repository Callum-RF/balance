# Balance

Personal expense + nutrition tracker. FastAPI + SQLite backend, NiceGUI
frontend, single process, single database file. Runs on your desktop as a
Windows service (NSSM) or Linux service (systemd), reachable from your
phone over Tailscale.

## Run it

```bash
cd expense-nutrition-tracker
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac
pip install -r requirements.txt
python run.py
```

Open **http://localhost:8000**. API docs at **http://localhost:8000/docs**.

If you moved this folder after creating the venv, delete `venv/` and
recreate it — Windows venvs bake in an absolute path and break on a move.

## What's in this version

**Dashboard** — a glanceable top row of KPI tiles (calories today, spend
this month vs. budget, net), then a **Today** card you can page back through
day by day (‹ ›) showing that day's macros, a "things to watch" strip that
only surfaces limits you're actually near or over, and inline water
logging. Below that, a **This month** card (income / spent / net plus
overall and per-category budget bars) and an **Overview** section over a
chosen window (day → 1 year) with a spending-trend bar chart, a category
pie whose legend lets you exclude categories from the total, nutrition
bars, and "vs previous period" change badges so the numbers have context.

**Transactions** — add/list/delete, categorized, with an optional context
tag (alone / with friends / with family / work / other) to see how context
affects spending. The log is searchable and filterable by merchant/notes
text, category, and date range, and the currently-filtered set can be
exported to CSV. A **Summary** tab charts spending over time (a per-day or
per-month trend with an average line) and by category. Income has the same
Log / Summary / Add layout, including its own income-trend chart and CSV
export.

**Import Statement** — bulk-import transactions and income from a CSV or
PDF bank statement instead of entering them one at a time. CSV parsing is
exact (structured data, nothing to guess). PDF parsing extracts real text
and works well for genuine digital statements, but explicitly refuses and
tells you to export a CSV instead if the PDF turns out to be a scanned
image with no readable text — deliberately not repeating the mistake made
with receipt scanning (see below). Nothing is saved until you've reviewed
every row and confirmed; possible duplicates (matching an existing entry's
date and amount) are flagged and unchecked by default. An "undo this
import" option is available immediately after importing.

**Food Log** — add/list/delete, barcode lookup via Open Food Facts
(cached locally), core macros plus an optional expandable section for
sugar, fiber, sodium, saturated fat, trans fat, added sugar, alcohol, and
caffeine. Also taggable by context.

**Pantry** — track what's in your fridge/freezer/pantry, grouped by
location. Mark items consumed or wasted (wasted items roll up into a
running "money lost to waste" total). Items expiring within 7 days are
flagged, more urgently under 48 hours. A rough "runway" estimate shows how
many days your current stock covers based on stored calories vs. your
daily calorie goal.

**Subscriptions** — track recurring payments (Amazon Prime, YouTube
Premium, etc.), monthly or yearly, normalized into a single monthly total.
Also surfaces **detected recurring payments**: merchants you're charged by
on a regular monthly/yearly cadence with near-constant amounts but haven't
set up as a subscription yet, each with a one-click "add as subscription".

**Prices** — log prices for items you buy repeatedly and see the
percentage change since you started tracking, a per-item line chart, and a
"compare all (indexed)" overlay that rebases every tracked item to 100 at
its first reading so items at different price points can be compared on
relative change.

**Profile & Goals** — date of birth (age calculated automatically), height,
sex, activity level (described in plain terms, not just "moderate"), weight
log, full control over your daily nutrient targets and limits (calories,
macros, fiber, water, added sugar, saturated fat, trans fat, sodium,
alcohol, caffeine), and an overall monthly budget plus optional
**per-category budgets** that show as their own bars on the dashboard.
Progress bars throughout the app pull from these goals; tap the ⓘ by any
nutrient for a short structured explainer of what it does and what too
little / too much looks like (general public-health reference info, not
medical advice).

**Settings** — pick your display currency (symbol only, no conversion),
manage categories (add / rename inline / delete, with anything still using a
deleted category safely moved to Uncategorized), and set an optional
**PIN lock** that gates the UI per browser session (stored salted-hashed;
note the JSON API under `/api` is not PIN-gated — Tailscale remains the real
security boundary). A **Backup** card on Profile & Goals downloads every
table as one dated JSON file.

**Editing & quality-of-life** — every transaction, income, and food entry
can be edited in a prefilled dialog; deletes show an **Undo** banner instead
of being instantly permanent; the Food Log and Income Add tabs lead with
one-tap **Quick add** chips of your recent entries (log yesterday's porridge
or this month's salary without retyping); the dashboard shows a 6-month
**Savings** chart (net income − spending) and an **Insights** card calling
out categories that moved noticeably vs the same point last month.

**Design & mobile** — the whole UI shares one design system (icon-led
section headers, status pills, KPI tiles, consistent empty states) built on
a dark, Linear-inspired theme. Every page is responsive and tested down to
phone width, and the app ships a PWA manifest so you can "Add to Home
Screen" on your phone and launch it like a native app.

## Known simplifications / what's next

- **Receipt OCR was tried and scrapped.** An earlier version attempted to
  auto-read merchant/total/date off a photographed receipt via Tesseract.
  In practice, thermal-printer receipt photos were too unreliable for a
  general-purpose OCR engine — accuracy varied a lot and wasn't trustworthy
  enough to build on. Add Transaction now instead lets you **attach a
  receipt photo purely for your own reference** (stored in `data/receipts/`,
  viewable later from the Transactions list) while you type the actual
  merchant/amount/date yourself. No pip package or separate program install
  needed anymore as a result.
- **Barcode scanning** (Add Food) needs a live device/browser to fully
  verify — the camera/JS parts couldn't be tested in the environment this
  was built in. If it misbehaves, the specific error message (or browser
  console output) will make fixing it fast.
- **Pantry items don't auto-fill nutrition from barcode** the way Food Log
  entries do — added manually for now, since pantry quantities are in
  mixed units (g/kg/ml/l/unit) which complicates auto-scaling.
- The Profile page's "sex" and "activity level" fields feed the Forecast
  page's BMR/TDEE estimate; the "sex" field's only effect is a small
  constant offset in that formula, nothing else.

## Architecture note

Every page/section reads and writes the database directly via SQLModel
sessions (see `frontend/ui.py`), rather than making HTTP calls to the
FastAPI backend from the frontend. Same process, so this avoids pointless
network round-trips — but it does mean the JSON API (`/docs`) and the UI
share models but aren't strictly required to go through each other. The
API is there for you to script against directly if useful, and is the
natural place to add things like a receipt-upload endpoint later.

## Deployment (recap)

The app itself is plain Python and already runs the same way on Windows,
Linux, and Mac — nothing in the code is Windows-specific. What differs
between platforms is only how you keep it running in the background.

### Windows

NSSM, pointed at `venv\Scripts\python.exe` running `run.py`, working
directory = project root. (Full walkthrough earlier in this README/your
setup history — `nssm install ExpenseTracker`, then `nssm start
ExpenseTracker`.)

### Linux (Mint, or any systemd-based distro)

1. Set up the venv the normal way:
   ```bash
   cd expense-nutrition-tracker
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   deactivate
   ```
2. Create `/etc/systemd/system/balance.service`:
   ```ini
   [Unit]
   Description=Balance expense & nutrition tracker
   After=network.target

   [Service]
   Type=simple
   User=YOUR_USERNAME
   WorkingDirectory=/home/YOUR_USERNAME/expense-nutrition-tracker
   ExecStart=/home/YOUR_USERNAME/expense-nutrition-tracker/venv/bin/python run.py
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   (Replace `YOUR_USERNAME` and the path with your actual username and
   wherever you put the project.)
3. Enable and start it:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now balance.service
   ```
4. Check it's running and see logs if something's wrong:
   ```bash
   sudo systemctl status balance.service
   journalctl -u balance.service -f
   ```
5. If you ever move the project folder, the same rule as Windows applies —
   delete `venv/` and recreate it, since venvs bake in an absolute path
   regardless of platform.

### Android

Balance doesn't run *on* Android — your phone is a client, not a host.
The server (Windows or Linux machine, whichever you use) runs
continuously; your phone just opens it in a browser over Tailscale, same
as visiting any website. There's no separate Android build or install
step beyond what's already covered under Tailscale + "Add to Home
Screen" below — this isn't a gap, it's just how the architecture works
(one server, any number of client devices).

### Remote access (any host platform)

Tailscale on the server + phone, same account on both, then
`http://<tailscale-ip>:8000` from your phone's browser. "Add to Home
Screen" in Chrome to install it like an app.

**Why Tailscale specifically, and keep it:** the app has **no login** — it
holds your finances and health data but anything that can reach `:8000`
sees everything. Tailscale *is* the security boundary here: only devices on
your own tailnet can reach the server, and to the public internet the app
simply doesn't exist (no open ports, nothing to scan). That's why remote
access should go through Tailscale (or a comparable private VPN) rather than
port-forwarding or a public tunnel (ngrok / Cloudflare Tunnel), which would
expose an unauthenticated personal-data app to the world.

- If you only ever use it at home on the same Wi-Fi, you can skip Tailscale
  and hit the server's LAN address (`http://<192.168…>:8000`) — reserve its
  IP in your router so it doesn't drift. You lose away-from-home access.
- Keep your tailnet to your own devices. If you ever want to share Balance
  with someone else, that's the point to add real authentication rather than
  widen network/tailnet access.
- `run.py` already binds `0.0.0.0`, so it's reachable on the Tailscale
  interface with no code change.

### A friendly, private URL — `https://balance.<your-tailnet>.ts.net`

Goal: reach the app at a real name over HTTPS instead of
`http://<tailscale-ip>:8000`, while keeping it **private to your own devices**
and **buying no domain**. Tailscale does all of this for free.

> **Common wrong turn:** the **"Search domains"** field in Tailscale's DNS
> settings does *not* rename your machine or set the app's URL — it only adds
> a DNS *search suffix* (so a bare hostname gets a domain appended when you
> look it up). Leave it alone; the settings that actually matter are
> **MagicDNS**, the **machine name**, and **`tailscale serve`** below.

1. **Enable MagicDNS.** Tailscale admin console → **DNS** tab → turn on
   **MagicDNS**. This is what makes `<machine>.<tailnet>.ts.net` names
   resolve for devices on your tailnet.
2. **Enable HTTPS.** Same **DNS** tab → turn on **HTTPS Certificates**. This
   lets Tailscale issue a real TLS cert for your machine's name (needed for
   the secure `https://` URL and the Android PWA install).
3. **Name the machine (optional but nicer).** Admin console → **Machines** →
   click your server → the **⋮** menu → **Edit machine name** → e.g.
   `balance`. Your tailnet name (the `...ts.net` part) is shown in the admin
   console; the full address is `<machine-name>.<tailnet-name>.ts.net`.
4. **Publish the app on HTTPS with `tailscale serve`.** On the server (keep
   `python run.py` running on `:8000` as usual — `serve` just fronts it):
   ```bash
   sudo tailscale serve --bg 8000
   ```
   Then confirm the exact URL it gave you:
   ```bash
   tailscale serve status
   ```
   That prints something like `https://balance.tailXXXX.ts.net` → `http://127.0.0.1:8000`.
   (Flag names shift slightly between Tailscale versions — `tailscale serve
   --help` shows the exact form for yours. To stop: `tailscale serve reset`.)

   There's a helper that does steps 4's start + status in one go (and can turn
   it off again):
   ```bash
   scripts/serve.sh          # start serving and print the URL
   scripts/serve.sh off      # stop serving (app keeps running locally)
   ```
5. **Open that `https://…ts.net` URL on your phone.** No IP, no port, HTTPS,
   still only reachable from your own tailnet.

If the name still won't resolve on the **phone**, check that the phone's
Tailscale is connected and set to **use Tailscale DNS** (MagicDNS pushes the
DNS config to each device; with that off, the `.ts.net` names won't resolve).

**About the `tailXXXX` part of the name:** that middle chunk is your *tailnet
name*, auto-generated by Tailscale. On a personal/individual account it's
fixed — you can rename the *machine* (`balance`) but not the tailnet suffix,
and you shouldn't try to swap in a custom hostname via local DNS because the
HTTPS certificate is issued for the real `...ts.net` name and a mismatch
breaks the padlock. In practice it doesn't matter: once you **Add to Home
Screen**, you launch Balance from an icon labelled "Balance" and never see or
type the URL again — the ugly suffix only lives in the address bar you stop
using.

### Installing as a PWA (Add to Home Screen)

Balance ships a web manifest, icons, and a service worker, so it installs to
your phone's home screen and launches full-screen like a native app. The one
requirement is a **secure context** — HTTPS or `localhost`; plain
`http://<tailscale-ip>:8000` doesn't count.

- **iOS Safari** — Share → **Add to Home Screen** works even over plain HTTP;
  you get the standalone, full-screen app either way.
- **Android Chrome** — for the real "Install app" prompt you need HTTPS, i.e.
  the `tailscale serve` URL from the section above. Open
  `https://<machine>.<tailnet>.ts.net`, then Chrome menu → **Install app**.

### Backups

The whole app is one file, `data/app.db`, plus `data/receipts/` for
attached receipt photos. Back them up however you like — the mechanism
doesn't depend on which OS is hosting it.
