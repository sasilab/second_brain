# Second Brain — Project Specification

## 1. Vision

A personal knowledge management system where you capture thoughts like sending a WhatsApp message — text, voice notes, images — and AI automatically organizes everything into your Obsidian vault. You also import all past AI conversations (ChatGPT, Claude, Gemini) into the same brain. Two interfaces: a PWA chat app for capturing, Obsidian for browsing and connecting.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              CAPTURE INTERFACE                   │
│                                                  │
│  PWA Chat App (public URL via Cloudflare Tunnel) │
│  • Text messages                                 │
│  • Voice notes → Whisper transcription           │
│  • Images → AI description + OCR                 │
│  • Links → fetch & summarize                     │
│  • Questions → semantic search, get answers      │
│  • Offline queue when backend is unavailable      │
│                                                  │
│  Accessible from: iPhone, iPad, PC, laptop       │
└──────────────────────┬──────────────────────────┘
                       │ HTTPS
                       ▼
┌─────────────────────────────────────────────────┐
│              FASTAPI BACKEND                     │
│                                                  │
│  Runs on PC (later VPS)                          │
│  Cloudflare Tunnel → public HTTPS URL            │
│                                                  │
│  Processing pipeline:                            │
│  1. Receive input (text/image/voice/link)        │
│  2. Convert (voice→text, image→description)      │
│  3. Categorize (journal/idea/reference/task)      │
│  4. Generate tags                                │
│  5. Summarize                                    │
│  6. Write markdown to correct vault folder       │
│  7. Update vector index                          │
│                                                  │
│  Additional endpoints:                           │
│  • Semantic search across vault                  │
│  • Chat import (upload JSON exports)             │
│  • Settings (API keys, provider selection)        │
│  • Auth (password login)                         │
└──────────────────────┬──────────────────────────┘
                       │ writes .md files
                       ▼
┌─────────────────────────────────────────────────┐
│              OBSIDIAN VAULT                       │
│                                                  │
│  Plain markdown files with YAML frontmatter      │
│  ChromaDB vector index in _meta/                 │
│  Syncs to all devices via Obsidian Sync/iCloud   │
└─────────────────────────────────────────────────┘
```

---

## 3. Tech Stack

| Component            | Technology                          | Why                                      |
|----------------------|-------------------------------------|------------------------------------------|
| Backend framework    | FastAPI (Python 3.11+)              | Async, fast, easy to deploy              |
| Capture UI           | HTML + CSS + JS (PWA)               | No framework needed, lightweight, installable |
| Voice transcription  | OpenAI Whisper API                  | Best accuracy, simple API                |
| Image understanding  | GPT-4o / Claude vision              | Describe images, extract text (OCR)      |
| LLM processing       | OpenAI / Anthropic / Google (switchable) | Auto-tag, summarize, categorize      |
| Vector search        | ChromaDB (local, file-based)        | No server needed, persists to disk       |
| Metadata store       | SQLite                              | Lightweight, file-based, queryable       |
| Note storage         | Markdown files (Obsidian vault)     | Universal, no lock-in                    |
| Public access        | Cloudflare Tunnel (cloudflared)     | Free, HTTPS, no static IP needed         |
| Auth                 | Simple password + session token     | Single-user app, keep it simple          |

---

## 4. Vault Folder Structure (PARA-inspired hybrid)

```
SecondBrain/
├── 00_Inbox/              ← temporary landing zone
├── 01_Projects/           ← active, has a deadline
├── 02_Areas/              ← ongoing responsibilities (health, career, finances)
├── 03_Resources/          ← reference topics (Python tips, AI research)
├── 04_Archive/            ← completed/inactive
├── 05_Daily/              ← daily journal notes (2026-05-14.md)
├── 06_Chats/              ← imported AI conversations
│   ├── ChatGPT/
│   ├── Claude/
│   └── Gemini/
├── 07_References/         ← saved links, articles, images
├── 08_Attachments/        ← images, voice note transcripts, files
├── Templates/             ← daily note template, chat import template
└── _meta/                 ← ChromaDB, SQLite, config (excluded from sync)
    ├── chroma/            ← vector database files
    ├── second_brain.db    ← SQLite metadata
    └── config.json        ← app settings
