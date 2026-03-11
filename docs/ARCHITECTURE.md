# Architecture

This document is for contributors and explains how the GUI layer, domain layer,
and tests are organized.

## Design intent
- Keep `MainWindow` as an orchestration entry point, not a monolithic logic file.
- Keep heavy business logic in `portfolio_core`.
- Keep UI-only mapping/recalculation logic in explicit `ui/*` modules.
- Keep dialog and state transitions testable through seam-oriented methods.

## Layering and dependencies
High-level dependency direction:

1. `ui/screens/*` provides widget composition only.
2. `ui/main_window_controller.py` composes screens and delegates per-screen logic.
3. `ui/controllers/*` contains focused composed controller objects by concern.
4. `ui/main_window_actions.py` and `ui/main_window_wizard.py` handle focused
   action/wizard flows.
5. `ui/portfolio_editor_adapter.py` maps between widgets and domain payloads.
6. `portfolio_core/*` performs validation, planning, persistence, and calculations.

Rule of thumb: `portfolio_core` must not import from `ui`.

## Runtime flow
Main user flow:

1. Welcome screen handles startup choices (`open last`, `load`, `start new`, `quit`).
2. Main editor captures current portfolio values.
3. Save/Open/New actions go through `MainWindowActionsMixin`.
4. Planning (`invest`/`rebalance`) is built in `portfolio_core.use_cases`.
5. Summary screen presents generated plan steps.
6. Wizard execution is managed by `MainWindowWizardMixin`.
7. Completed wizard flow repopulates the main editor and returns to screen 2.

FX thread-safety guards in this flow:
- Wizard FX fetch uses generation tokens so stale async completions are ignored.
- Starting a new wizard run requires successful cancellation of any previous in-flight FX thread.
- Window close waits for FX-thread shutdown (up to 12 seconds); close is blocked with a user-visible message if shutdown does not complete in time.

## Controller composition rules
- `MainWindow` is the composition root and owns long-lived controller instances.
- Prefer direct signal wiring to composed controller methods for single-hop UI actions.
- Keep `MainWindow` wrappers only when they are required by:
  - `MainWindowActionsMixin` / `MainWindowWizardMixin` host-method contracts, or
  - stable test seams for cross-controller orchestration points.
- New screen behavior should be added to a dedicated controller object under `ui/controllers/*`, not as inline `MainWindow` logic.

## UI module map
- `ui/main_window_controller.py`
  - thin composition root for welcome/main/summary/wizard wiring and transitions
  - composes focused controller objects from `ui/controllers/*`
  - wires most Qt signals directly to composed controller methods
  - keeps thin wrapper methods only for cross-flow contracts used by actions/wizard flows and tests
  - guards window close until in-flight wizard FX fetch thread is safely stopped
- `ui/controllers/main_window_welcome.py`
  - `MainWindowWelcomeController`: welcome setup, remembered-path status rendering, startup transitions
- `ui/controllers/main_window_main_editor.py`
  - `MainWindowMainEditorController`: editor wiring and direct row-level add/delete/new-document actions
- `ui/controllers/main_window_table_editing.py`
  - `MainWindowTableEditingController`: tree item normalization and validation/revert behavior
- `ui/controllers/main_window_metrics.py`
  - `MainWindowMetricsController`: derived totals/percentages/drift refresh and visual state updates
- `ui/controllers/main_window_summary.py`
  - `MainWindowSummaryController`: summary setup and summary->wizard/main navigation behavior
- `ui/controllers/protocols.py`
  - protocol contracts for controller-host dependencies
  - keeps controller object composition statically typed without MRO coupling
- `ui/constants.py`
  - shared static UI constants used by multiple UI modules
- `ui/main_window_actions.py`
  - save/open/new action flows and unsaved-changes decision handling
  - wraps dialog interactions behind typed helper methods to keep action logic testable
- `ui/main_window_wizard.py`
  - wizard screen wiring and per-step calculate/save/advance behavior
  - handles transition back to main editor when wizard execution completes
