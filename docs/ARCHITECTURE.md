# Architecture

This document describes internal module boundaries for contributors.

## UI module structure
- `ui/main_window_controller.py`:
  - top-level coordinator for screen wiring, transitions, and summary/planning orchestration
  - composes focused mixins for file actions and wizard step flow
- `ui/main_window_actions.py`:
  - save/open/new action flows and unsaved-changes decision handling
  - wraps dialog interactions behind typed helper methods to keep action logic testable
- `ui/main_window_wizard.py`:
  - wizard screen wiring and per-step calculate/save/advance behavior
  - handles transition back to main editor when wizard execution completes
- `ui/portfolio_editor_adapter.py`:
  - UI/domain mapping layer for the main editor
  - converts between tree/cash widgets, `Portfolio`, and JSON-like use-case payloads
- `ui/portfolio_metrics.py`:
  - pure recalculation service for derived table values
  - computes totals, portfolio %, strategy %, and drift from row snapshots
  - dataclasses:
    - `MetricInstrumentRow`: snapshot of one instrument row (`value_text`, target % text, row kind)
    - `MetricGroupRow`: snapshot of one top-level row plus its instrument rows
    - `MetricsSnapshot`: immutable input payload for a full recalculation pass
    - `MetricsResult`: render-ready output maps and aggregate totals
- `ui/ui_state.py`:
  - typed mutable workflow state shared by controller logic
  - enum:
    - `UnsavedChangesDecision`: typed save/discard/cancel result for unsaved-changes confirmation
  - dataclasses:
    - `PlanningState`: current generated plan (`plan_steps`), active wizard index (`step_index`), and planning mode
    - `WizardState`: per-step transient calculation cache (`last_calc`)
- `ui/screens/main_editor_screen.py`:
  - screen 1 presentation/layout (portfolio editor)
  - exposes tree/cash/action widgets for coordinator signal wiring
- `ui/screens/summary_screen.py`:
  - screen 2 presentation/layout (plan summary)
  - exposes summary text and navigation controls
- `ui/screens/wizard_screen.py`:
  - screen 3 presentation/layout (per-instrument execution wizard)
  - exposes price input, calculation feedback, and step action controls

## Test structure
- `tests/ui/test_portfolio_editor_adapter.py`:
  - unit tests for adapter mapping behavior and partial/strict input handling
- `tests/ui/test_portfolio_metrics.py`:
  - unit tests for pure recalculation rules and zero-denominator edge cases
- `tests/ui/test_screens.py`:
  - structural tests for screen modules (defaults, controls, static setup)
- `tests/ui/test_ui_state.py`:
  - unit tests for explicit planning/wizard UI state defaults and behavior
- `tests/ui/test_main_window_controller_state_flow.py`:
  - focused tests for planning/wizard state transitions and prompt/action split points in `MainWindow`
- `tests/ui/test_main_window_actions.py`:
  - focused tests for save-target resolution and unsaved-changes action decisions
- `tests/ui/test_main_window_wizard.py`:
  - focused tests for wizard step rendering, calculation flow, and step advancement behavior
- `tests/core/helpers.py`:
  - shared builders for core/domain tests (`make_valid_data`, `make_portfolio`)
- `tests/core/test_validation.py`:
  - portfolio validation invariants and JSON round-trip stability tests
- `tests/core/test_budget.py`:
  - invest-budget and future-tax-aware unit-calculation behavior tests
- `tests/core/test_planning.py`:
  - invest/rebalance planning behavior and group->instrument split tests
- `tests/core/test_calc_stock_units.py`:
  - unit-calculation and buy/sell commit mutation tests
- `tests/core/test_session_and_use_cases.py`:
  - `PortfolioSession`/`PortfolioDocument` behavior and use-case orchestration tests
