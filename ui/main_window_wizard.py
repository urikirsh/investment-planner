from __future__ import annotations

"""Wizard-screen flow extracted from the main window controller.

This mixin encapsulates wizard screen wiring plus step calculation/save/advance
behavior so `MainWindow` can remain focused on high-level orchestration.

It also owns wizard-run-scoped FX handling for USD-priced instruments:
- one-at-most BOI fetch attempt per run (only when USD steps exist)
- non-blocking BOI fetch (up to 10s timeout) so wizard transition never blocks
- loud failure UX on fetch error, with cache fallback when available
- manual USD/ILS override fallback (transient, never persisted)
"""

from datetime import datetime
from decimal import Decimal
from typing import cast

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QLabel, QLineEdit, QStackedWidget, QTreeWidget, QWidget

from portfolio_core.calc_stock_units import calculate_buy_units, calculate_buy_units_from_ils_price
from portfolio_core.fx_service import UsdIlsRateQuote, fetch_latest_usd_ils_rate
from portfolio_core.models import Currency
from portfolio_core.portfolio_session import CachedUsdIlsQuote, PortfolioSession
from portfolio_core.use_cases import apply_wizard_step
from ui.dialogs import show_error
from ui.portfolio_editor_adapter import populate_main_editor_from_portfolio
from ui.screens.wizard_screen import WizardScreen
from ui.ui_state import PlanningState, WizardState
from ui.ui_utils import d_from_text

D = Decimal


class _FxFetchWorker(QObject):
    """Background BOI fetch worker.

    Runs inside a dedicated `QThread` and emits a single completion signal with:
    - parsed quote object on success, or
    - human-readable error text on failure.
    """

    finished = Signal(object, object, int)  # (UsdIlsRateQuote | None, error_text | None, generation)

    def __init__(self, *, timeout_seconds: float = 10.0, generation: int) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds
        self._generation = generation

    @Slot()
    def run(self) -> None:
        try:
            quote = fetch_latest_usd_ils_rate(timeout_seconds=self._timeout_seconds)
            self.finished.emit(quote, None, self._generation)
        except Exception as exc:
            self.finished.emit(None, str(exc), self._generation)


