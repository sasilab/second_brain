# Contributing

Thanks for your interest in Second Brain. This is a small project — fixes, ideas, and PRs are all welcome.

## Setup

```bash
git clone <your-fork>
cd second-brain
uv venv && uv pip install -r requirements.txt    # or python -m venv .venv && pip install -r ...
cp .env.example .env                              # add at least one provider API key
python run.py                                     # http://localhost:8000
```

The vault is created on first launch (`./vault` by default; override with `VAULT_PATH` in `.env`).

## Project layout

See [`README.md`](./README.md#architecture) for the high-level diagram and the file tree under `app/`.

For a deeper read, [`SECOND_BRAIN_SPEC.md`](./SECOND_BRAIN_SPEC.md) §18 lists the build order in the same sequence the codebase grew — it's a good orientation map.

## Running locally

| Task | Command |
|---|---|
| Start the dev server | `python run.py` (no auto-reload — restart for code changes) |
| Compile-check every `.py` | `python -m py_compile $(git ls-files '*.py')` |
| Rebuild vector index from disk | `python cli.py reindex -v` |
| Show config / index size | `python cli.py status` |

There is **no test suite yet** — adding pytest coverage is a great first contribution.

## Code style

- Python 3.11+ (uses `X \| Y` unions, `dict[str, Any]`, etc.)
- Type hints where they aid clarity; not strict mypy
- Each `app/services/*.py` module has one job — keep them orthogonal
- Comments only for non-obvious *why* (hidden constraints, workarounds, surprising behavior). Well-named identifiers handle the *what*
- Frontend: vanilla JS, no build step, no framework. Keep it that way unless there's a strong reason

## Pull requests

- Branch from `main`
- One feature/fix per PR; keep diffs focused
- Update `README.md` if you add a user-facing endpoint, CLI command, or env key
- Update `SECOND_BRAIN_SPEC.md` if you change architecture
- Verify `python -m py_compile` passes before pushing

## Issues

Use GitHub Issues. For bugs, please include:

- OS + Python version
- Active LLM provider + model
- Full traceback (**redact API keys**)
- Minimal repro steps

## Security

If you find a vulnerability that could leak data or credentials, please email the maintainer privately rather than opening a public issue.

## Licence

By contributing you agree that your contributions are licensed under the [MIT License](./LICENSE).
