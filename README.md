# Investment Planner

A **local-first investment planning tool** for passive investors who follow a target allocation strategy and want to invest new funds efficiently, with minimal friction and without unnecessary taxable events.

The app helps answer one recurring question:

> *“Given my current portfolio and target allocation, how should I invest new money today?”*

---

## ✨ Key Features

- **Target allocation by asset group**
  - Define strategy at the *asset exposure* level (e.g. S&P 500, Bonds, Crypto).
  - Each asset group has an exact target percentage (must sum to 100%).

- **Multiple instruments per asset group**
  - Hold the same exposure via multiple providers/funds.
  - Choose a **preferred instrument** for new purchases while keeping legacy holdings (useful for tax reasons).

- **Cash reserve handling**
  - Keep a configurable minimum cash balance for fees.
  - Automatically infer how much cash is available for investment.

- **No-sell investment planning**
  - Default mode allocates new money only (no selling).
  - Overweight asset groups are skipped automatically.

- **Optional rebalance mode**
  - Allows selling and buying to return to target allocation.

- **Discrete unit calculation**
  - Enter instrument prices.
  - App calculates how many units to buy (always rounded down).
  - Minimum trade size enforced.

- **Step-by-step investment wizard**
  - Review plan → calculate units → commit each trade.
  - Partial progress is saved; no need to complete everything in one session.

- **Local JSON storage**
  - All data is stored locally.
  - No external APIs, no broker integration, no cloud dependency.

---

## 🧠 Conceptual Model

- **Asset Group**  
  Represents an exposure in your strategy (e.g. “S&P 500”, “US Bonds”).  
  Holds the target percentage and defines *what* you want exposure to.

- **Instrument**  
  A concrete fund / ETF / product that provides exposure to an asset group.  
  You may have multiple instruments per group but buy new units only via the preferred one.

- **Cash**  
  Explicitly modeled and excluded from strategy percentages.  
  Only cash above the configured reserve is considered investable.

---

## 🖥️ GUI Overview

The app uses a simple 3-screen flow:

1. **Main screen**
   - Edit cash, asset groups, instruments, targets.
   - Reorder asset groups (controls investment order).
   - Save or start investment planning.

2. **Summary screen**
   - Shows planned buy/sell amounts per asset group.
   - Confirms investment budget and execution order.

3. **Investment wizard**
   - For each asset group:
     - Enter price.
     - See calculated units.
     - Save & continue to the next step.

---

## 🚀 Getting Started

### Requirements
- Python **3.10+**
- Windows / macOS / Linux

### Install dependencies
```bash
pip install PySide6
```

### Run the app

From the project root:

```bash
python -m app
```

If `portfolio.json` exists, it will be loaded automatically.
Otherwise, a minimal default portfolio is created.

---

## 🧪 Tests

Core logic is fully unit-tested (planning, validation, unit calculation).

Run all tests:

```bash
pip install pytest
pytest
```

---

## 📁 Project Structure

```bash
investment_planner/
├── models.py            # Data models
├── io_json.py           # Load/save portfolio JSON
├── validation.py        # Strict portfolio validation
├── planning.py          # Invest / rebalance algorithms
├── calc_stock_units.py  # Price → units → commit logic
│
ui/
├── main_window.py       # PySide6 GUI
│
app.py                   # Application entry point
```

---

## 🔒 Privacy & Safety

- No network access
- No credentials
- No broker APIs
- Portfolio data is local and excluded via `.gitignore`

This tool is designed for personal decision support only.

---

## ⚠️ Disclaimer

This software is provided for **educational and personal use only**.
It does **not** constitute financial advice.
You are solely responsible for any investment decisions you make.
