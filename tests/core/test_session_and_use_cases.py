from __future__ import annotations

"""
Session/document and application use-case tests.

Covers persistence-path behavior, dirty-state tracking, and planning/wizard
use-case orchestration around `PortfolioSession`.
"""

import pytest
import json
from datetime import date, datetime, timezone

from portfolio_core.io_json import load_portfolio, load_portfolio_file, save_portfolio_file
from portfolio_core.models import Exchange
from portfolio_core.planning_types import PlanningMode
from portfolio_core.portfolio_document import PortfolioDocument
from portfolio_core.portfolio_session import PortfolioSession, build_default_portfolio
from portfolio_core.use_cases import (
    InsufficientQuantityForSellError,
    PlanStep,
    apply_wizard_step,
    build_plan_for_current_document,
    create_new_default_document,
    save_document_from_data,
    sync_document_from_data,
)
from portfolio_core.validation import validate_portfolio
from tests.core.helpers import D, make_valid_data


def test_portfolio_session_resolve_startup_path_returns_none_when_config_missing(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    assert session.resolve_startup_path() is None


def test_portfolio_session_set_active_file_path_persists_path_to_config(tmp_path):
    config_path = tmp_path / "config.json"
    target_path = tmp_path / "my_portfolio.json"
    target_path.write_text("{}", encoding="utf-8")
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=config_path)
    session.set_active_file_path(target_path)
    assert session.current_file_path == target_path
    assert session.get_remembered_portfolio_path() == target_path
    reloaded = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=config_path)
    assert reloaded.resolve_startup_path() == target_path


def test_portfolio_session_resolve_startup_path_clears_missing_file_reference(tmp_path):
    config_path = tmp_path / "config.json"
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=config_path)
    session.set_active_file_path(tmp_path / "missing.json")
    assert session.resolve_startup_path() is None
    assert session.current_file_path is None
    assert session._read_last_loaded_path_from_config() is None