```

### Why this structure:

- `00-04` follow PARA for purpose-based organization
- `05_Daily` is separate because daily notes are chronological, not purpose-based
- `06_Chats` keeps imported conversations grouped by source
- `07_References` collects links and saved content
- `08_Attachments` stores binary files referenced from notes
- `_meta` holds system files that should NOT sync to other devices

---

## 5. Note Format

Every note is a markdown file with YAML frontmatter:

```markdown
---
id: uuid-here
source: pwa | chatgpt | claude | gemini | browser
type: journal | idea | reference | task | chat | voice | image
date: 2026-05-14T09:30:00
tags: [meeting, api-design, tom]
summary: Good meeting with Tom about new API design direction.
category: 02_Areas/career
---

# Meeting with Tom — API Design

Had a great meeting with Tom about the new API design.
We decided to go with REST instead of GraphQL for the
public endpoints. He'll send mockups by Friday.
```

### Frontmatter fields:

| Field      | Description                                      | Auto-generated? |
|------------|--------------------------------------------------|-----------------|
| `id`       | UUID for deduplication                           | Yes             |
| `source`   | Where it came from                               | Yes             |
| `type`     | Content type                                     | Yes (AI)        |
| `date`     | Creation timestamp                               | Yes             |
| `tags`     | 3-7 relevant tags                                | Yes (AI)        |
| `summary`  | 1-3 sentence summary                             | Yes (AI)        |
| `category` | PARA folder it belongs in                        | Yes (AI)        |

---

## 6. Backend API Design

### 6.1 Authentication

Single-user app. Simple password-based auth.

```
POST /api/auth/login
  Body: { "password": "..." }
  Returns: { "token": "session-token" }

All other endpoints require header:
  Authorization: Bearer <session-token>
```

Password is hashed (bcrypt) and stored in `_meta/config.json`. On first run, prompt user to set a password.

### 6.2 Capture Endpoints

```
POST /api/capture/text
  Body: { "content": "Had a great meeting with Tom..." }
  Returns: { "id": "uuid", "filed_to": "05_Daily/2026-05-14.md", "tags": [...] }

POST /api/capture/voice
  Body: multipart/form-data with audio file
  Pipeline: Whisper transcription → text processing → file
  Returns: { "id": "uuid", "transcript": "...", "filed_to": "..." }

POST /api/capture/image
  Body: multipart/form-data with image file
  Pipeline: Save to 08_Attachments → AI description → create note linking to image
  Returns: { "id": "uuid", "description": "...", "filed_to": "..." }

POST /api/capture/link
  Body: { "url": "https://..." }
  Pipeline: Fetch page → summarize → save as reference note
  Returns: { "id": "uuid", "title": "...", "summary": "...", "filed_to": "..." }
```

### 6.3 Search Endpoints

```
POST /api/search
  Body: { "query": "Docker networking discussion", "limit": 10 }
  Returns: { "results": [{ "id": "...", "title": "...", "snippet": "...", "score": 0.87, "path": "..." }] }

POST /api/ask
  Body: { "question": "What did I learn about Docker last week?" }
  Pipeline: Semantic search → retrieve top chunks → LLM answers using context
  Returns: { "answer": "Based on your notes...", "sources": [...] }
```

### 6.4 Import Endpoints

```
POST /api/import/chatgpt
  Body: multipart/form-data with conversations.json
  Pipeline: Parse → split conversations → for each: summarize, tag, save as .md
  Returns: { "imported": 142, "failed": 0 }

POST /api/import/claude
  Body: multipart/form-data with claude export JSON
  Returns: { "imported": 87, "failed": 0 }

POST /api/import/gemini
  Body: multipart/form-data with gemini export
  Returns: { "imported": 56, "failed": 0 }
```

### 6.5 Settings Endpoints

```
GET /api/settings
  Returns current settings (providers, active provider, models)

PUT /api/settings
  Body: { "active_provider": "openai", "openai_api_key": "sk-...", ... }
  Stores encrypted in _meta/config.json

GET /api/settings/providers
  Returns: [
    { "name": "openai", "display": "OpenAI (GPT)", "configured": true, "models": ["gpt-4o-mini", "gpt-4o"] },
    { "name": "anthropic", "display": "Anthropic (Claude)", "configured": false, "models": [...] },
    { "name": "google", "display": "Google (Gemini)", "configured": false, "models": [...] }
  ]
