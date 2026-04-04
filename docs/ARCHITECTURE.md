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
2. `ui/main_window.py` composes screens and delegates per-screen logic.
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
4. Planning (`invest`/`rebalance`) is built in `portfolio_core.workflows`.
5. Summary screen presents generated plan steps.
6. Wizard execution is managed by `MainWindowWizardMixin`.
7. Wizard returns to screen 2 either after completion or via explicit "Exit Wizard"; both paths repopulate the main editor from current session state and run a full metrics refresh before showing screen 2.

Startup/wizard market-data guards in this flow:
- Welcome->main transition includes async startup market-data refresh with a minimum 1-second loading overlay.
- Wizard runs reuse startup-cached USD/ILS data from in-memory session cache.
- Wizard flow never performs USD/ILS network fetches.
- Window close cancels any active startup market-data fetch before teardown.

## Controller composition rules
- `MainWindow` is the composition root and owns long-lived controller instances.
- Prefer direct signal wiring to composed controller methods for single-hop UI actions.
- Keep `MainWindow` wrappers only when they are required by:
  - `MainWindowActionsMixin` / `MainWindowWizardMixin` host-method contracts, or
  - stable test seams for cross-controller orchestration points.
- New screen behavior should be added to a dedicated controller object under `ui/controllers/*`, not as inline `MainWindow` logic.

## UI module map
- `ui/controllers/main_window_welcome.py`
  - `MainWindowWelcomeController`: welcome setup, remembered-path status rendering, and UI-level startup decisions
  - successful startup actions show a blocking overlay for at least 1 second while fetching startup market data
  - fetch failures show a Back-only error dialog and keep the user on the welcome screen
  - commits the staged startup portfolio only after startup refresh succeeds, then delegates final enter-main / stay-on-welcome UI decisions
- `ui/controllers/startup_transition.py`
  - extracted startup transition state machine and startup market-data worker lifecycle
  - owns the minimum-delay timer, worker-thread lifecycle, and transition gating
- `ui/controllers/main_window_main_editor.py`
  - `MainWindowMainEditorController`: editor wiring and direct row-level add/delete/new-document actions
  - `Add Instrument` opens a modal 3-step dialog and only mutates the tree on explicit wizard completion
  - controller keeps add flow orchestration-focused by running wizard execution (overlay + accept/result checks) in a dedicated helper
  - add flow builds case-insensitive portfolio-wide name locations and exchange+ticker locations so duplicate keys are blocked before row creation
  - accepted add-flow results append a new instrument row, then the standard metrics refresh recomputes derived table values
- `ui/controllers/main_window_table_editing.py`
  - `MainWindowTableEditingController`: tree item normalization and validation/revert behavior
- `ui/controllers/main_window_metrics.py`
  - `MainWindowMetricsController`: derived totals/percentages/drift refresh and visual state updates
- `ui/controllers/main_window_summary.py`
  - `MainWindowSummaryController`: summary setup and summary->wizard/main navigation behavior
- `ui/controllers/protocols.py`
  - protocol contracts for controller-host dependencies
  - keeps controller object composition statically typed without MRO coupling
- `ui/screens/main_editor_screen.py`
  - screen 2 presentation/layout (portfolio editor)
  - exposes tree/cash/action widgets for signal wiring
- `ui/screens/add_instrument_wizard_dialog.py`
  - modal 3-step add-instrument flow used from screen 2
  - step 1: exchange choice
  - step 2: ticker input with exchange-specific live normalization/validation plus duplicate `(exchange, ticker)` inline blocking
  - step 3: name + strategy percentage validation and final add action, including inline duplicate-name blocking
  - each step renders the selected group plus prior step decisions for review
  - NYSE ticker input normalizes lowercase letters to uppercase while typing
  - step-2 ticker input `Enter` key behaves like `Next` when `Next` is enabled
  - for NYSE and TASE, step-2 `Next` shows a blocking loading overlay ("reading data") while ticker verification runs in an async lookup coordinator
  - successful step-2 lookup requires both instrument metadata and a current/last traded price
  - ticker-not-found, missing-price lookup results, ticker-lookup communication failures, and unexpected internal lookup failures are shown as Back-only modals and keep the flow on step 2
  - duplicate ticker/name submit paths keep defensive Back-only modals naming the existing location
  - return/cancel prompts for discard only when user has edited wizard input
