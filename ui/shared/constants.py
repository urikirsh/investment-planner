"""Shared UI-level constants.

Timing policy notes:
- `DEFAULT_CLEANUP_WAIT_MS` is the standard short wait for async cleanup guards.
- `CLOSE_EVENT_CLEANUP_WAIT_MS` is intentionally longer for app-close teardown.
- `STARTUP_FX_FETCH_TIMEOUT_SECONDS` bounds network wait during welcome->main FX fetch.
"""

APP_NAME = "Investment Planner"

# Cleanup/wait policy constants (milliseconds unless noted otherwise).
DEFAULT_CLEANUP_WAIT_MS = 1000
CLOSE_EVENT_CLEANUP_WAIT_MS = 12000

# Startup welcome -> main FX fetch timeout (seconds).
STARTUP_FX_FETCH_TIMEOUT_SECONDS = 10.0