```

### 6.6 Browse Endpoints

```
GET /api/notes/recent?limit=20&offset=0
  Returns recent notes with metadata

GET /api/notes/{id}
  Returns full note content

GET /api/notes/by-date/{date}
  Returns daily note for given date

GET /api/tags
  Returns all tags with counts

GET /api/notes/by-tag/{tag}
  Returns all notes with given tag
```

---

## 7. PWA Chat Interface

### 7.1 Design

WhatsApp-style chat interface:
- Dark theme (easy on the eyes, matches Obsidian dark mode)
- Your messages on the right (blue/green bubble)
- System confirmations on the left (gray bubble)
- Bottom input bar with: text field, mic button (hold to record), attach button (image/file), send button
- Top bar with: app name, search icon, settings gear

### 7.2 Pages / Views

1. **Chat (main view)** — the WhatsApp-like capture interface
2. **Search** — semantic search bar + results list
3. **Import** — upload chat exports (ChatGPT/Claude/Gemini), shows progress
4. **Settings** — API keys, active provider, password change
5. **Browse** — recent notes, filter by tag/date/source (simple list view)

### 7.3 Offline Behavior

When the backend is unreachable:
- User can still type messages
- Messages stored in IndexedDB with status "queued"
- Visual indicator: "Offline — messages will sync when connected"
- On reconnect: auto-send queued messages in order
- Queued messages show a clock icon instead of checkmark

### 7.4 PWA Requirements

- `manifest.json` for installability
- Service worker for offline caching of the app shell
- Icons (simple brain/note icon, multiple sizes)
- Theme color matching the dark UI

### 7.5 Input Handling

| User action            | What happens in UI                     | What's sent to backend         |
|------------------------|----------------------------------------|--------------------------------|
| Type text + send       | Message appears in chat                | POST /api/capture/text         |
| Hold mic + release     | Recording indicator → "Transcribing…"  | POST /api/capture/voice        |
| Attach image + send    | Image thumbnail in chat                | POST /api/capture/image        |
| Paste URL + send       | Link preview appears                   | POST /api/capture/link         |
| Type "?" prefix        | Treated as a question                  | POST /api/ask                  |

The "?" prefix convention: if a message starts with "?", it's a query (don't save, just answer). Otherwise it's a capture (save to vault). Alternatively, a toggle/mode switch in the UI.

---

## 8. LLM Provider System

### 8.1 Provider Abstraction

```python
class LLMProvider(ABC):
    name: str
    display_name: str

    @abstractmethod
    def complete(self, prompt: str, system: str = "") -> str: ...

    def summarize(self, text: str) -> str: ...
    def generate_tags(self, text: str) -> list[str]: ...
    def categorize(self, text: str) -> dict: ...
    def answer_query(self, query: str, context_chunks: list[str]) -> str: ...
```

### 8.2 Supported Providers

| Provider   | Class             | Models                          |
|------------|-------------------|---------------------------------|
| OpenAI     | OpenAIProvider    | gpt-4o-mini (default), gpt-4o  |
| Anthropic  | AnthropicProvider | claude-sonnet-4-20250514        |
| Google     | GoogleProvider    | gemini-2.0-flash (default)      |

### 8.3 Adding New Providers

To add a new provider:
1. Create a new class extending `LLMProvider`
2. Implement `is_configured()` and `complete()`
3. Register in the `PROVIDERS` dict
4. Add to settings UI

The base class provides default implementations of `summarize()`, `generate_tags()`, `categorize()`, and `answer_query()` that call `complete()` with appropriate prompts.

---

## 9. AI Processing Pipeline

When a new capture arrives, the backend runs this pipeline:

```
Input (text/voice/image/link)
  │
  ├─ [voice] → Whisper API → transcript text
  ├─ [image] → Vision API → description text + save file
  ├─ [link]  → fetch URL → extract content → text
  └─ [text]  → use as-is
  │
  ▼
Categorization prompt:
  "Given this content, classify it as one of:
   journal, idea, reference, task, chat, voice, image.
   Also determine the best PARA folder:
   01_Projects, 02_Areas, 03_Resources.
   If it's a daily thought/reflection, use 05_Daily."
  │
  ▼
Tag generation prompt:
  "Generate 3-7 short tags for this content.
   Return only a JSON array."
  │
  ▼
Summary prompt:
  "Summarize this in 1-3 sentences."
  │
  ▼