class MainWindowWizardMixin:
    """Mixin containing wizard screen setup and per-step execution flow.

    Host methods declared with ``...`` are intentional interface stubs that
    the concrete ``MainWindow`` provides.
    """

    session: PortfolioSession
    planning_state: PlanningState
    wizard_state: WizardState
    stack: QStackedWidget
    tree: QTreeWidget
    cash_value_edit: QLineEdit
    cash_reserve_edit: QLineEdit
    future_tax_edit: QLineEdit
    screen_main: QWidget
    screen_wizard: WizardScreen
    wiz_info: QLabel
    price_label: QLabel
    price_edit: QLineEdit
    manual_rate_edit: QLineEdit
    wiz_result: QLabel
    _non_investable_bucket_id: str
    _non_investable_bucket_title: str
    _fx_fetch_thread: QThread | None
    _fx_fetch_worker: _FxFetchWorker | None

    def _quit_app(self) -> None:
        """Quit the Qt application from wizard controls."""
        ...

    def _update_file_context_ui(self) -> None:
        """Refresh file-related UI context after wizard save side effects."""
        ...

    def _update_future_tax_visual_state(self) -> None:
        """Apply visual cues when the editor is repopulated after wizard completion."""
        ...

    def _init_wizard_screen(self) -> None:
        """Build screen-3 widget and wire wizard actions."""
        self.screen_wizard = WizardScreen(cast(QWidget, self))
        self.wiz_info = self.screen_wizard.wiz_info
        self.price_label = self.screen_wizard.price_label
        self.price_edit = self.screen_wizard.price_edit
        self.manual_rate_edit = self.screen_wizard.manual_rate_edit
        self.wiz_result = self.screen_wizard.wiz_result
        self.screen_wizard.calculate_btn.clicked.connect(self._wizard_calculate)
        self.screen_wizard.quit_btn.clicked.connect(self._quit_app)
        self.screen_wizard.save_continue_btn.clicked.connect(self._wizard_save_continue)
        self.screen_wizard.continue_without_save_btn.clicked.connect(self._wizard_continue_without_saving)
        self._fx_fetch_thread = None
        self._fx_fetch_worker = None

    def _show_current_wizard_step(self) -> None:
        """Render current wizard step details and reset last calculation state."""
        s = self.planning_state.plan_steps[self.planning_state.step_index]
        idx = self.planning_state.step_index + 1
        total = len(self.planning_state.plan_steps)

        action = "BUY" if s.planned_delta_money > 0 else "SELL"
        self.wiz_info.setText(
            f"Step {idx}/{total}\n"
            f"Asset group: {s.asset_group_name}\n"
            f"Instrument: {s.instrument_name}\n"
            f"Planned {action} value (ILS): {abs(s.planned_delta_money)}"
        )
        if hasattr(self, "screen_wizard"):
            self.screen_wizard.set_price_mode(s.currency)
            self._render_fx_panel_for_current_step()
        self.price_edit.setText("")
        self.wiz_result.setText("Units: - | Spent/Proceeds: - | Leftover vs plan: -")

        self.wizard_state.last_calc = None

    def _wizard_calculate(self) -> None:
        """Calculate units/spend for the current wizard step from entered price."""
        try:
            s = self.planning_state.plan_steps[self.planning_state.step_index]
            entered_price = d_from_text(self.price_edit.text(), "price")

            planned = abs(s.planned_delta_money)
            conversion_info = ""
            if s.currency == Currency.USD.value:
                usd_ils_rate = self._get_effective_usd_ils_rate()
                price_ils = entered_price * usd_ils_rate
                calc = calculate_buy_units_from_ils_price(
                    instrument_id=s.instrument_id,
                    planned_money=planned,
                    price_ils=price_ils,
                )
                conversion_info = (
                    f"Converted: {entered_price} USD x {usd_ils_rate} = {price_ils} ILS | "
                )
            else:
                calc = calculate_buy_units(
                    instrument_id=s.instrument_id,
                    planned_money=planned,
                    price_ag=entered_price,
                )
            self.wizard_state.last_calc = calc

            label_money = "Spent (ILS)" if s.planned_delta_money > 0 else "Proceeds (ILS)"
            self.wiz_result.setText(
                f"{conversion_info}Units: {calc.units} | {label_money}: {calc.spent} | Leftover vs plan: {calc.leftover}"
            )
        except Exception as e:
            show_error(cast(QWidget, self), "Calculation failed", str(e))

    def _get_effective_usd_ils_rate(self) -> D:
        """Return USD/ILS rate for current wizard run, with override fallback."""
        if self.wizard_state.usd_ils_rate is not None:
            return self.wizard_state.usd_ils_rate
        if self.wizard_state.usd_ils_fetch_in_progress:
            raise ValueError("Still fetching official USD/ILS rate (can take up to 10 seconds). Please wait.")
        if self.wizard_state.manual_override_usd_ils_rate is not None:
            return self.wizard_state.manual_override_usd_ils_rate

        raw = self.manual_rate_edit.text().strip()
        if raw:
            rate = d_from_text(raw, "manual USD/ILS rate")
            if rate <= 0:
                raise ValueError("manual USD/ILS rate must be positive")
            self.wizard_state.manual_override_usd_ils_rate = rate
            self._render_fx_panel_for_current_step()
            return rate

        raise ValueError(
            "USD/ILS rate unavailable. Could not fetch from Bank of Israel. "
            "Enter a manual USD/ILS rate to continue."
        )

    def _wizard_has_usd_steps(self) -> bool:
        """Return whether current plan includes at least one USD-priced step."""
        return any(step.currency == Currency.USD.value for step in self.planning_state.plan_steps)

    def _prepare_wizard_fx_rate_cache(self) -> None:
        """Begin BOI USD/ILS fetch asynchronously once per wizard run when needed.

        This method is intentionally side-effectful for UI responsiveness:
        - marks fetch as in-progress immediately,
        - renders loading state in the wizard,
        - starts worker thread and returns without blocking.

        If an older fetch cannot be cancelled yet, no new fetch is started and
        an explicit "please wait" message is shown.
        """
        if self.wizard_state.usd_ils_fetch_attempted:
            return
        if not self._wizard_has_usd_steps():
            return

        if not self._cancel_wizard_fx_fetch():
            show_error(
                cast(QWidget, self),
                "Please wait",
                "Still finishing background USD/ILS fetch. Try again in a few seconds.",
            )
            return
        self.wizard_state.usd_ils_fetch_attempted = True
        self.wizard_state.usd_ils_fetch_in_progress = True
        self.wizard_state.usd_ils_fetch_error = None
        self.wizard_state.usd_ils_fetch_generation += 1
        generation = self.wizard_state.usd_ils_fetch_generation
        self.wizard_state.usd_ils_active_fetch_generation = generation

        if hasattr(self, "screen_wizard"):
            self._render_fx_panel_for_current_step()

        parent = cast(QObject, self)
        self._fx_fetch_thread = QThread(parent)
        self._fx_fetch_worker = _FxFetchWorker(timeout_seconds=10.0, generation=generation)
        self._fx_fetch_worker.moveToThread(self._fx_fetch_thread)
        self._fx_fetch_thread.started.connect(self._fx_fetch_worker.run)
        self._fx_fetch_worker.finished.connect(self._on_fx_fetch_finished)
        self._fx_fetch_worker.finished.connect(self._fx_fetch_thread.quit)
        self._fx_fetch_worker.finished.connect(self._fx_fetch_worker.deleteLater)
        self._fx_fetch_thread.finished.connect(self._fx_fetch_thread.deleteLater)
        self._fx_fetch_thread.start()

    @Slot(object, object, int)
    def _on_fx_fetch_finished(self, quote_obj: object, error_obj: object, generation: int) -> None:
        """Handle completion of asynchronous BOI fetch.

        Success path:
        - stores official quote in run state,
        - persists quote to session config cache,
        - clears error/loud-failure state.

        Failure path:
        - records explicit fetch error,
        - tries local cached quote fallback,
        - shows one loud failure modal per run,
        - requires manual entry when no readable cache exists.
        """
        if generation != self.wizard_state.usd_ils_active_fetch_generation:
            if self._fx_fetch_thread is not None and not self._fx_fetch_thread.isRunning():
                self._fx_fetch_worker = None
                self._fx_fetch_thread = None
            return

        self.wizard_state.usd_ils_fetch_in_progress = False
        self.wizard_state.usd_ils_active_fetch_generation = None
        self._fx_fetch_worker = None
        self._fx_fetch_thread = None

        quote = quote_obj if isinstance(quote_obj, UsdIlsRateQuote) else None
        error_text = str(error_obj) if isinstance(error_obj, str) else ""

        if quote is not None and not error_text:
            self.wizard_state.usd_ils_rate = quote.rate
            self.wizard_state.usd_ils_rate_date = quote.effective_date
            self.wizard_state.usd_ils_source = quote.source
            self.wizard_state.usd_ils_used_last_published = quote.used_last_published
            self.wizard_state.usd_ils_fetch_error = None
            self.wizard_state.usd_ils_rate_from_cache = False
            self.wizard_state.usd_ils_rate_cached_at = None
            try:
                self.session.write_cached_usd_ils_quote(
                    rate=quote.rate,
                    effective_date=quote.effective_date,
                    source=quote.source,
                    used_last_published=quote.used_last_published,
                )
            except Exception:
                pass
            self._render_fx_panel_for_current_step()
            return

        self.wizard_state.usd_ils_fetch_error = error_text or "Unknown fetch failure"
        self.wizard_state.usd_ils_rate = None
        self.wizard_state.usd_ils_rate_date = None
        self.wizard_state.usd_ils_source = None
        self.wizard_state.usd_ils_used_last_published = False
        self.wizard_state.usd_ils_rate_from_cache = False
        self.wizard_state.usd_ils_rate_cached_at = None

        cached = self.session.read_cached_usd_ils_quote()
        if isinstance(cached, CachedUsdIlsQuote):
            self.wizard_state.usd_ils_rate = cached.rate
            self.wizard_state.usd_ils_rate_date = cached.effective_date
            self.wizard_state.usd_ils_source = f"{cached.source} (cached)"
            self.wizard_state.usd_ils_used_last_published = cached.used_last_published
            self.wizard_state.usd_ils_rate_from_cache = True
            self.wizard_state.usd_ils_rate_cached_at = cached.cached_at

        if not self.wizard_state.usd_ils_failure_dialog_shown:
            self.wizard_state.usd_ils_failure_dialog_shown = True
            if self.wizard_state.usd_ils_rate_from_cache:
                show_error(
                    cast(QWidget, self),
                    "Official USD/ILS fetch failed",
                    "Could not fetch official USD/ILS rate within 10 seconds.\n"
                    f"Using cached USD/ILS rate: {self.wizard_state.usd_ils_rate} "
                    f"(cached at: {self.wizard_state.usd_ils_rate_cached_at}).",
                )
            else:
                show_error(
                    cast(QWidget, self),
                    "Official USD/ILS fetch failed",
                    "Could not fetch official USD/ILS rate within 10 seconds.\n"
                    "No readable cached rate is available. Enter manual USD/ILS rate to continue.",
                )

        self._render_fx_panel_for_current_step()

    def _reset_wizard_fx_state_for_new_run(self) -> bool:
        """Reset transient USD/ILS state and clear manual FX input for a new run.

        Returns ``False`` when a prior fetch thread is still running and reset
        is therefore not safe to apply yet.
        """
        if not self._cancel_wizard_fx_fetch():
            return False
        self.wizard_state.usd_ils_rate = None
        self.wizard_state.usd_ils_rate_date = None
        self.wizard_state.usd_ils_source = None
        self.wizard_state.usd_ils_used_last_published = False
        self.wizard_state.usd_ils_fetch_attempted = False
        self.wizard_state.usd_ils_fetch_error = None
        self.wizard_state.manual_override_usd_ils_rate = None
        self.wizard_state.usd_ils_fetch_in_progress = False
        self.wizard_state.usd_ils_failure_dialog_shown = False
        self.wizard_state.usd_ils_rate_from_cache = False
        self.wizard_state.usd_ils_rate_cached_at = None
        self.wizard_state.usd_ils_active_fetch_generation = None
        # Clear manual input widget to prevent value carry-over across runs.
        if hasattr(self, "manual_rate_edit"):
            self.manual_rate_edit.setText("")
        return True

    def _cancel_wizard_fx_fetch(self, *, wait_timeout_ms: int = 1000) -> bool:
        """Stop and detach the in-flight FX fetch thread, if any.

        Returns
        -------
        bool
            ``True`` when no thread is running after cancellation attempt.
            ``False`` when a thread is still running after waiting.
        """
        thread = self._fx_fetch_thread
        worker = self._fx_fetch_worker
        if thread is not None and thread.isRunning():
            thread.quit()
            if not thread.wait(wait_timeout_ms):
                return False
        if worker is not None:
            worker.deleteLater()
        self._fx_fetch_worker = None
        self._fx_fetch_thread = None
        return True

    def _render_fx_panel_for_current_step(self) -> None:
        """Render FX quote/fallback/override status for the active step.

        For USD steps this method is the single source of truth for:
        - loading message ("can take up to 10 seconds"),
        - official/cached/manual source disclosures,
        - whether calculate is temporarily disabled,
        - whether manual override controls should be shown.
        """
        if not hasattr(self, "screen_wizard"):
            return
        s = self.planning_state.plan_steps[self.planning_state.step_index]
        if s.currency != Currency.USD.value:
            self.screen_wizard.calculate_btn.setEnabled(True)
            self.screen_wizard.set_fx_panel(
                visible=False,
                info_text="",
                error_text="",
                manual_visible=False,
            )
            return

        info_lines: list[str] = []
        if self.wizard_state.usd_ils_fetch_in_progress:
            info_lines.append("Fetching official USD/ILS rate (can take up to 10 seconds)...")

        if self.wizard_state.usd_ils_rate is not None:
            info_lines.append(
                f"USD/ILS rate: {self.wizard_state.usd_ils_rate} | "
                f"Effective date: {self.wizard_state.usd_ils_rate_date} | "
                f"Source: {self.wizard_state.usd_ils_source}"
            )
            if self.wizard_state.usd_ils_used_last_published:
                info_lines.append("No new official rate for today; using last published rate.")
            if self.wizard_state.usd_ils_rate_from_cache:
                info_lines.append(
                    f"Official fetch failed. Using cached rate saved at: {self.wizard_state.usd_ils_rate_cached_at}."
                )

        if self.wizard_state.manual_override_usd_ils_rate is not None:
            info_lines.append(f"Using manual override USD/ILS rate: {self.wizard_state.manual_override_usd_ils_rate}")

        error_text = self.wizard_state.usd_ils_fetch_error or ""
        if error_text:
            error_text = (
                f"Official USD/ILS fetch failed after up to 10 seconds ({error_text}). "
                + (
                    "Using cached rate shown above."
                    if self.wizard_state.usd_ils_rate_from_cache
                    else "No readable cached rate available. Enter manual USD/ILS rate."
                )
            )

        self.screen_wizard.calculate_btn.setEnabled(not self.wizard_state.usd_ils_fetch_in_progress)
        self.screen_wizard.set_fx_panel(
            visible=True,
            info_text="\n".join(info_lines),
            error_text=error_text,
            manual_visible=bool(error_text and not self.wizard_state.usd_ils_rate_from_cache),
            manual_value=(
                str(self.wizard_state.manual_override_usd_ils_rate)
                if self.wizard_state.manual_override_usd_ils_rate is not None
                else ""
            ),
            )

    def _wizard_save_continue(self) -> None:
        """Apply current step trade (if valid), persist, and move to next step."""
        try:
            if self.session.document.current_portfolio is None:
                raise ValueError("No portfolio loaded")

            s = self.planning_state.plan_steps[self.planning_state.step_index]

            if self.wizard_state.last_calc is None:
                calc_units = 0
                spent = D("0")
            else:
                calc_units = self.wizard_state.last_calc.units
                spent = self.wizard_state.last_calc.spent

            applied = apply_wizard_step(self.session, s, calc_units, spent)
            if applied:
                self._update_file_context_ui()

            self._advance_wizard_step()
        except Exception as e:
            show_error(cast(QWidget, self), "Save failed", str(e))

    def _wizard_continue_without_saving(self) -> None:
        """Skip current step without mutating portfolio and move forward."""
        try:
            if self.session.document.current_portfolio is None:
                raise ValueError("No portfolio loaded")
            self._advance_wizard_step()
        except Exception as e:
            show_error(cast(QWidget, self), "Continue failed", str(e))

    def _advance_wizard_step(self) -> None:
        """Move to next step, or repopulate main editor and return when complete.

        Final-step transition is guarded by FX-thread cancellation; if cleanup
        cannot complete yet, the method keeps the current step active and
        informs the user to retry shortly.
        """
        self.planning_state.step_index += 1
        if self.planning_state.step_index >= len(self.planning_state.plan_steps):
            if not self._cancel_wizard_fx_fetch():
                self.planning_state.step_index -= 1
                show_error(
                    cast(QWidget, self),
                    "Please wait",
                    "Still finishing background USD/ILS fetch. Try again in a few seconds.",
                )
                return
            self.wizard_state.usd_ils_fetch_in_progress = False
            self.wizard_state.usd_ils_active_fetch_generation = None
            current = self.session.document.current_portfolio
            assert current is not None
            populate_main_editor_from_portfolio(
                tree=self.tree,
                cash_value_edit=self.cash_value_edit,
                cash_reserve_edit=self.cash_reserve_edit,
                future_tax_edit=self.future_tax_edit,
                portfolio=current,
                non_investable_bucket_id=self._non_investable_bucket_id,
                non_investable_bucket_title=self._non_investable_bucket_title,
                on_future_tax_value_set=self._update_future_tax_visual_state,
            )
            self.stack.setCurrentWidget(self.screen_main)
        else:
            self._show_current_wizard_step()