- `ui/screens/summary_screen.py`
  - screen 3 presentation/layout (plan summary)
  - exposes summary text and navigation controls
- `ui/screens/welcome_screen.py`
  - screen 1 presentation/layout (startup welcome)
  - exposes startup actions plus remembered-path status display
- `ui/screens/wizard_screen.py`
  - screen 4 presentation/layout (per-instrument execution wizard)
  - exposes units input, inline validation, calculation feedback, and step action controls
  - action layout keeps app-level `Quit` separated from right-aligned step navigation actions (`Exit Wizard`, `Skip Step`)
  - primary commit action (`Save and continue`) is colocated with the result row (`Units/Spent/Leftover`) for higher focus
  - `Save and continue` is disabled by default and only enabled after the active units value is valid for the planned step amount
  - centered units row and centered result row are width-aligned with a minimum 11-character input width guard
  - row-width syncing is responsive: widths are clamped to available space and revert to natural sizing on narrow windows
- `ui/shared/*`
  - package for cross-cutting UI primitives reused by screens/controllers/adapters
  - `cached_instrument_pricing.py`: shared cached-price resolution helper that reads the market-data lookup cache and converts per-unit prices to ILS
  - `constants.py`: shared static UI constants used by multiple UI modules
    - cleanup timing knobs are defined here so wait policy stays centralized
  - `decimal_input_delegate.py`: numeric line-edit delegate for decimal-only input
  - `loading_overlay.py`: reusable blocking loading overlay with centered spinner + status label for timed/async UI transitions
  - `ui_types.py`: shared enums and Qt item-data role ids for tree semantics
  - `ui_utils.py`: shared UI helpers for row metadata, formatting, alignment, and exchange/currency parsing
  - `__init__.py`: re-export surface for common shared symbols
- `ui/dialogs.py`
  - typed wrappers around common `QMessageBox`/`QFileDialog` interactions
  - centralizes dialog seams to keep controller/action code easier to test
- `ui/main_window.py`
  - thin composition root for welcome/main/summary/wizard wiring and transitions
  - composes focused controller objects from `ui/controllers/*`
  - wires most Qt signals directly to composed controller methods
  - keeps thin wrapper methods only for cross-flow contracts used by actions/wizard flows and tests
  - guards window close by canceling any active startup transition/fetch and invoking wizard FX cleanup seam
- `ui/main_window_actions.py`
  - save/open/new action flows and unsaved-changes decision handling
  - wraps dialog interactions behind typed helper methods to keep action logic testable
- `ui/main_window_wizard.py`
  - wizard screen wiring and per-step cached-price resolution, units validation, save, and advance behavior
  - handles transition back to main editor when wizard execution completes or when user exits early via `Exit Wizard`
  - wizard step info card includes instrument name, ticker, exchange, asset group, and action amount context
  - resolves per-instrument prices through the shared cached-instrument-pricing helper backed by the market-data lookup cache populated during startup/add-instrument lookups
  - pre-fills whole-unit buy/sell counts from cached prices, then recomputes totals from the user-editable units field
  - invalid step state invalidates cached `last_calc` and re-disables `Save and continue`
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
- `ui/tree_widget.py`
  - specialized `QTreeWidget` behavior and drag/drop guardrails for investment rows
  - enforces tree-level edit/move constraints before controller-level validation
- `ui/ui_state.py`
  - typed mutable workflow state shared by controller logic
  - `UnsavedChangesDecision`: typed save/discard/cancel prompt result
  - `PlanningState`: generated steps, active wizard index, and planning mode
  - `WizardState`: per-step transient calculation cache plus startup-cached USD/ILS display state
- `ui/wizard_fx_coordinator.py`
  - extracted FX-only coordinator used by `MainWindowWizardMixin`
  - owns USD-step FX panel rendering and reset behavior for wizard runs
  - reads session-cached USD/ILS quote; wizard does not trigger BOI fetch
- `ui/ticker_lookup_coordinator.py`
  - extracted ticker-lookup worker/thread lifecycle coordinator used by add-instrument wizard step 2
  - normalizes lookup outcomes into typed success/error payloads consumed by the dialog UI
  - remembers the latest successful lookup metadata for the dialog accept flow
  - treats "metadata found but no price" as a step-2 error outcome rather than a success

