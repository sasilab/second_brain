#!/usr/bin/env bash
# Quick-start: expose the local Second Brain server via Cloudflare Tunnel.
# Produces an ephemeral https://*.trycloudflare.com URL — fine for personal use,
# changes on every restart. For a stable URL use a named tunnel (see README §Tunnel).

set -euo pipefail

if ! command -v cloudflared >/dev/null 2>&1; then
  cat <<'EOF'
cloudflared not found. Install it first:

  macOS:    brew install cloudflare/cloudflare/cloudflared
  Linux:    https://pkg.cloudflare.com/index.html
  Windows:  winget install --id Cloudflare.cloudflared

Then re-run this script.
EOF
  exit 1
fi

PORT="${PORT:-8000}"
echo "→ Tunnel target: http://localhost:${PORT}"
echo "→ Press Ctrl-C to stop the tunnel."
echo

exec cloudflared tunnel --url "http://localhost:${PORT}"
