# Quick-start: expose the local Second Brain server via Cloudflare Tunnel.
# Produces an ephemeral https://*.trycloudflare.com URL.

$ErrorActionPreference = "Stop"

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared not found. Install it first:"
    Write-Host "  winget install --id Cloudflare.cloudflared"
    Write-Host "  (or download from https://github.com/cloudflare/cloudflared/releases)"
    Write-Host ""
    Write-Host "Then re-run this script."
    exit 1
}

$port = if ($env:PORT) { $env:PORT } else { "8000" }
Write-Host "-> Tunnel target: http://localhost:$port"
Write-Host "-> Press Ctrl-C to stop the tunnel."
Write-Host ""

& cloudflared tunnel --url "http://localhost:$port"