def test_portfolio_document_load_save_and_dirty_state_tracking(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    p1 = load_portfolio(make_valid_data())
    p2 = load_portfolio(make_valid_data(cash_value="15000"))

    p1_path = tmp_path / "p1.json"
    p2_path = tmp_path / "p2.json"
    save_portfolio_file(p1, p1_path)

    loaded = session.load_document_from_path(p1_path)
    assert loaded == p1
    assert session.current_file_path == tmp_path / "p1.json"
    assert session.document.current_portfolio == p1
    assert session.document.is_dirty() is False

    session.document.set_current(p2)
    assert session.document.is_dirty() is True

    session.save_document_to_path(p2_path)
    assert session.current_file_path == p2_path
    assert session.document.current_portfolio == p2
    assert session.document.saved_snapshot == p2
    assert session.document.is_dirty() is False

    session.mark_new_document(p1)
    assert session.current_file_path is None
    assert session.document.current_portfolio == p1
    assert session.document.saved_snapshot == p1
    assert session.document.is_dirty() is False


def test_load_portfolio_file_accepts_utf8_bom(tmp_path):
    target = tmp_path / "bom_portfolio.json"
    payload = make_valid_data()
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")

    loaded = load_portfolio_file(target)
    assert loaded == load_portfolio(payload)


def test_portfolio_document_save_to_path_requires_current_portfolio(tmp_path):
    doc = PortfolioDocument()
    with pytest.raises(ValueError, match="No current portfolio to save"):
        doc.save_to_path(tmp_path / "x.json")


def test_portfolio_session_reads_cached_usd_ils_quote_from_memory(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    target_path = tmp_path / "portfolio.json"
    target_path.write_text("{}", encoding="utf-8")
    session.set_active_file_path(target_path)

    session.cache_usd_ils_quote(
        rate=D("3.77"),
        effective_date=date.fromisoformat("2026-03-05"),
        used_last_published=False,
    )

    assert session.resolve_startup_path() == target_path
    cached = session.read_cached_usd_ils_quote()
    assert cached is not None
    assert cached.rate == D("3.77")
    assert str(cached.effective_date) == "2026-03-05"


def test_portfolio_session_cache_usd_ils_quote_updates_memory_only(tmp_path) -> None:
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    cached_at = datetime(2026, 3, 13, tzinfo=timezone.utc)

    quote = session.cache_usd_ils_quote(
        rate=D("3.81"),
        effective_date=date.fromisoformat("2026-03-12"),
        used_last_published=True,
        cached_at=cached_at,
    )

    assert quote.rate == D("3.81")
    assert quote.effective_date == date.fromisoformat("2026-03-12")
    assert quote.used_last_published is True
    assert quote.cached_at == cached_at
    in_memory = session.read_cached_usd_ils_quote()
    assert in_memory is not None
    assert in_memory == quote

    reloaded = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    assert reloaded.read_cached_usd_ils_quote() is None


def test_portfolio_session_cache_usd_ils_quote_does_not_write_config(tmp_path) -> None:
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")

    quote = session.cache_usd_ils_quote(
        rate=D("3.79"),
        effective_date=date.fromisoformat("2026-03-11"),
        used_last_published=False,
    )

    in_memory = session.read_cached_usd_ils_quote()
    assert in_memory is not None
    assert in_memory == quote
    assert not (tmp_path / "config.json").exists()


def test_build_default_portfolio_returns_valid_portfolio():
    p = build_default_portfolio()
    validate_portfolio(p)


def test_use_case_save_document_from_data_persists_and_tracks_snapshot(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    target = tmp_path / "saved.json"
    saved = save_document_from_data(session, make_valid_data(), target)
    assert target.exists()
    assert session.current_file_path == target
    assert session.document.current_portfolio == saved
    assert session.document.saved_snapshot == saved
    assert session.document.is_dirty() is False


def test_use_case_sync_document_from_data_marks_dirty_against_saved_snapshot(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    target = tmp_path / "saved.json"
    save_document_from_data(session, make_valid_data(), target)
    changed = sync_document_from_data(session, make_valid_data(cash_value="13000"))
    assert session.document.current_portfolio == changed
    assert session.document.is_dirty() is True


def test_use_case_create_new_default_document_clears_active_path(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    existing = tmp_path / "existing.json"
    existing.write_text("{}", encoding="utf-8")
    session.set_active_file_path(existing)
    created = create_new_default_document(session)
    assert created == build_default_portfolio()
    assert session.current_file_path is None
    assert session.document.current_portfolio == created
    assert session.document.is_dirty() is False


def test_use_case_build_plan_for_current_document_returns_steps(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    portfolio = load_portfolio(make_valid_data())
    session.document.mark_new_unsaved(portfolio)
    result = build_plan_for_current_document(session, PlanningMode.INVEST)

    assert result.portfolio == portfolio
    assert result.mode == PlanningMode.INVEST
    assert result.budget == D("10000")
    assert len(result.rows) == 2
    assert result.rows[0].asset_group_id == "g1"
    assert result.rows[0].asset_group_name == "Asset 1"
    assert result.rows[0].current_value == D("6000")
    assert result.rows[0].planned_delta_money == D("6000")
    assert result.rows[1].asset_group_id == "g2"
    assert result.rows[1].asset_group_name == "Asset 2"
    assert result.rows[1].current_value == D("4000")
    assert result.rows[1].planned_delta_money == D("4000")

    assert len(result.steps) == 2
    assert result.steps[0].asset_group_id == "g1"
    assert result.steps[0].asset_group_name == "Asset 1"
    assert result.steps[0].instrument_id == "i1"
    assert result.steps[0].ticker == "1234567"
    assert result.steps[0].instrument_name == "Inst 1"
    assert result.steps[0].planned_delta_money == D("6000")
    assert result.steps[1].asset_group_id == "g2"
    assert result.steps[1].asset_group_name == "Asset 2"
    assert result.steps[1].instrument_id == "i2"
    assert result.steps[1].ticker == "2345678"
    assert result.steps[1].instrument_name == "Inst 2"
    assert result.steps[1].planned_delta_money == D("4000")


def test_use_case_apply_wizard_step_persists_buy_trade(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    target = tmp_path / "portfolio.json"
    save_document_from_data(session, make_valid_data(), target)
    before = session.document.current_portfolio
    assert before is not None
    before_cash = before.cash.value

    step = PlanStep(
        asset_group_id="g1",
        asset_group_name="Asset 1",
        instrument_id="i1",
        ticker="1234567",
        instrument_name="Inst 1",
        exchange=Exchange.TASE,
        planned_delta_money=D("500"),
    )
    applied = apply_wizard_step(session, step, calc_units=2, spent=D("200"))
    assert applied is True
    after = session.document.current_portfolio
    assert after is not None
    assert after.cash.value == before_cash - D("200")
    assert next(ins for ins in after.instruments if ins.id == "i1").quantity == 2
    assert session.current_file_path == target


def test_use_case_apply_wizard_step_skips_when_not_actionable(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    target = tmp_path / "portfolio.json"
    save_document_from_data(session, make_valid_data(), target)
    before = session.document.current_portfolio
    assert before is not None

    step = PlanStep(
        asset_group_id="g1",
        asset_group_name="Asset 1",
        instrument_id="i1",
        ticker="1234567",
        instrument_name="Inst 1",
        exchange=Exchange.TASE,
        planned_delta_money=D("500"),
    )
    applied = apply_wizard_step(session, step, calc_units=0, spent=D("0"))
    assert applied is False
    assert session.document.current_portfolio == before


def test_use_case_apply_wizard_step_persists_sell_trade_and_decrements_quantity(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    target = tmp_path / "portfolio.json"
    save_document_from_data(
        session,
        make_valid_data(
            instruments=[
                {
                    "id": "i1",
                    "name": "Inst 1",
                    "value": "6000",
                    "exchange": "TASE",
                    "investable": True,
                    "groupId": "g1",
                    "targetInGroupPercentage": "100",
                    "quantity": 5,
                },
                {
                    "id": "i2",
                    "name": "Inst 2",
                    "value": "4000",
                    "exchange": "TASE",
                    "investable": True,
                    "groupId": "g2",
                    "targetInGroupPercentage": "100",
                },
            ]
        ),
        target,
    )

    step = PlanStep(
        asset_group_id="g1",
        asset_group_name="Asset 1",
        instrument_id="i1",
        ticker="1234567",
        instrument_name="Inst 1",
        exchange=Exchange.TASE,
        planned_delta_money=D("-500"),
    )
    applied = apply_wizard_step(session, step, calc_units=2, spent=D("200"))

    assert applied is True
    after = session.document.current_portfolio
    assert after is not None
    assert next(ins for ins in after.instruments if ins.id == "i1").quantity == 3


def test_use_case_apply_wizard_step_sell_raises_when_quantity_is_insufficient(tmp_path):
    session = PortfolioSession(default_json_path=tmp_path / "default_portfolio", config_path=tmp_path / "config.json")
    target = tmp_path / "portfolio.json"
    save_document_from_data(
        session,
        make_valid_data(
            instruments=[
                {
                    "id": "i1",
                    "name": "Inst 1",
                    "value": "6000",
                    "exchange": "TASE",
                    "investable": True,
                    "groupId": "g1",
                    "targetInGroupPercentage": "100",
                    "quantity": 1,
                },
                {
                    "id": "i2",
                    "name": "Inst 2",
                    "value": "4000",
                    "exchange": "TASE",
                    "investable": True,
                    "groupId": "g2",
                    "targetInGroupPercentage": "100",
                },
            ]
        ),
        target,
    )

    step = PlanStep(
        asset_group_id="g1",
        asset_group_name="Asset 1",
        instrument_id="i1",
        ticker="1234567",
        instrument_name="Inst 1",
        exchange=Exchange.TASE,
        planned_delta_money=D("-500"),
    )

    with pytest.raises(InsufficientQuantityForSellError, match="Cannot sell 2 units"):
        apply_wizard_step(session, step, calc_units=2, spent=D("200"))
