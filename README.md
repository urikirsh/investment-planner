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
- Optional per-instrument `quantity` tracking field (default empty; empty or non-negative integer; no calculation impact)
- Per-instrument `currency` (`ILS` or `USD`) for wizard price-entry semantics
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
  - dynamic price input mode:
    - `ILS` instruments: price entered in agorot
    - `USD` instruments: price entered in USD
    - ILS wizard label is `Price (Agorot)`, and input is converted with `agorot / 100` to ILS before unit calculation
  - USD/ILS conversion fetched from Bank of Israel representative rates (latest published)
  - fetch runs in the background and can take up to 10 seconds; wizard opens immediately
  - during fetch, USD-step `Calculate` is disabled with a visible loading notice
  - if official fetch fails, a temporary manual USD/ILS override can be entered in the wizard
  - if official fetch fails but a readable cached rate exists, the cached rate is used and its cache timestamp is shown
  - if official fetch fails and cached rate is unavailable/unreadable, wizard prompts for manual USD/ILS input
  - stale async fetch completions are ignored (wizard-run generation guard) to avoid cross-run state leaks
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
- Main editor includes:
  - `Quantity` column (instrument rows), optional tracking only
  - `Currency` column (instrument rows) with dropdown editing
- Wizard displays all planned/spent/proceeds amounts explicitly in ILS
- Drag and drop to:
  - reorder groups and instruments
  - move instruments into or out of the non-investable bucket

For internal code structure and test architecture, see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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

The app reads and writes a JSON portfolio file. The canonical schema/example is
maintained in [`example_portfolio.json`](example_portfolio.json).

Notes:
- Monetary/percentage values are stored as strings and parsed as decimals.
- `instruments[*].currency` is required and must be `ILS` or `USD`.
- `instruments[*].quantity` is optional and must be empty or a non-negative integer string.
- `groups[*].targetPercentage` must sum to exactly `100`.
- For each investable group, `targetInGroupPercentage` across its instruments must sum to exactly `100`.
- Non-investable instruments must not have `groupId`, and their `targetInGroupPercentage` must be `0`.
- JSON files with or without UTF-8 BOM are supported on load.

---

## Saving your work

- The app remembers the last portfolio file you worked on and reopens it next time.
- If that file is missing, the app starts with a small default portfolio so you can keep working.
- The app also stores the last successful USD/ILS quote in the same user config for fetch-failure fallback.
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