Write markdown file:
  - Generate YAML frontmatter (id, source, type, date, tags, summary, category)
  - Write content below frontmatter
  - Save to determined folder path
  - If daily journal entry → append to today's daily note instead of creating new file
  │
  ▼
Update vector index:
  - Chunk the content
  - Generate embeddings
  - Store in ChromaDB with metadata
```

### 9.1 Daily Note Handling

Daily journal entries are special — they APPEND to the day's file rather than creating separate files:

```markdown
---
date: 2026-05-14
type: daily
tags: [journal]
---

# Wednesday, May 14, 2026

## 09:30
Had a great meeting with Tom about the new API design.
We decided to go with REST instead of GraphQL.

## 14:15
🎙️ Voice note: Need to remember to buy groceries —
milk, eggs, bread, and that special cheese from the market.

## 16:45
📷 [Image: whiteboard-photo.jpg](../08_Attachments/2026-05-14-whiteboard.jpg)
Architecture diagram from the team meeting. Shows the
microservices layout with the new auth service in the middle.
```

Each capture that's categorized as "journal" gets appended with a timestamp header.

---

## 10. Chat Import Parsers

### 10.1 ChatGPT Export Format

ChatGPT exports as `conversations.json` — an array of conversation objects.

```python
# Structure:
# [{ "title": "...", "create_time": 1234567890, "mapping": { node_id: { "message": { "content": { "parts": [...] } } } } }]

def parse_chatgpt(file_path: str) -> list[dict]:
    """
    Parse ChatGPT export JSON.
    Returns list of { title, date, messages: [{ role, content }] }
    """
    # Each conversation becomes one .md file in 06_Chats/ChatGPT/
    # Filename: YYYY-MM-DD-slugified-title.md
```

### 10.2 Claude Export Format

Claude exports conversations as JSON. The structure may vary — handle gracefully.

```python
def parse_claude(file_path: str) -> list[dict]:
    """
    Parse Claude export JSON.
    Returns list of { title, date, messages: [{ role, content }] }
    """
    # Each conversation becomes one .md file in 06_Chats/Claude/
```

### 10.3 Gemini Export Format

Gemini exports via Google Takeout as JSON files.

```python
def parse_gemini(file_path: str) -> list[dict]:
    """
    Parse Gemini/Google Takeout export.
    Returns list of { title, date, messages: [{ role, content }] }
    """
    # Each conversation becomes one .md file in 06_Chats/Gemini/
```

### 10.4 Imported Chat Note Format

```markdown
---
id: uuid
source: chatgpt
type: chat
date: 2026-03-15T14:30:00
tags: [python, web-scraping, beautifulsoup]
summary: Discussion about scraping product prices using BeautifulSoup and handling pagination.
original_title: "Web Scraping Help"
---

# Web Scraping Help

**User:** How do I scrape prices from an e-commerce site?

**Assistant:** You can use BeautifulSoup with requests...

**User:** What about pagination?

**Assistant:** For pagination, you'll want to...
```

### 10.5 Import Processing

For large exports (hundreds of conversations):
- Process in batches (10 at a time)
- LLM calls for summary/tags are the bottleneck — use async where possible
- Show progress in the UI via SSE (Server-Sent Events)
- Allow skipping LLM processing (import raw, process later)
- Deduplication: check if a conversation with the same title + date already exists

---

## 11. Semantic Search (ChromaDB)

### 11.1 Setup

```python
import chromadb

client = chromadb.PersistentClient(path="vault/_meta/chroma")
collection = client.get_or_create_collection(
    name="second_brain",
    metadata={"hnsw:space": "cosine"}
)
```

### 11.2 Indexing

When a note is created or updated:

```python
def index_note(note_path: str, content: str, metadata: dict):
    """
    Chunk content, generate embeddings, store in ChromaDB.
    """
    chunks = chunk_text(content, max_tokens=500, overlap=50)
    for i, chunk in enumerate(chunks):
        collection.upsert(
            ids=[f"{metadata['id']}_chunk_{i}"],
            documents=[chunk],
            metadatas=[{
                "note_id": metadata["id"],
                "source": metadata["source"],
                "type": metadata["type"],
                "date": metadata["date"],
                "path": note_path,
                "tags": ",".join(metadata.get("tags", []))
            }]
        )
