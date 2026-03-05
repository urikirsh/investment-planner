# AGENTS.md

Project-specific guidance for coding agents working in this repository.

## Workflow Rules

- Never commit directly to `main`.
- Always work on a feature branch.
- Commit only files touched for the requested task.
- Do not include unrelated local artifacts in commits.

## Required Validation After Every Code Change

Run both checks after each new code change, using the project config in `pyproject.toml`:

- `py -3.13 -m mypy --config-file pyproject.toml`
- `py -3.13 -m pytest -c pyproject.toml`

Do not report completion if either command fails.

## Testing Conventions

- Put tests in the matching module area:
  - core/domain logic -> `tests/core`
  - UI behavior -> `tests/ui`
- Reuse shared test utilities/helpers whenever possible before adding new test scaffolding.
- Shared test utility locations in this repo:
  - Core tests: `tests/core/helpers.py` (payload/model builders like `make_valid_data`, `make_portfolio`)
  - UI tests: `tests/ui/conftest.py` (shared fixtures/builders like `qapp`, `make_plan_step`, `make_buy_calculation`)
- Keep tests focused and close to the behavior being changed.
- After adding tests, check whether repeated setup/helpers now justify extraction into shared utility files.
- Only extract when reuse is significant (i.e., meaningfully reduces duplicated test code), not for one-off or minor duplication.

## Data File Hygiene

- Keep personal/local portfolio JSON files untracked by default.
- Do not add local portfolio data files unless explicitly requested.

## PR Description Behavior

- Only generate PR descriptions when explicitly requested by the user.
- When requested, provide the PR description in Markdown format in chat.
- Do not auto-generate PR description files unless explicitly requested.

## Clarification Policy

- If requirements are underspecified, ask concise multiple-choice clarifying questions before implementing.

## Documentation Maintenance

- If code structure changes, update `docs/ARCHITECTURE.md` in the same task:
  - adding/removing code files
  - moving significant functionality between files/modules
- If user-facing behavior changes, update `README.md` in the same task.
