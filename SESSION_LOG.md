# Second Brain — Session Log

**Date:** 2026-05-14
**Status:** All 18 spec build-order steps complete. Plus weather/location context, full auto-linking system, MOC builder, Obsidian graph colors, ZIP import. Repo initialised; first commit `176450d` on branch `main`.

---

## TL;DR

Built the entire Second Brain system end-to-end in one session, working from `SECOND_BRAIN_SPEC.md`. The system runs (deps installed in `.venv` via uv, all `.py` compile clean), and the user confirmed text-capture filing works. Additional features layered on top of the spec: weather/location enrichment for daily entries, automatic Obsidian-graph linking (Tags pages, Related sections, daily round-ups), a `cli.py group` command for MOC creation, color groups for the graph view, and ZIP support for chat imports. Repo initialised, README rewritten for open-source, MIT license + CONTRIBUTING added, `.gitignore` whitelist-style for the vault, branch renamed `master → main`. Final attempted action was `gh repo create second-brain-private --private --source=. --remote=private --push` — interrupted because `gh` isn't on PATH inside the sandbox shell.

---

## Build sequence (spec build-order §18)

### Step 1 — Project scaffolding
- Folder tree per spec §12: `app/{routers,services,parsers,models}/`, `frontend/{css,js,icons}/`, `vault/{00_Inbox..08_Attachments,Templates,_meta}/`
- `requirements.txt`, `.env.example`, `.gitignore`, `run.py`, `app/main.py`, `app/config.py`, `vault/Templates/daily.md`
- `app/config.py` uses pydantic-settings; loads `.env`; exposes `vault_root`, `meta_dir`, `chroma_dir`, `daily_dir`, etc.

### Step 2 — LLM provider system (`app/services/llm_providers.py`)
- `LLMProvider` ABC with `complete(prompt, system, json_mode)`, `is_configured()`, `model()`, `supports_vision()`, `describe_image(bytes, mime, prompt)`
- `OpenAIProvider`, `AnthropicProvider`, `GoogleProvider` — lazy SDK clients
- `PROVIDERS` registry, `get_provider`, `get_active_provider`, `list_providers`, `reset_clients` (added in step 15)
- All three support both text completion and vision

### Step 3 — Vault service (`app/services/vault.py`)
- `make_id`, `write_note(folder, filename, content, metadata)`, `read_note`, `make_filename(date, title)`, `resolve_category_dir`, `vault_relative`
- `append_daily(date, body, prefix, header_suffix)` — creates daily file with H1 header on first call, appends `## HH:MM[ · suffix]` blocks
- `ensure_obsidian_graph_config()` (added later) — writes `vault/.obsidian/graph.json` if absent