```

### 11.3 Querying

```python
def search(query: str, limit: int = 10, filters: dict = None):
    """
    Semantic search across the vault.
    Optional filters: source, type, date_range, tags.
    """
    where = {}
    if filters:
        if "source" in filters:
            where["source"] = filters["source"]
        if "type" in filters:
            where["type"] = filters["type"]

    results = collection.query(
        query_texts=[query],
        n_results=limit,
        where=where if where else None
    )
    return results
```

### 11.4 Re-indexing

Provide a CLI command to rebuild the entire index from vault files:

```bash
python -m second_brain.cli reindex
```

This scans all `.md` files in the vault, parses frontmatter, and rebuilds ChromaDB. Safe to run anytime — uses upsert so it's idempotent.

---

## 12. Project File Structure

```
second-brain/
├── README.md                  ← setup instructions
├── requirements.txt           ← Python dependencies
├── .env.example               ← API key template
├── .env                       ← actual API keys (gitignored)
├── run.py                     ← entry point: starts FastAPI server
│
├── app/
│   ├── __init__.py
│   ├── main.py                ← FastAPI app, CORS, middleware
│   ├── config.py              ← settings, paths, env loading
│   ├── auth.py                ← password hashing, session tokens
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── capture.py         ← text/voice/image/link capture endpoints
│   │   ├── search.py          ← semantic search + ask endpoints
│   │   ├── import_chats.py    ← ChatGPT/Claude/Gemini import endpoints
│   │   ├── browse.py          ← list notes, filter, read endpoints
│   │   └── settings.py        ← API keys, provider config endpoints
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_providers.py   ← provider abstraction + OpenAI/Anthropic/Google
│   │   ├── processor.py       ← AI pipeline (categorize, tag, summarize)
│   │   ├── vault.py           ← read/write markdown files to vault
│   │   ├── indexer.py         ← ChromaDB indexing + search
│   │   ├── transcriber.py     ← Whisper voice transcription
│   │   └── web_fetcher.py     ← fetch + extract content from URLs
│   │
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── chatgpt.py         ← ChatGPT JSON export parser
│   │   ├── claude.py          ← Claude export parser
│   │   └── gemini.py          ← Gemini/Takeout export parser
│   │
│   └── models/
│       ├── __init__.py
│       └── schemas.py         ← Pydantic models for all request/response
│
├── frontend/                  ← PWA static files
│   ├── index.html             ← main chat interface
│   ├── manifest.json          ← PWA manifest
│   ├── sw.js                  ← service worker (offline support)
│   ├── css/
│   │   └── style.css          ← dark theme, chat bubbles
│   ├── js/
│   │   ├── app.js             ← main app logic
│   │   ├── chat.js            ← chat UI + message handling
│   │   ├── recorder.js        ← voice recording
│   │   ├── offline.js         ← IndexedDB queue for offline
│   │   ├── search.js          ← search page logic
│   │   ├── import.js          ← import page logic
│   │   └── settings.js        ← settings page logic
│   └── icons/
│       ├── icon-192.png
│       └── icon-512.png
│
├── vault/                     ← Obsidian vault (or symlink to existing vault)
│   ├── 00_Inbox/
│   ├── 01_Projects/
│   ├── 02_Areas/
│   ├── 03_Resources/
│   ├── 04_Archive/
│   ├── 05_Daily/
│   ├── 06_Chats/
│   │   ├── ChatGPT/
│   │   ├── Claude/
│   │   └── Gemini/
│   ├── 07_References/
│   ├── 08_Attachments/
│   ├── Templates/
│   │   └── daily.md
│   └── _meta/
│       └── .gitkeep
│
├── cli.py                     ← CLI commands (reindex, import, etc.)
└── setup_tunnel.sh            ← Cloudflare Tunnel setup script
```

---

## 13. Environment & Configuration

### .env.example

```env
# Second Brain Configuration

# Vault path (absolute or relative)
VAULT_PATH=./vault

# API Keys (add the ones you have)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=

# Active LLM provider: openai | anthropic | google
ACTIVE_PROVIDER=openai

# OpenAI model (for completions)
OPENAI_MODEL=gpt-4o-mini

# Anthropic model
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# Google model
GOOGLE_MODEL=gemini-2.0-flash

# Server
HOST=0.0.0.0
PORT=8000

