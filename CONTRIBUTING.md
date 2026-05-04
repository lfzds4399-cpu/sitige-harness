# Contributing

Thanks for your interest. PRs are welcome — small focused ones get reviewed fastest.

## Setup

```bash
git clone https://github.com/lfzds4399-cpu/sitige-harness.git
cd sitige-harness
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,api,observability,scheduling,storage]"
pre-commit install
```

## Run quality gates locally

```bash
ruff check .
mypy src
bandit -r src
pytest -q
```

CI runs the same suite. Keep coverage above the floor in `pyproject.toml`.

## Commit conventions

- Imperative tense: `fix: handle empty manifest` — not `fixed` or `fixes`
- One concern per commit
- If your change is user-visible, add a line to `CHANGELOG.md` under `## [Unreleased]`

## Adding a new pipeline / agent / validator

1. **Validator** — pure function, signature `def validate(payload, ctx) -> ValidationResult`. Add to `src/tetra_harness/validators/`. Cover with unit tests in `tests/test_validators.py`.
2. **Agent** — async class deriving from `BaseAgent`. Add to `src/tetra_harness/agents/`. Mock LLM calls in tests; the suite must run offline.
3. **Pipeline** — subclass `BasePipeline`, declare stages. Add YAML manifest in `configs/<name>.yaml`. End-to-end test in `tests/test_pipelines.py`.

## What NOT to commit

- `.env` — only `.env.example`. Never commit live keys.
- Run artifacts under `data/` (already gitignored, but double-check).
- Database files (`*.db`).
- Large fixtures — use small synthetic data.

## Reporting bugs

Open a GitHub issue with: minimal repro, expected vs actual, Python version, traceback (if any). Use the issue template.

## Security

Don't open a public issue for vulnerabilities. See [SECURITY.md](SECURITY.md).
