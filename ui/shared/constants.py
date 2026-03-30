"""Shared UI-level constants.

Timing policy notes:
- `DEFAULT_CLEANUP_WAIT_MS` is the standard short wait for async cleanup guards.
- `CLOSE_EVENT_CLEANUP_WAIT_MS` is intentionally longer for app-close teardown.
- `STARTUP_MARKET_DATA_FETCH_TIMEOUT_SECONDS` bounds network wait during welcome->main startup market-data refresh.
"""

APP_NAME = "Investment Planner"

# Cleanup/wait policy constants (milliseconds unless noted otherwise).
DEFAULT_CLEANUP_WAIT_MS = 1000
CLOSE_EVENT_CLEANUP_WAIT_MS = 12000

# Startup welcome -> main market-data fetch timeout (seconds).
STARTUP_MARKET_DATA_FETCH_TIMEOUT_SECONDS = 10.0
