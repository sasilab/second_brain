# Claude Code instructions for this repo

## Project

Second Brain — personal knowledge capture system. PWA chat frontend → FastAPI backend → Obsidian vault (markdown + YAML frontmatter) + ChromaDB index.

The full design lives in [`SECOND_BRAIN_SPEC.md`](./SECOND_BRAIN_SPEC.md). Read it first when picking up new work. The build order is in section 18.

## Hard rules

### Secrets — never touch `.env`

The `.env` file in the project root contains live API keys (OpenAI, Anthropic, Google).

- **Never** read it (no `Read`, `cat`, `Get-Content`, `type`, `head`, `tail`, etc.)
- **Never** edit it (no `Edit`, `Write`, `sed`, redirection, etc.)
- **Never** display, print, log, or echo its contents — including via `python -c`, `printenv`, `Get-ChildItem env:`, or any shell expansion of `$env:OPENAI_API_KEY` and friends
- **Never** include it in `git add`, screenshots, debug output, error messages, or anywhere the value could leak

If the user needs to change a setting, **tell them which key to edit manually** in `.env` (e.g. "set `ACTIVE_PROVIDER=anthropic` in `.env`"). Do not ask them to paste the current value back.

If a stack trace would expose a key, redact it before showing the user.

`.env.example` (the template, no real values) is fine to read and edit.

## Useful pointers

- Vault layout, note format, and folder semantics: spec §4–§5
- LLM provider abstraction: `app/services/llm_providers.py`
- AI pipeline (categorize/tag/summarize): `app/services/processor.py`
- Markdown read/write + daily-note append: `app/services/vault.py`
- Auth (bcrypt hash in `vault/_meta/config.json`, bearer tokens in memory): `app/auth.py`
- Settings & vault paths: `app/config.py`
- Run the dev server: `python run.py`
- Health check: `GET /api/health`
