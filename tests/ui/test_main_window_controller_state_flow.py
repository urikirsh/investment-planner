from __future__ import annotations

import os
from collections.abc import Iterator
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from PySide6.QtWidgets import QApplication

from investment_planner.calc_stock_units import BuyCalculation
from investment_planner.planning_types import PlanningMode
from investment_planner.use_cases import PlanStep
import ui.main_window_controller as main_window_controller
from ui.main_window_controller import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

D = Decimal


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = cast(QApplication | None, QApplication.instance())
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture()
def window(monkeypatch: pytest.MonkeyPatch, qapp: QApplication, tmp_path) -> Iterator[MainWindow]:
    _ = qapp
    monkeypatch.setattr(MainWindow, "_load_or_init", lambda self: None)
    win = MainWindow(json_path=str(tmp_path / "portfolio.json"))
    yield win
    win.close()


def test_wizard_state_and_step_index_flow_across_planning_and_wizard_methods(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    step_1 = PlanStep(
        asset_group_id="g_equity",
        asset_group_name="Equity",
        instrument_id="i_world",
        instrument_name="World ETF",
        planned_delta_money=D("120"),
    )
    step_2 = PlanStep(
        asset_group_id="g_bonds",
        asset_group_name="Bonds",
        instrument_id="i_bond",
        instrument_name="Bond Fund",
        planned_delta_money=D("80"),
    )
    calc = BuyCalculation(
        instrument_id="i_world",
        price=D("10"),
        planned_money=D("120"),
        units=12,
        spent=D("120"),
        leftover=D("0"),
    )

    fake_plan_result = SimpleNamespace(
        budget=D("200"),
        steps=[step_1, step_2],
        portfolio=SimpleNamespace(),
    )
    monkeypatch.setattr(window, "_save_current_or_save_as", lambda **_: True)
    monkeypatch.setattr(main_window_controller, "build_plan_for_current_document", lambda *_: fake_plan_result)
    monkeypatch.setattr(window, "_populate_summary", lambda *_: None)

    window.planning_state.step_index = 99
    window.wizard_state.last_calc = calc
    window._run_planning(PlanningMode.REBALANCE)
    assert window.planning_state.plan_steps == [step_1, step_2]
    assert window.planning_state.step_index == 0
    assert window.planning_state.mode == PlanningMode.REBALANCE
    assert window.wizard_state.last_calc is None

    window.wizard_state.last_calc = calc
    window._show_current_wizard_step()
    assert window.planning_state.step_index == 0
    assert window.wizard_state.last_calc is None
    assert "Step 1/2" in window.wiz_info.text()

    window.wizard_state.last_calc = calc
    window._advance_wizard_step()
    assert window.planning_state.step_index == 1
    assert window.wizard_state.last_calc is None
    assert "Step 2/2" in window.wiz_info.text()