## portfolio_core module map
- `portfolio_core/domain/models.py`
  - core immutable domain models (`Cash`, `AssetGroup`, `Instrument`, `Portfolio`)
  - `Exchange` enum is the canonical instrument trading selector (`TASE`, `NYSE`)
  - exchange-to-currency mapping lives in the enum (`TASE->ILS`, `NYSE->USD`)
  - planning output model `AssetGroupPlanRow`
- `portfolio_core/domain/planning_types.py`
  - shared planning enum `PlanningMode` (`INVEST`, `REBALANCE`)
- `portfolio_core/domain/ticker_rules.py`
  - shared exchange-specific ticker normalization and validation helpers
  - centralizes TASE/NYSE ticker regex rules, input constraints, and UI-facing rule constants
  - defines canonical exchange+ticker identity keys and a shared duplicate-location index value object used by wizard/editor flows
- `portfolio_core/domain/validation.py`
  - portfolio business-rule validation pipeline
  - validates instrument field constraints and exchange-specific invariants
  - validates cash constraints, allocation sums, instrument mapping, and naming/identity invariants

### market_data package
- `portfolio_core/market_data/models.py`
  - defines lookup result/metadata contracts and immutable provider-data freezing
  - lookup metadata now carries optional `last_traded_price` alongside display fields
- `portfolio_core/market_data/lookup_service.py`
  - routes lookups by exchange and owns NYSE/TASE cache policy
  - cache entries store the full typed lookup result, including fetched price metadata
  - also exposes a cache-read path used by the wizard when it must not trigger a fresh fetch
- `portfolio_core/market_data/transport.py`
  - defines the HTTP transport seam used by providers
- `portfolio_core/market_data/providers/base.py`
  - provides shared HTTP transport error-normalization for provider implementations
- `portfolio_core/market_data/providers/nyse_stooq.py`
  - resolves NYSE via Stooq quote endpoint (`q/l`) plus symbol page title (`q/?s=`) for display names
  - NYSE dotted symbols also try dashed Stooq fallback keys (for example `BRK.B` -> `brk-b.us`)
- `portfolio_core/market_data/providers/tase_api.py`
  - resolves TASE via `api.tase.co.il` `company/securitydata`
  - normalizes quoted TASE price fields from agorot to ILS before populating lookup metadata

### planning package
- `portfolio_core/planning/calc_stock_units.py`
  - unit-level trade math:
    - agorot-to-ILS conversion and unit flooring (`calculate_buy_units`)
    - direct ILS-price unit flooring (`calculate_buy_units_from_ils_price`)
    - immutable portfolio mutation helpers for buy/sell commits (`commit_buy`, `commit_sell`)
- `portfolio_core/planning/planning.py`
  - pure planning logic:
    - invest budget calculation
    - group-level deltas (`plan_invest_no_sell`, `plan_rebalance`)
    - group-to-instrument delta splitting (`map_asset_group_deltas_to_instruments`)

### session package
- `portfolio_core/session/portfolio_document.py`
  - in-memory editable document state:
    - current model
    - saved snapshot
    - active file path
    - dirty-state detection
- `portfolio_core/session/portfolio_session.py`
  - session-level file context and config-backed startup path behavior
  - exposes read-only remembered-path access for startup UI (`get_remembered_portfolio_path`)
  - holds cached last successful USD/ILS quote in session memory only
  - coordinates `PortfolioDocument` load/save/new workflows
  - defines minimal default in-memory portfolio builder

- `portfolio_core/app_metadata.py`
  - app-level metadata helpers shared across layers
  - lazily resolves app version from `pyproject.toml` (`[project].version`)
  - returns `None` when metadata is unavailable (welcome screen hides version label)
- `portfolio_core/constants.py`
  - shared core-level constants used by market-data services and startup/open document workflows
- `portfolio_core/fx_service.py`
  - Bank of Israel USD/ILS fetch boundary and response parsing
  - normalizes BOI payload into a typed quote object used by wizard flow
- `portfolio_core/io_json.py`
  - JSON parsing/serialization boundary for `Portfolio`
  - handles structural parsing and decimal conversion, but not strategy validation
  - requires instrument `exchange`, `ticker`, and `quantity`
- `portfolio_core/workflows.py`
  - application workflow orchestration between UI and domain services
  - parses/validates/syncs/saves document data
  - builds plan results and applies wizard steps with persistence behavior

