# Investment Planner

**A GUI tool for planning and executing a passive investment strategy**

`investment-planner` is a desktop application for managing a long-term investment strategy based on predefined asset allocation targets.

It helps answer a common question for passive investors:

> *Given my current holdings and target allocation, how should I allocate new money (or rebalance) in a clear, controlled way?*

The tool is designed for real-world use, emphasizes correctness and transparency, and is actively used to manage an actual portfolio.

---

## Core concepts

- You define asset groups with target percentages (must sum to exactly 100).
- Instruments belong to groups and have a current market value (ILS).
- Over time, market movements cause the portfolio to drift from the target.
- When investing new money (or rebalancing), the app:
  - shows how far each group is from its target
  - calculates how much should be allocated per group
  - helps translate value allocations into concrete buy decisions

The application never executes trades automatically. All actions are explicit and user-controlled.

---

## Features

### Portfolio structure
- Asset groups with decimal target percentages
- Instruments with current market value in ILS
- Per-group instrument split using mandatory in-group target percentages (must sum to 100 per group)
- Permanent non-investable bucket for holdings excluded from the strategy
- Cash with:
  - configurable minimum reserve
  - configurable future tax (non-investable liability)

### Calculations and insights
- Strategy % per group (share of investable assets)
- Portfolio % per row (share of total portfolio value), where:
  - `total portfolio = cash + all instrument values - future tax`
- Drift (pp) from target allocation, with color coding:
  - green -> over target
  - red -> under target
- Strict validation: target percentages must sum to `100.0` exactly
- Future tax must be non-negative (empty input is normalized to `0`)

### Investment workflow
- Two modes:
  - Invest: allocate new funds without selling
  - Invest & Rebalance: allow selling to restore targets
- Invest budget formula:
  - `cash - minimal reserve - future tax` (floored at zero)
- Step-by-step investment flow:
  - per-instrument allocation based on desired post-investment in-group targets
  - price input exactly as shown in the broker (agorot)
  - automatic conversion to ILS
  - integer unit calculation (rounded down)
- Wizard actions:
  - Save and continue
  - Continue without saving
- Partial execution supported (each instrument handled independently)

### UI and UX
- Immediate validation with clear feedback and automatic revert on invalid input
- Future tax is highlighted in red when greater than zero
- Main screen shows your live investable balance, with color feedback:
  - green when you have enough to invest
  - gray when you do not
- Drag and drop to:
  - reorder groups and instruments
  - move instruments into or out of the non-investable bucket

### UI module structure
- `ui/main_window_controller.py`:
  - coordinator for screen transitions, planning flow, and persistence actions
  - separates UI prompting (`QMessageBox` / `QFileDialog`) from save/open/plan action methods for easier testing
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

---

## Screenshots

### Main portfolio screen

![Main portfolio screen](main_window_screenshot.png)

### Investment summary screen

![Investment summary screen](per_instrument_screenshot.png)

### Per-instrument investment screen

![Per-instrument investment screen](per_instrument_screenshot.png)

---

## Running the application

### Requirements
- Python 3.14.2
- PySide6

Install dependencies:

```bash
pip install PySide6
```

Run the app:

```bash
python investment_planner.py
```

---

## Data file format

The app reads and writes a JSON portfolio file with this shape:

```json
{
  "cash": {
    "value": "12000",
    "min_reserve": "2000",
    "future_tax": "0"
  },
  "groups": [
    {
      "id": "g_equity",
      "name": "Global Equity",
      "targetPercentage": "70"
    },
    {
      "id": "g_bonds",
      "name": "Bonds",
      "targetPercentage": "30"
    }
  ],
  "instruments": [
    {
      "id": "i_world_etf",
      "name": "World ETF",
      "value": "8000",
      "investable": true,
      "groupId": "g_equity",
      "targetInGroupPercentage": "100"
    },
    {
      "id": "i_bond_fund",
      "name": "Bond Fund",
      "value": "3000",
      "investable": true,
      "groupId": "g_bonds",
      "targetInGroupPercentage": "100"
    },
    {
      "id": "i_legacy_holding",
      "name": "Legacy Holding",
      "value": "1200",
      "investable": false,
      "targetInGroupPercentage": "0"
    }
  ]
}
```

Notes:
- Monetary/percentage values are stored as strings and parsed as decimals.
- `groups[*].targetPercentage` must sum to exactly `100`.
- For each investable group, `targetInGroupPercentage` across its instruments must sum to exactly `100`.
- Non-investable instruments must not have `groupId`, and their `targetInGroupPercentage` must be `0`.

See [`example_portfolio.json`](example_portfolio.json) for a full synthetic example.

---

## Saving your work

- The app remembers the last portfolio file you worked on and reopens it next time.
- If that file is missing, the app starts with a small default portfolio so you can keep working.
- `Save` updates the current file.
- `Save As` lets you choose a new file name/location.
- `Open` loads an existing portfolio file.
- `New` starts a fresh default portfolio.
- If you try to `Open`, `New`, or `Quit` with unsaved changes, the app asks whether to save first.
- In the step-by-step wizard:
  - `Save and continue` writes progress after that step.
  - `Continue without saving` moves on without writing that step.

---

## Project metadata

- Name: `investment-planner`
- Type: Desktop GUI application (PySide6)
- Primary language: Python
- Python requirement: `3.14.2`
- License: MIT (see [`LICENSE`](LICENSE))
