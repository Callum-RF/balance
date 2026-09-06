# Self-hosting Balance

Balance is a **single-user, self-hosted** app: it runs on your own machine or
server and stores everything locally. Nothing is sent anywhere — no accounts, no
telemetry, no cloud. (That's also why there's no GDPR/data-custody burden: you
hold your own data, we never see it.)

## Quick start (Docker — recommended)

Requires Docker + Docker Compose.

```bash
git clone <your-fork-url> balance
cd balance
docker compose up -d
```

Open **http://localhost:8000**.

That's it. On first run the database is created automatically and the app opens
on a lean, focused set of screens (Dashboard, Transactions, Food Log, Profile,
Settings). Turn on any extra areas under **Settings → Modules**.

To serve on a different host port, edit the left side of the `ports:` mapping in
`docker-compose.yml` (e.g. `"9000:8000"`), then `docker compose up -d` again.

## Your data & backups

All data lives in the **`./data`** folder next to `docker-compose.yml`:

- `app.db` — your SQLite database (transactions, food, everything)
- `receipts/` — receipt images
- `backups/` — automatic daily snapshots the app makes
- `.storage-secret` — signs your session cookie

**To back up, copy the whole `./data` folder somewhere safe.** To restore, put it
back and start the container. Because it's a plain folder on your host, syncing it
to a cloud drive or an external disk is trivial.

> ⚠️ **Don't point two instances at the same `./data`.** SQLite allows only one
> writer. If you already run Balance another way (e.g. a system service on the
> same `app.db`), stop it before starting the container, or use a separate folder.

## Updating

```bash
git pull
docker compose up -d --build
```

Your `./data` is untouched by updates. Schema changes migrate automatically on
start, and existing installs keep all their enabled modules.

## Optional: PIN lock

Set a PIN under **Settings** to require it on each new browser session. The PIN is
stored only as a salted hash — never in plain text.

## Configuration reference

| Setting | Where | Default |
|---|---|---|
| Host port | `ports:` in `docker-compose.yml` | `8000` |
| Timezone | `TZ` env in `docker-compose.yml` | `Europe/London` |
| Bind host (container) | `BALANCE_HOST` (Dockerfile) | `0.0.0.0` |

## Running without Docker

You can also run it directly with Python 3.12+:

```bash
pip install -r requirements.txt
python run.py            # serves on 127.0.0.1:8000
```

Set `BALANCE_HOST=0.0.0.0` to expose it on your network, or `BALANCE_PORT` to
change the port. Data is written to the `data/` folder beside `run.py`.