## Test map
UI-focused tests:
- `tests/ui/*`
  - layout mirrors `ui/*` where practical (`controllers/`, `screens/`, `delegates/`, `shared/`)
  - cross-cutting/integration-focused UI tests remain at `tests/ui/` root
- `tests/ui/conftest.py`
  - shared Qt app/window fixtures and reusable UI test helpers/builders (`seed_session_usd_ils_cache`, `make_plan_step`, `make_buy_calculation`, `add_instrument_row`)
- `tests/ui/controllers/test_main_window_controller_delegation.py`
  - table-driven wrapper->controller delegation guards for composed controllers
- `tests/ui/controllers/test_main_window_main_editor_controller.py`
  - focused add-instrument wizard integration tests for accept/cancel tree-mutation behavior
  - covers seeded table-value rounding for successful add flows
- `tests/ui/controllers/test_main_window_controller_screen_signals.py`
  - focused screen-level signal wiring integration tests across welcome/main/summary/wizard flows
- `tests/ui/controllers/test_main_window_controller_state_flow.py`
  - focused tests for planning/wizard state transitions and controller/action seams
- `tests/ui/controllers/test_main_window_table_editing_controller.py`
  - focused table-editing enablement and validation/revert behavior tests
- `tests/ui/controllers/test_main_window_welcome_flow.py`
  - startup welcome behavior tests (button state and transition flows)
- `tests/ui/controllers/test_main_window_welcome_lifecycle.py`
  - focused lifecycle tests for the extracted startup transition worker/thread ownership (`start`, `cancel`, `clear`)
- `tests/ui/screens/test_add_instrument_wizard_dialog.py`
  - focused add-instrument wizard dialog tests (step flow, validation, Enter shortcut behavior, context text, and duplicate ticker/name guards)
  - covers the blocked step-2 path when lookup metadata is found but price is unavailable
- `tests/ui/screens/test_screens.py`
  - structural tests for main screen modules (defaults, controls, static setup)
- `tests/ui/shared/test_loading_overlay.py`
  - loading overlay structure/geometry behavior and visibility toggling
- `tests/ui/shared/test_ui_utils.py`
  - exchange parsing/default fallback and UI helper behavior
- `tests/ui/test_dialogs.py`
  - focused dialog wrapper behavior and signal outcomes
- `tests/ui/test_main_window_actions.py`
  - focused tests for save-target resolution and unsaved-changes action decisions
- `tests/ui/test_main_window_wizard.py`
  - focused tests for wizard step rendering, calculation flow, and step advancement behavior
- `tests/ui/test_portfolio_editor_adapter.py`
  - adapter mapping behavior and partial/strict input handling
- `tests/ui/test_portfolio_metrics.py`
  - pure recalculation rules and zero-denominator edge cases
- `tests/ui/test_ticker_lookup_coordinator.py`
  - ticker-lookup coordinator lifecycle and outcome mapping behavior
  - covers missing-price lookup mapping and remembered-success metadata
- `tests/ui/test_ui_state.py`
  - planning/wizard state defaults and behavior
- `tests/ui/test_wizard_fx_coordinator.py`
  - FX coordinator behavior (session-cache hydration and USD-step panel rendering)

Core/domain tests:
- `tests/core/helpers.py`
  - shared builders (`make_valid_data`, `make_portfolio`)
- `tests/core/market_data/test_service.py`
  - NYSE/TASE market-data lookup parsing/matching, cache behavior, and communication-failure behavior
- `tests/core/test_budget.py`
  - invest-budget and future-tax-aware unit calculations
- `tests/core/test_calc_stock_units.py`
  - unit-calculation and buy/sell commit mutation behavior
- `tests/core/test_fx_service.py`
  - BOI USD/ILS payload parsing and "last published day" detection behavior
- `tests/core/test_planning.py`
  - invest/rebalance planning and group-to-instrument split behavior
- `tests/core/test_session_and_use_cases.py`
  - `PortfolioSession`/`PortfolioDocument` behavior and use-case orchestration
- `tests/core/test_ticker_rules.py`
  - shared ticker normalization/shape-validation rules plus canonical exchange+ticker key/index behavior
- `tests/core/test_validation.py`
  - validation invariants and JSON round-trip stability

## Updating this document
Update this file when:
- flow ownership moves between controller/mixins/adapters,
- a new top-level `ui/*` module is introduced,
- a new top-level `portfolio_core/*` module is introduced or ownership changes,
- major test responsibilities move between test modules.