- `ui/wizard_fx_coordinator.py`
  - extracted FX-only coordinator used by `MainWindowWizardMixin`
  - owns transient USD/ILS FX orchestration for wizard runs:
    - one-at-most BOI fetch attempt per wizard run (only when USD steps exist)
    - non-blocking background BOI fetch (wizard opens immediately)
    - USD-step calculate disabled while fetch is in progress (up to 10 seconds)
    - generation-token guard so stale async completions are ignored
    - explicit cancel-failure handling before starting new fetch/reset/finish transitions
    - fallback manual USD/ILS override state (wizard-run scoped, non-persistent)
- `ui/exchange_delegate.py`
  - combo-box delegate for instrument exchange editing in the main tree (`TASE`/`NYSE`)
- `ui/ticker_input_delegate.py`
  - line-edit delegate for instrument ticker editing
  - enforces live ASCII alphanumeric-only input while allowing empty interim text
  - required/exact exchange-specific ticker format is validated at save/planning time
- `ui/portfolio_editor_adapter.py`
  - UI/domain mapping layer for the main editor
  - converts between tree/cash widgets, `Portfolio`, and JSON-like use-case payloads
- `ui/portfolio_metrics.py`
  - pure recalculation service for derived table values
  - computes totals, portfolio %, strategy %, and drift from row snapshots
  - core dataclasses:
    - `MetricInstrumentRow`: snapshot of one instrument row (`value_text`, target % text, row kind)
    - `MetricGroupRow`: snapshot of one top-level row plus its instrument rows
    - `MetricsSnapshot`: immutable input payload for a full recalculation pass
    - `MetricsResult`: render-ready output maps and aggregate totals
- `ui/ui_state.py`
  - typed mutable workflow state shared by controller logic
  - `UnsavedChangesDecision`: typed save/discard/cancel prompt result
  - `PlanningState`: generated steps, active wizard index, and planning mode
  - `WizardState`: per-step transient calculation cache plus USD/ILS wizard-run FX cache/override fields
- `ui/screens/main_editor_screen.py`
  - screen 2 presentation/layout (portfolio editor)
  - exposes tree/cash/action widgets for signal wiring
- `ui/screens/summary_screen.py`
  - screen 3 presentation/layout (plan summary)
  - exposes summary text and navigation controls
- `ui/screens/welcome_screen.py`
  - screen 1 presentation/layout (startup welcome)
  - exposes startup actions plus remembered-path status display
- `ui/screens/wizard_screen.py`
  - screen 4 presentation/layout (per-instrument execution wizard)
  - exposes price input, calculation feedback, and step action controls

## portfolio_core module map
- `portfolio_core/models.py`
  - core immutable domain models (`Cash`, `AssetGroup`, `Instrument`, `Portfolio`)
  - `Exchange` enum is the canonical instrument trading selector (`TASE`, `NYSE`)
  - exchange-to-currency mapping lives in the enum (`TASE->ILS`, `NYSE->USD`)
  - planning output model `AssetGroupPlanRow`
- `portfolio_core/validation.py`
  - portfolio business-rule validation pipeline
  - validates instrument field constraints and exchange-specific invariants
  - validates cash constraints, allocation sums, instrument mapping, and naming/identity invariants
- `portfolio_core/io_json.py`
  - JSON parsing/serialization boundary for `Portfolio`
  - handles structural parsing and decimal conversion, but not strategy validation
  - requires instrument `exchange`, `ticker`, and `quantity`
- `portfolio_core/planning_types.py`
  - shared planning enum `PlanningMode` (`INVEST`, `REBALANCE`)
- `portfolio_core/planning.py`
  - pure planning logic:
    - invest budget calculation
    - group-level deltas (`plan_invest_no_sell`, `plan_rebalance`)
    - group-to-instrument delta splitting (`map_asset_group_deltas_to_instruments`)
- `portfolio_core/calc_stock_units.py`
  - unit-level trade math:
    - agorot-to-ILS conversion and unit flooring (`calculate_buy_units`)
    - direct ILS-price unit flooring (`calculate_buy_units_from_ils_price`)
    - immutable portfolio mutation helpers for buy/sell commits (`commit_buy`, `commit_sell`)