# App password (set on first run if empty)
APP_PASSWORD=
```

---

## 14. Setup & Run Instructions

### First-time setup

```bash
# 1. Clone / download the project
cd second-brain

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and edit environment file
cp .env.example .env
# Edit .env — add at least one API key

# 5. Point to your existing Obsidian vault (optional)
# Either edit VAULT_PATH in .env, or create a symlink:
# ln -s /path/to/your/obsidian/vault ./vault

# 6. Run the server
python run.py

# 7. Open in browser
# Local: http://localhost:8000
# First visit: set your password
```

### Cloudflare Tunnel (public access)

```bash
# 1. Install cloudflared
# Mac: brew install cloudflare/cloudflare/cloudflared
# Linux: see https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/

# 2. Login (one-time)
cloudflared login

# 3. Create tunnel
cloudflared tunnel create second-brain

# 4. Run tunnel (points to your local server)
cloudflared tunnel --url http://localhost:8000

# This gives you a public URL like:
# https://random-name.trycloudflare.com
# Or set up a custom domain if you have one
```

---

## 15. Phase 2 — Future Enhancements

These are NOT part of the initial build. Documenting for later.

### 15.1 Browser History Import
- Chrome history is a SQLite file at `~/.config/google-chrome/Default/History`
- Read URLs + titles + timestamps
- Batch summarize with LLM
- Save as reference notes

### 15.2 VPS Migration
- Move to Hetzner CX22 (~€4.50/mo, Frankfurt)
- Same code, just runs on the server
- Vault syncs via Obsidian Sync or Git
- No more Cloudflare Tunnel needed (direct domain)

### 15.3 AI-Maintained Index
- Inspired by obsidian-deep-wiki
- Auto-generate index/MOC (Map of Content) pages
- Cross-link related notes automatically
- Weekly "digest" summarizing themes

### 15.4 Calendar/Timeline View
- Visual timeline of all captures
- Filter by type, source, tag
- See patterns (when you're most productive, what topics cluster)

### 15.5 Obsidian Plugin
- Optional companion plugin
- Quick capture from within Obsidian
- Shows AI suggestions inline

---

## 16. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Vault format | Plain markdown + YAML frontmatter | No lock-in, Obsidian-native, readable anywhere |
| Folder structure | PARA hybrid | Proven system, AI can auto-categorize into it |
| Vector DB | ChromaDB (local) | No server, persists to disk, rebuilt from files |
| Auth | Simple password + token | Single-user personal app, no OAuth complexity |
| PWA vs native app | PWA | Cross-platform, no app store, installable |
| Offline strategy | IndexedDB queue | Captures aren't lost when PC is off |
| Daily notes | Append mode | One file per day, not per thought |
| Chat imports | Batch with progress | Large exports need progress indication |
| LLM providers | Pluggable base class | Easy to add Ollama, Mistral, etc. later |
| Embeddings | ChromaDB default (all-MiniLM-L6-v2) | Good enough for personal use, runs locally |

---

## 17. Non-Goals (Explicitly Out of Scope)

- Multi-user support
- Real-time collaboration
- Mobile native apps
- Complex permission systems
- Social/sharing features
- Self-hosted LLM (v1 uses API providers)

---

## 18. Build Order

When building, follow this sequence:

1. **Project scaffolding** — file structure, requirements, config loading
2. **LLM provider system** — base class + OpenAI + Anthropic + Google implementations
3. **Vault service** — read/write markdown files, frontmatter parsing
4. **AI processing pipeline** — categorize, tag, summarize using LLM
5. **FastAPI app** — auth + capture endpoints (text first)
6. **PWA frontend** — chat UI, text capture working end-to-end
7. **Voice capture** — Whisper integration + mic recording in frontend
8. **Image capture** — vision API + file attachment in frontend
9. **Link capture** — URL fetching + summarization
10. **ChromaDB indexer** — indexing on capture + search endpoint
11. **Chat importers** — ChatGPT parser first, then Claude, then Gemini
12. **Import UI** — upload page with progress
13. **Search UI** — search page in PWA
14. **Browse UI** — list/filter notes
15. **Settings UI** — API keys, provider switching
16. **Offline queue** — IndexedDB + service worker
17. **Cloudflare Tunnel setup** — script + instructions
18. **Testing + polish**

---

*This spec is designed to be handed to Claude Code. It contains everything needed to build the complete system. Start with step 1 and work through sequentially.*
