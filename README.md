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
- Drag and drop to:
  - reorder groups and instruments
  - move instruments into or out of the non-investable bucket

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
python app.py
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

## Save and persistence behavior

- By default, the app uses `portfolio.json` in the project root.
- On startup, if `portfolio.json` exists, it is loaded.
- If no file exists, the app initializes a minimal default in-memory portfolio.
- Pressing `Update` validates current UI data and writes it to `portfolio.json`.
- During wizard execution, `Save and continue` persists after each step to support partial execution.
- `Continue without saving` advances the wizard without writing changes for that step.

---

## Project metadata

- Name: `investment-planner`
- Type: Desktop GUI application (PySide6)
- Primary language: Python
- Python requirement: `3.14.2`
- License: MIT (see [`LICENSE`](LICENSE))