### Step 4 — AI processing pipeline (`app/services/processor.py`)
- Single LLM call returning JSON `{type, category, tags, summary, title}` (uses provider's native JSON mode where supported)
- `_strip_json_fences`, `_sanitize` for robustness
- `_file_with_analysis(...)` shared helper: daily/journal → append, else → new file in PARA folder
- Per-type entry points: `process_text_capture`, `process_voice_capture`, `process_image_capture`, `process_link_capture`
- Each accepts optional `context` (weather/location) and threads to vault + frontmatter

### Step 5 — FastAPI auth + capture
- `app/auth.py` — bcrypt hash in `vault/_meta/config.json`, in-memory bearer-token set, `require_auth` dependency, `bootstrap_from_env` (seeds from `APP_PASSWORD`)
- `app/routers/auth.py` — `/api/auth/{status,setup,login}`
- `app/routers/capture.py` — `/api/capture/text` (extended later for voice/image/link)
- `app/main.py` — FastAPI factory, CORS, `/api/health`, mounts static frontend

### Step 6 — PWA chat UI
- `frontend/index.html`, `css/style.css`, `js/app.js`, `manifest.json`
- Dark WhatsApp-style theme; auth screen → chat view
- Text capture working end-to-end (**confirmed by user**)

### Step 7 — Voice capture
- `app/services/transcriber.py` — OpenAI Whisper API wrapper. Hard-requires `OPENAI_API_KEY` regardless of active provider.
- Backend: `POST /api/capture/voice` (multipart audio + optional `lat`/`lon` form fields)
- Frontend: mic button with red-pulse recording state, MediaRecorder, format auto-detection (`webm/opus`, `mp4`, `ogg`), transcript shown as user bubble + filing result

### Step 8 — Image capture
- Vision support added to all three providers in `llm_providers.py`
- Backend: `POST /api/capture/image` — saves to `08_Attachments/{date}-{shortid}.{ext}`, calls active provider's `describe_image`, runs pipeline. Orphaned file cleanup if vision fails.
- Frontend: paperclip → file picker, thumbnail bubble, "Analyzing image…" pending → result
- Image embed in note: `![Image](../08_Attachments/<file>)` (works because all PARA target folders are 1 level deep)

### Step 9 — Link capture
- `app/services/web_fetcher.py` — `httpx` + BeautifulSoup, strips `script/style/nav/footer/aside/iframe`, prefers `<article>`/`<main>`, caps text at 30 K chars
- Backend: `POST /api/capture/link` (JSON body `{url, context?}`)
- Frontend: bare-URL detection in send (single-line, `http(s)://`, no whitespace) → routes to `/link` automatically; link bubble + page-title result

### Step 10 — ChromaDB indexer + `/api/search` + `/api/ask`
- `app/services/indexer.py` — lazy `PersistentClient(path=vault/_meta/chroma)`, collection `second_brain` (cosine HNSW)
- `chunk_text(max_chars=1000, overlap=100)` paragraph→sentence→hard-cut
- `index_note(note_id, content, frontmatter, vault_relpath)` — delete-by-`note_id` then upsert; deterministic IDs `{note_id}_chunk_{i}`
- `search(query, limit, filters)` — pulls 3× limit, dedupes to best chunk per note, returns full text + score + metadata
- `reindex_vault()` — wipe + walk + re-index; assigns `daily-YYYY-MM-DD` IDs to daily files, UUID5-from-path for legacy notes
- `app/routers/search.py` — `/api/search` (filters: type/source/category) and `/api/ask` (top 6 hits → grounded LLM answer with sources)
- Indexing called automatically after every capture

### Step 11 — Chat importers (parsers)
- `app/parsers/_common.py` — `load_json` (handles UTF-8 BOM), `parse_date` (Unix s/ms, ISO 8601, common strings), `NormalizedConversation`/`NormalizedMessage` TypedDicts
- `app/parsers/chatgpt.py` — walks `mapping` from `current_node` back to root, then reverses (handles edits/branches); skips system + non-text content
- `app/parsers/claude.py` — accepts `[convs]` or `{conversations: [...]}`; reads `chat_messages`; maps `human`→user, `assistant|claude|model`→assistant; pulls text from `text` field, then content blocks
- `app/parsers/gemini.py` — handles JSON conversations AND My Activity items (header `Bard`/`Gemini`); strips `Asked: `/`Said: `/etc. prefixes
- `app/services/chat_importer.py` — stable `uuid5(source + source_id || title|date)` IDs; filename `YYYY-MM-DD-{slug}-{6-hex}.md`; idempotent (file-exists skip); optional LLM tagging/summary; auto-link after each chat
- `app/routers/import_chats.py` — `POST /api/import/{chatgpt,claude,gemini}` returning `ImportResponse`

### Step 12 — Import UI with SSE progress
- `chat_importer.iter_import` generator yields `{phase: started|progress|done, total, index, title, imported, skipped, failed}`
- Streaming endpoints `/api/import/{source}/stream` — sync iterator runs in daemon thread, events surface via `asyncio.Queue` + `loop.call_soon_threadsafe`; `text/event-stream` with `X-Accel-Buffering: no`
- Frontend: import overlay (source dropdown, file picker, "process with LLM" toggle, optional limit), `fetch(POST)` reads `response.body` as stream, animated progress bar + live counters

### ZIP support (added between 12 and 13 on user request)
- `app/services/import_helpers.py` — `extract_payload(raw, source)` returns `(content, "json"|"html")`. Detects ZIP by magic bytes (`PK\x03\x04`).
- For Gemini ZIPs: skips paths containing `gemini_scheduled_actions_data`, `gemini_gems_data`, `__MACOSX`, `.DS_Store`. Picks `MyActivity.json` (priority 100) > `MyActivity.html` (90) > any `.json` under a Gemini path (50).
- Gemini parser gained `parse_html(html)` — walks `.outer-cell` divs, regex-matches dates, strips action prefixes
- Endpoints dispatch `parse` vs `parse_html` based on extracted format

### Step 13 — Search UI in PWA
- Topbar 🔍 → search overlay
- 280 ms debounced input; Enter triggers immediately; Escape closes
- Result cards with title, monospace path, type · source · date dots, 4-line clamped snippet, tag pills, match-percentage badge
- Race-safe (per-request sequence number)
- Path click copies to clipboard (later upgraded to obsidian:// in step 14)

### Step 14 — Browse UI + obsidian:// links + `VAULT_NAME`
- `app/config.py` — `vault_name: str = ""` setting + `effective_vault_name` property (falls back to vault folder name)
- `.env.example` — `VAULT_NAME=` line with explanatory comment
- `app/routers/config.py` — `GET /api/config` returning `{vault_name, active_provider}` (auth-gated)
- `app/services/browse.py` — walks vault, parses frontmatter, extracts H1 as title (falls back to `original_title`, then filename); 30 s in-memory cache; `invalidate_cache` exposed
- Cache invalidated after every capture and chat import
- `app/routers/browse.py` — `GET /api/notes/recent?limit&offset&type&source&tag` and `GET /api/tags?limit`
- Frontend: ☰ topbar button → browse overlay with type/source/tag dropdowns + reset; tag dropdown populated from `/api/tags`; paginated note cards with "Load more" (30 per page)
- `obsidianUrl(path)` helper builds `obsidian://open?vault=…&file=…` (URL-encoded, `.md` stripped)
- `buildPathLink(path)` returns `<a href="obsidian://...">` if `vault_name` set, else copy-to-clipboard fallback
- All path renderers updated: capture-result "Filed to", ask-result sources, search results, browse cards
- `refreshAppConfig()` runs after `showApp()` so vault name is loaded before first card

### Step 15 — Settings UI (option a — keys in `_meta/config.json`)
- `app/services/runtime_settings.py` — `RUNTIME_KEYS` whitelist, `load_overrides`, `save_overrides`, `apply_overrides` (mutates `settings` instance), `update`
- `llm_providers.reset_clients()` — clears cached SDK clients on save
- `app/routers/settings.py` — `GET /api/settings` (keys returned only as `*_configured: bool`), `PUT /api/settings` (empty string clears an override), `GET /api/settings/providers`
- `app/main.py` — `runtime_settings.apply_overrides()` at startup (after `ensure_vault_dirs`, before `auth.bootstrap_from_env`)
- Frontend: ⚙ topbar button → settings overlay with provider selector, per-provider model/key inputs (key inputs blank means "no change"), vault name field, configured badges

### Step 16 — Service worker + offline queue
- `frontend/sw.js` — caches app shell on install (`/`, `/index.html`, `/css/style.css`, `/js/app.js`, `/manifest.json`), passes `/api/*` straight through to network. Caches additional shell assets opportunistically. Falls back to cached `/` for navigation requests when offline.
- `app.js` registers SW on startup
- IndexedDB store `capture_queue` — `enqueueCapture/listQueue/removeQueueItem` helpers
- `drainQueue()` runs on `online` event + at startup (with 1.5s delay)
- `📵 offline` topbar badge driven by `navigator.onLine`
- `captureText`/`captureLink` fall through to enqueue on `TypeError("Failed to fetch")` or `!navigator.onLine`
- Voice/image stay online-only (binary blobs in IDB skipped — could be added later)

### Step 17 — Cloudflare Tunnel scripts
- `setup_tunnel.sh` (bash, uses `set -euo pipefail`) — checks for `cloudflared`, prints install hints per OS, runs ephemeral tunnel
- `setup_tunnel.ps1` (PowerShell equivalent) — same, with `winget install --id Cloudflare.cloudflared` hint
- `PORT` env var honoured; defaults to 8000

### Step 18 — Polish + verify
- README rewritten end-to-end (then rewritten again in the open-source pass)
- All 32 `.py` files compile (`python -m py_compile run.py cli.py app/...`)
- File tree verified — every spec §12 path exists plus the additions

---

## Features beyond spec

### Weather + location enrichment (added between steps 9 and 10)
- `app/services/weather.py` — `get_context(lat, lon)` returns `{lat, lon, temp_c, condition, weather_emoji, location}`. Open-Meteo for weather (with `is_day` for night moon emojis), **OpenStreetMap Nominatim for reverse geocoding** because Open-Meteo doesn't have a reverse endpoint (their geocoding is forward-only). 15-min in-memory cache keyed by `(round(lat, 2), round(lon, 2))` ≈ 1 km grid.
- `vault.append_daily(..., header_suffix="")` — daily timestamp lines become `## 16:26 · ☀️ 22°C, partly cloudy · Coburg`
- `processor._file_with_analysis(..., context=None)` — threads context through; new files get `context:` in frontmatter, daily files get the header suffix
- `app/models/schemas.py` — `CaptureContext { lat, lon }`; text/link requests gained `context: CaptureContext | None`; voice/image endpoints take `lat`/`lon` as `Form` fields
- Frontend: `getCoords()` helper with 3 states (`unknown`/`granted`/`denied`), browser permission persisted, 5-min in-memory cache, `enableHighAccuracy: false`, 5 s timeout, 10 min `maximumAge`. Once denied, never re-prompts in the session. Silently skipped for offline.

### Auto-linking (`app/services/linker.py`)
Three sections injected into every standalone note's body, all wrapped in HTML comment markers so they're idempotent:

- `<!-- linker:tags -->` — wikilinks like `[[Tags/python|python]]` for each tag
- `<!-- linker:related -->` — top 3 most-similar notes via ChromaDB. **Skipped for `type=moc`** (a MOC is already a curated list).
- `<!-- linker:daily-links -->` (daily files only) — links to standalone notes filed the same day

Tag index pages live in `vault/Tags/<tag>.md` — auto-generated, list every note with that tag, sorted newest first. Filename sanitised (`<>:"/\|?*` → `-`).

Hooks:
- After every capture (`processor._file_with_analysis`): `linker.link_new_note(path)` + `linker.update_tag_pages(tags)` + `linker.link_daily_for_date(today)`
- After every chat import (`chat_importer._import_one`): `linker.link_new_note(path)`
- Once at end of import loop: `linker.regenerate_all_tag_indexes()` (cheaper than per-chat regen)
- `cli.py link` runs both passes vault-wide

The indexer **strips** `<!-- linker:* -->` sections before chunking, so auto-link content never pollutes embeddings. The indexer also skips the `Tags/` folder.

### MOC builder (`app/services/moc_builder.py`, `cli.py group`)
- `python cli.py group "startup work - Tharavu Research, ExplainPannu, CivicDataLab"`
- `split_topic_terms` splits on `,`, `;`, ` - `, ` – `, ` — ` → multiple sub-queries
- `gather_candidates` runs full topic + each sub-term through `indexer.search` (limit 20 each), dedupes by `note_id`, skips MOCs and `Tags/`, caps at 50
- `organize_with_llm` sends candidates to active provider in JSON mode; system prompt enforces `{title, summary, categories: [{name, description?, notes: [{path, note?}]}]}` — paths validated against candidate set so hallucinations get dropped
- Fallback: invalid JSON → dump everything in one "Related notes" category
- Writes to `01_Projects/{date}-moc-{slug}.md` with frontmatter `type: moc, source: cli, tags: [moc, ...top 6 inherited from candidates]`
- Indexes + links the MOC

### Obsidian graph color groups (`vault.ensure_obsidian_graph_config`)
- Writes `vault/.obsidian/graph.json` at startup **only if absent**
- Color groups (24-bit RGB ints in Obsidian's format):
  - `path:05_Daily` → blue (#3a7aff)
  - `path:06_Chats/ChatGPT` → green (#4caf50)
  - `path:06_Chats/Claude` → purple (#9c27b0)
  - `path:06_Chats/Gemini` → orange (#ff9800)
  - `path:01_Projects` → red (#ef4444)
  - `path:02_Areas` → yellow (#fbc02d)
  - `path:03_Resources` → teal (#00bfa5)
  - `path:07_References` → gray (#9e9e9e)
  - `path:Tags` → pink (#ec407a)

---

## Current state — what's working

### Confirmed by user
- Steps 2-6 (text capture pipeline → file in vault). Quote: *"Steps 2-6 are working — text capture is filing to the vault correctly."*
- User has `.env` configured with API keys (don't read this file)
- Vault has been populated: link.md and Untitled.canvas at root, plus content under `_meta/`, `Tags/`, `.obsidian/`

### Implemented + compile-clean, awaiting user verification
- Voice capture (step 7)
- Image capture (step 8) — vision API across all three providers
- Link capture (step 9)
- Weather/location (PWA → backend → daily header + frontmatter)
- ChromaDB indexer + search + ask (step 10)
- Chat importers (step 11) — JSON paths
- Import UI with SSE progress (step 12)
- ZIP import for Claude + Gemini (with sidecar dir skipping for Gemini)
- Gemini HTML parser (My Activity)
- Search UI (step 13)
- Browse UI + obsidian:// links (step 14)
- Settings UI (step 15) with runtime override of provider keys
- Auto-linking + Tags pages + Related sections + daily round-ups
- MOC builder (`cli.py group`)
- Obsidian graph color groups
- Service worker + IndexedDB offline queue (step 16)
- Cloudflare Tunnel scripts (step 17)

### Verified compile-clean
All 32 `.py` files pass `python -m py_compile` (last check: after MOC builder + linker tweak + git setup).

---

## Known issues

- **Obsidian "block not supported" rendering** — user-reported, **unfixed**. Not investigated this session. Likely candidates to look at next time:
  - Wiki-link format edge cases (paths with special chars, the `[[path|title]]` pipe form)
  - HTML comment markers (`<!-- linker:tags -->`) — Obsidian *should* hide these, but worth confirming
  - Markdown produced by chat imports (User/Assistant blocks)
  - Whatever produces a `> [!block]` callout or similar block syntax that Obsidian can't render
  Open one of the affected notes in the Obsidian source view to identify which block is failing.
- Settings file (`vault/_meta/config.json`) is **plain JSON, not encrypted**. Filesystem permissions are the only protection. The spec says "encrypted" but this would be theatre without a separate user-input passphrase. Documented in README and CLAUDE.md.
- `git status`/`git add` requires `safe.directory` allowlist on the `I:` drive (Windows + non-NTFS-style filesystem). Workaround used in this session: `git -c safe.directory='I:/Code Space/second_brain' <cmd>`. Permanent fix: `git config --global --add safe.directory 'I:/Code Space/second_brain'` (run by user, not by Claude — sandbox rule forbids global git config writes).
- `gh` CLI not on PATH inside the bash sandbox — last command interrupted with `gh: command not found`. User should run `gh repo create ...` from their own shell.

---

## Pending work

1. **Obsidian "block not supported" fix** — see Known Issues. Investigate which markdown construct Obsidian can't render; adjust the producing code (likely `linker.py` or `chat_importer.py`).
2. **ChatGPT import** — waiting for user's export email from OpenAI; export not yet downloaded.
3. **Gemini re-export** — current `gemini_chat.zip` doesn't include the right format; user needs to re-export from Google Takeout with **My Activity → Gemini Apps Activity** explicitly selected (HTML or JSON).
4. **README screenshots** — `docs/screenshots/{chat,search,graph}.png` are referenced as placeholders; need real PNGs. Take from the running PWA + Obsidian graph view.
5. **Mobile PWA icons** — `manifest.json` has no `icons` array. iOS/Android home-screen install will use a generic placeholder. Generate `192x192` and `512x512` PNGs (suggest `🧠` brain emoji on `#0f1115` background), drop into `frontend/icons/`, add `icons` array to `manifest.json`.
6. **Push to GitHub** — last attempted command `gh repo create second-brain-private --private --source=. --remote=private --push` was interrupted (gh not on sandbox PATH). Run from user shell.

---

## How to run

### Server
```powershell
cd "I:\Code Space\second_brain"
.venv\Scripts\activate
python run.py
# → http://localhost:8000
```

First visit sets a password. After that, log in with the same password.

### Cloudflare Tunnel (public URL)
```powershell
.\setup_tunnel.ps1               # Windows
# or:  ./setup_tunnel.sh          # macOS/Linux
```
Ephemeral URL — changes on every restart. For a stable URL use a named tunnel (see README "Public access" section).

### CLI commands
```powershell
.venv\Scripts\python cli.py status                        # provider config + index size
.venv\Scripts\python cli.py reindex                       # rebuild Chroma from .md files
.venv\Scripts\python cli.py reindex -v                    # ... and log each file
.venv\Scripts\python cli.py link                          # regenerate Tags/ pages + add Tags/Related to every note
.venv\Scripts\python cli.py group "topic name"            # build a Map of Content hub note
```

All three are idempotent.

### API endpoints (full list)
| Method | Path | Auth |
|---|---|---|
| GET  | `/api/health` | no |
| GET  | `/api/auth/status` | no |
| POST | `/api/auth/setup` | no (first-time only) |
| POST | `/api/auth/login` | no |
| GET  | `/api/config` | yes |
| POST | `/api/capture/text` | yes |
| POST | `/api/capture/voice` | yes (multipart) |
| POST | `/api/capture/image` | yes (multipart) |
| POST | `/api/capture/link` | yes |
| POST | `/api/search` | yes |
| POST | `/api/ask` | yes |
| POST | `/api/import/{chatgpt,claude,gemini}` | yes (multipart) |
| POST | `/api/import/{chatgpt,claude,gemini}/stream` | yes (multipart, SSE) |
| GET  | `/api/notes/recent` | yes |
| GET  | `/api/tags` | yes |
| GET  | `/api/settings` | yes |
| PUT  | `/api/settings` | yes |
| GET  | `/api/settings/providers` | yes |

### `.env` keys (do not read this file)
| Key | Notes |
|---|---|
| `VAULT_PATH` | Default `./vault` |
| `VAULT_NAME` | Must match Obsidian's vault switcher exactly — drives obsidian:// URLs |
| `OPENAI_API_KEY` | **Required for voice capture** (Whisper) |
| `ANTHROPIC_API_KEY` | |
| `GOOGLE_API_KEY` | |
| `ACTIVE_PROVIDER` | `openai`/`anthropic`/`google` |
| `OPENAI_MODEL` | Default `gpt-4o-mini` |
| `ANTHROPIC_MODEL` | Default `claude-sonnet-4-20250514` |
| `GOOGLE_MODEL` | Default `gemini-2.0-flash` |
| `HOST`, `PORT` | Default `0.0.0.0:8000` |
| `APP_PASSWORD` | Optional; seeds the bcrypt hash on first run |

The Settings UI in the PWA can override every provider/model/vault-name key at runtime — overrides land in `vault/_meta/config.json` and take precedence over `.env`. Empty string in a PUT clears the override.

---

## Architecture notes & caveats

- **Voice = OpenAI only.** `transcriber.py` uses the OpenAI Whisper API regardless of `ACTIVE_PROVIDER`. If the user has only Anthropic/Google keys, voice capture returns a 500 with a clear message.
- **Reverse geocoding = Nominatim, not Open-Meteo.** Open-Meteo's geocoding API is forward-only. Nominatim is free and has no key requirement, but enforces 1 req/sec — well within our 15-min cache.
- **PARA folders are 1 level deep.** Image embeds use `../08_Attachments/<file>` which works for everything except chat imports (2 levels deep). Chat imports don't have images, so safe.
- **`type=moc` skips auto-Related.** A MOC is itself a curated link list; auto-related would echo it.
- **Indexer skips `_meta/`, `Templates/`, `Tags/`.** Browse includes `Tags/` (so users can navigate tag hubs).
- **Browse cache TTL 30 s.** Invalidated explicitly after every capture/import. Manual edits in Obsidian aren't tracked — close+reopen the browse overlay or wait 30 s.
- **Frontmatter `tags` round-trip.** ChromaDB metadata can't hold lists, so tags are stored comma-joined and split back when returned by the search endpoint.
- **Service worker scope** — only caches GET shell assets; `/api/*` and POST always go to the network. Falls back to cached `/` for navigation when offline.
- **Offline queue covers text + link only.** Voice/image require binary uploads — could be added with `Blob` storage in IDB later.

---

## File inventory

```
second_brain/
├── .env                       (your real keys — gitignored, DO NOT READ)
├── .env.example               (template)
├── .gitignore                 (whitelist for vault/)
├── .venv/                     (uv-created, gitignored)
├── CLAUDE.md                  (rules for AI assistants — never touch .env)
├── CONTRIBUTING.md            (open-source contributor guide)
├── LICENSE                    (MIT)
├── README.md                  (open-source consumer-facing)
├── SECOND_BRAIN_SPEC.md       (original design spec)
├── SESSION_LOG.md             (this file)
├── cli.py                     (status, reindex, link, group)
├── run.py                     (uvicorn entry)
├── requirements.txt
├── setup_tunnel.sh / .ps1     (Cloudflare Tunnel quick-start)
│
├── app/
│   ├── auth.py
│   ├── config.py              (settings, vault_name, effective_vault_name)
│   ├── main.py                (FastAPI factory, route registration)
│   ├── models/
│   │   └── schemas.py         (every Pydantic model)
│   ├── parsers/               (chatgpt, claude, gemini, _common)
│   ├── routers/
│   │   ├── auth.py
│   │   ├── browse.py
│   │   ├── capture.py
│   │   ├── config.py
│   │   ├── import_chats.py    (JSON + SSE flavours)
│   │   ├── search.py
│   │   └── settings.py
│   └── services/
│       ├── browse.py          (vault scanner, 30 s cache)
│       ├── chat_importer.py   (iter_import generator)
│       ├── import_helpers.py  (zip extraction)
│       ├── indexer.py         (ChromaDB)
│       ├── linker.py          (Tags/Related/daily-links + Tags pages)
│       ├── llm_providers.py   (OpenAI/Anthropic/Google with vision)
│       ├── moc_builder.py     (cli.py group)
│       ├── processor.py       (capture pipeline)
│       ├── runtime_settings.py (overrides on top of .env)
│       ├── transcriber.py     (Whisper)
│       ├── vault.py           (read/write + .obsidian/graph.json seed)
│       ├── weather.py         (Open-Meteo + Nominatim, 15 min cache)
│       └── web_fetcher.py     (httpx + bs4)
│
├── frontend/
│   ├── css/style.css          (dark theme + all overlays)
│   ├── index.html             (single-page PWA)
│   ├── js/app.js              (auth, capture, search, browse, settings, import, offline queue)
│   ├── manifest.json          (no icons yet — pending)
│   ├── sw.js                  (service worker)
│   └── icons/                 (empty — pending)
│
├── docs/
│   └── screenshots/           (empty — pending)
│
└── vault/
    ├── 00_Inbox/.gitkeep      (structure tracked, content gitignored)
    ├── 01_Projects/.gitkeep
    ├── 02_Areas/.gitkeep
    ├── 03_Resources/.gitkeep
    ├── 04_Archive/.gitkeep
    ├── 05_Daily/.gitkeep
    ├── 06_Chats/{ChatGPT,Claude,Gemini}/.gitkeep
    ├── 07_References/.gitkeep
    ├── 08_Attachments/.gitkeep
    ├── Tags/.gitkeep          (linker auto-populates this)
    ├── Templates/daily.md     (only Templates content tracked)
    ├── _meta/                 (Chroma + config.json — gitignored entirely)
    └── .obsidian/             (per-machine config — gitignored entirely)
```

---

## Git state

- Initialised with `git init`, branch renamed `master → main`
- First commit: **`176450d` — "Initial commit: Second Brain personal knowledge capture system"**
- 64 files, ~6500 LOC
- `.gitignore` uses **whitelist** for `vault/`: `vault/**` ignored by default, structural `.gitkeep` files + `vault/Templates/` explicitly allowed
- Also ignored: `.env`, `.venv/`, `__pycache__/`, `.claude/` (Claude Code state), `/*.zip` and `/conversations.json` at root (your `claude_chat.zip` and `gemini_chat.zip`), `vault/_meta/`, `vault/.obsidian/`, IDE/OS noise

**No remote configured yet.** Last attempted: `gh repo create second-brain-private --private --source=. --remote=private --push` (interrupted because `gh` isn't on the sandbox PATH).

To push when you're ready:
```powershell
gh repo create second-brain-private --private --source=. --remote=private --push
# or manually:
git remote add origin <url>
git push -u origin main
```

You'll need to run this once first so plain git commands work without `-c safe.directory=...`:
```powershell
git config --global --add safe.directory 'I:/Code Space/second_brain'
```

---

## Pick-up checklist for next session

In rough priority order:

1. **Diagnose the Obsidian "block not supported" issue.** Open the affected note in Obsidian's source view; identify the failing block; fix the producer (likely `linker.py` or one of the parsers).
2. **Re-export Gemini from Google Takeout with My Activity → Gemini Apps Activity selected**, drop the new ZIP into the import overlay.
3. **Once the ChatGPT export email arrives**, drop the ZIP in (use `Limit=10` first to verify shape).
4. Take screenshots: chat capture, search results, browse view, Obsidian graph (with the seeded color groups). Save under `docs/screenshots/`.
5. Generate PWA icons (192/512), add to `frontend/icons/` + reference in `manifest.json`.
6. `git config --global --add safe.directory 'I:/Code Space/second_brain'` (one-time, for clean git UX).
7. Push: `gh repo create second-brain-private --private --source=. --remote=private --push`.

The repo is fully buildable and runnable today. Everything past the "Confirmed by user" list above is implemented but only compile-checked from my side — exercise it and report any tracebacks.
