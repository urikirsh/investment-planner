# AGENTS.md

Project-level guidance for coding agents working in this repository.

## Workflow Rules

- Never commit directly to `main`.
- If the current branch is `main`, create and switch to a new feature branch before making changes.
- Always work on a feature branch.
- Commit only files touched for the requested task.
- Do not include unrelated local artifacts in commits.
- Keep commits single-purpose (for example: `fix`, `refactor`, `test`, `docs`) and avoid mixing unrelated categories.

## Required Validation After Every Code Change

Run both checks after every code change, using the project config in `pyproject.toml`:

- `py -3.13 -m mypy --config-file pyproject.toml`
- `py -3.13 -m pytest -c pyproject.toml`

Do not report completion if either command fails.

## Interpreter And Test Execution

- Use the same Python interpreter pattern as the project commands (`py -3.13`) when running tests and type checks.
- Prefer explicit config-driven invocations over implicit defaults so local/global tooling differences do not affect results.
- If you run targeted tests while iterating, still run the full required validation commands before completion.

## Testing Conventions

- Put tests in the matching module area:
  - core/domain logic -> `tests/core`
  - UI behavior -> `tests/ui`
- Reuse shared test utilities/helpers as much as possible before adding new test scaffolding.
- Shared test utility locations in this repo:
  - Core tests: `tests/core/helpers.py` (payload/model builders like `make_valid_data`, `make_portfolio`)
  - UI tests: `tests/ui/conftest.py` (shared fixtures/builders like `qapp`, `make_plan_step`, `make_buy_calculation`)
- Always accompany new code with new tests, and update existing tests when behavior/contracts change.

## Documentation Maintenance

- If any file is added or deleted, update `docs/ARCHITECTURE.md` in the same task to reflect the structural change.
- If user-facing behavior changes, update `README.md` in the same task.
- Keep documentation concise and behavior-accurate; avoid broad background text when a precise statement is enough.
- When changing user-facing text (UI labels/messages/docs), verify wording matches runtime behavior and units.

## Review Quality Rules

- For branch reviews, review changes relative to the branch merge-base with `main`.
- After fixing review findings, do a quick follow-up self-review of touched areas before handing off.
- For documentation-only changes, verify claims map to current code paths and avoid redundant repetition.

## PR Writing

- When asked for a PR title and description, provide a short description written in Markdown.
