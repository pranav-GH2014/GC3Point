import pytest
from nifty_algo.config.config_loader import AppConfig
from nifty_algo.risk.risk_manager import RiskManager, PreLiveCheckFailedError
from nifty_algo.risk.charges import ZerodhaOptionChargesCalculator

def test_affordability_98_percent_rule():
    config = AppConfig()
    risk = RiskManager(config)

    # Initial capital ₹5,000. 98% deployable = ₹4,900.
    # Case 1: Option @ ₹70 with lot size 65 = ₹4,550 <= ₹4,900 -> AFFORDABLE
    ok, qty, msg = risk.verify_affordability(available_capital=5000.0, option_premium=70.0, lot_size=65)
    assert ok is True
    assert qty == 65

    # Case 2: Option @ ₹100 with lot size 65 = ₹6,500 > ₹4,900 -> UNAFFORDABLE (skip trade)
    ok, qty, msg = risk.verify_affordability(available_capital=5000.0, option_premium=100.0, lot_size=65)
    assert ok is False
    assert qty == 0
    assert "exceeds 98% deployable capital limit" in msg

def test_consecutive_losses_circuit_breaker():
    config = AppConfig(max_consecutive_losses=3)
    risk = RiskManager(config)

    assert not risk.is_frozen
    assert risk.consecutive_losses == 0

    # Loss 1
    risk.record_trade_result(-150.0)
    assert risk.consecutive_losses == 1
    assert not risk.is_frozen

    # Win resets counter
    risk.record_trade_result(+195.0)
    assert risk.consecutive_losses == 0
    assert not risk.is_frozen

    # 3 consecutive losses
    risk.record_trade_result(-100.0)
    risk.record_trade_result(-120.0)
    risk.record_trade_result(-80.0)
    assert risk.consecutive_losses == 3
    assert risk.is_frozen is True

def test_pre_live_safety_checks_blocks_unresolved_parameters():
    config = AppConfig()
    config.simulation_mode = False
    config.live_execution_enabled = True
    config.risk.max_loss_per_trade_inr = None  # UNRESOLVED!

    risk = RiskManager(config)
    passed, failures = risk.perform_pre_live_safety_checks()
    assert passed is False
    assert any("max_loss_per_trade_inr" in f for f in failures)

def test_charges_calculation_gross_vs_net():
    # BUY 65 units @ 150, SELL @ 153 (+3 points)
    # Gross = +3 * 65 = ₹195.00
    buy_p = 150.0
    sell_p = 153.0
    qty = 65

    charges = ZerodhaOptionChargesCalculator.calculate(buy_p, sell_p, qty)
    gross_pnl = (sell_p - buy_p) * qty
    net_pnl = gross_pnl - charges.total_charges

    assert gross_pnl == 195.0
    assert charges.brokerage == 40.0  # 20 per leg * 2
    assert charges.total_charges > 40.0
    assert net_pnl < gross_pnl
    assert net_pnl > 0  # Winning trade after charges
