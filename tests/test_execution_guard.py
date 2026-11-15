import pytest
from nifty_algo.config.config_loader import AppConfig
from nifty_algo.database.db import DatabaseManager
from nifty_algo.execution.exit_manager import ExitSafetyManager, BrokerStateUncertainError
from nifty_algo.data.kite_client import SafeKiteClient

def test_exit_safety_prevents_naked_shorting(tmp_path):
    db_file = str(tmp_path / "test_exec.db")
    db = DatabaseManager(db_file)
    config = AppConfig(simulation_mode=True)
    kite = SafeKiteClient(config)
    exit_mgr = ExitSafetyManager(config, kite, db)

    # When no open long position exists, placing an exit must be strictly refused
    ok, order_id, tgt_price, msg = exit_mgr.place_fixed_target_exit("NIFTY26NOV24000CE", 100.0, 65)
    assert ok is False
    assert "Verified remaining long quantity" in msg

def test_exit_safety_protects_only_filled_quantity(tmp_path):
    db_file = str(tmp_path / "test_exec2.db")
    db = DatabaseManager(db_file)
    config = AppConfig(simulation_mode=True)
    kite = SafeKiteClient(config)
    exit_mgr = ExitSafetyManager(config, kite, db)

    # Register partial fill of 35 units (out of desired 65)
    db.create_position({
        "position_id": "P1",
        "trade_id": "T1",
        "instrument_token": 12345,
        "tradingsymbol": "NIFTY26NOV24000CE",
        "option_type": "CE",
        "strike": 24000.0,
        "expiry": "2026-11-26",
        "product": "NRML",
        "status": "OPEN",
        "desired_quantity": 65,
        "filled_quantity": 35,
        "remaining_quantity": 35,
        "buy_avg_price": 100.0,
        "target_price": 103.0,
        "opened_at_ist": "2026-11-14 10:00:00"
    })

    verified_qty, _ = exit_mgr.get_verified_remaining_long_quantity("NIFTY26NOV24000CE")
    assert verified_qty == 35

    # Target placement should succeed for verified quantity only
    ok, order_id, tgt_price, msg = exit_mgr.place_fixed_target_exit("NIFTY26NOV24000CE", 100.0, 65)
    assert ok is True
    assert tgt_price == 103.0
