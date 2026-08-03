#!/usr/bin/env bash
#
# Publish Balance over HTTPS on your tailnet via `tailscale serve`, and print
# the resulting private URL. Balance itself must already be running
# (`python run.py`) on port 8000 -- `tailscale serve` just fronts it with
# HTTPS and your MagicDNS name.
#
# Usage:
#   scripts/serve.sh          # start serving (proxies :8000) and print the URL
#   scripts/serve.sh 8000     # same, with an explicit port
#   scripts/serve.sh off      # stop serving (Balance still runs locally)
#   scripts/serve.sh status   # just print the current serve URL
#
# Note: `tailscale serve` flags shift a little between Tailscale versions; if
# the command below errors, `tailscale serve --help` shows the exact form.

set -euo pipefail

ARG="${1:-8000}"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "tailscale not found on PATH. Install Tailscale first: https://tailscale.com/download"
  exit 1
fi

case "$ARG" in
  off|stop)
    echo "Stopping tailscale serve for Balance..."
    sudo tailscale serve reset
    echo "Stopped. Balance is no longer published on your tailnet (it still runs locally on :8000)."
    exit 0
    ;;
  status)
    tailscale serve status
    exit 0
    ;;
esac

PORT="$ARG"

if ! curl -sf -o /dev/null "http://127.0.0.1:${PORT}/"; then
  echo "Balance isn't responding on http://127.0.0.1:${PORT}"
  echo "Start it first, e.g.:  source venv/bin/activate && python run.py"
  exit 1
fi

echo "Publishing Balance over HTTPS on your tailnet (proxying :${PORT})..."
sudo tailscale serve --bg "${PORT}"

echo
echo "Your private URL (open on your phone, then Add to Home Screen):"
tailscale serve status