- `portfolio_core/fx_service.py`
  - Bank of Israel USD/ILS fetch boundary and response parsing
  - normalizes BOI payload into a typed quote object used by wizard flow
- `portfolio_core/portfolio_document.py`
  - in-memory editable document state:
    - current model
    - saved snapshot
    - active file path
    - dirty-state detection
- `portfolio_core/app_metadata.py`
  - app-level metadata helpers shared across layers
  - lazily resolves app version from `pyproject.toml` (`[project].version`)
  - returns `None` when metadata is unavailable (welcome screen hides version label)
- `portfolio_core/portfolio_session.py`
  - session-level file context and config-backed startup path behavior
  - exposes read-only remembered-path access for startup UI (`get_remembered_portfolio_path`)
  - persists/reads cached last successful USD/ILS quote in the same user config
  - coordinates `PortfolioDocument` load/save/new workflows
  - defines minimal default in-memory portfolio builder
- `portfolio_core/use_cases.py`
  - application workflow orchestration between UI and domain services
  - parses/validates/syncs/saves document data
  - builds plan results and applies wizard steps with persistence behavior

## Test map
UI-focused tests:
- `tests/ui/test_main_window_controller_state_flow.py`
  - focused tests for planning/wizard state transitions and controller/action seams
- `tests/ui/test_main_window_controller_delegation.py`
  - table-driven wrapper->controller delegation guards for composed controllers
- `tests/ui/test_main_window_controller_screen_signals.py`
  - focused screen-level signal wiring integration tests across welcome/main/summary/wizard flows
- `tests/ui/test_main_window_table_editing_controller.py`
  - focused table-editing normalization and validation/revert behavior tests
- `tests/ui/test_main_window_welcome_flow.py`
  - startup welcome behavior tests (button state and transition flows)
- `tests/ui/test_main_window_actions.py`
  - focused tests for save-target resolution and unsaved-changes action decisions
- `tests/ui/test_main_window_wizard.py`
  - focused tests for wizard step rendering, calculation flow, and step advancement behavior
- `tests/ui/test_portfolio_editor_adapter.py`
  - adapter mapping behavior and partial/strict input handling
- `tests/ui/test_portfolio_metrics.py`
  - pure recalculation rules and zero-denominator edge cases
- `tests/ui/test_screens.py`
  - structural tests for screen modules (defaults, controls, static setup)
- `tests/ui/test_ticker_input_delegate.py`
  - ticker delegate behavior (live alphanumeric filtering and editor wiring)
- `tests/ui/test_ui_state.py`
  - planning/wizard state defaults and behavior
- `tests/ui/test_ui_utils.py`
  - exchange parsing/default fallback and UI helper behavior
- `tests/ui/test_wizard_fx_coordinator.py`
  - FX coordinator lifecycle behavior (cancel guards, stale generations, USD-step panel rendering)

Core/domain tests:
- `tests/core/helpers.py`
  - shared builders (`make_valid_data`, `make_portfolio`)
- `tests/core/test_validation.py`
  - validation invariants and JSON round-trip stability
- `tests/core/test_budget.py`
  - invest-budget and future-tax-aware unit calculations
- `tests/core/test_planning.py`
  - invest/rebalance planning and group-to-instrument split behavior
- `tests/core/test_calc_stock_units.py`
  - unit-calculation and buy/sell commit mutation behavior
- `tests/core/test_session_and_use_cases.py`
  - `PortfolioSession`/`PortfolioDocument` behavior and use-case orchestration
- `tests/core/test_fx_service.py`
  - BOI USD/ILS payload parsing and "last published day" detection behavior

## Updating this document
Update this file when:
- flow ownership moves between controller/mixins/adapters,
- a new top-level `ui/*` module is introduced,
- a new top-level `portfolio_core/*` module is introduced or ownership changes,
- major test responsibilities move between test modules.
