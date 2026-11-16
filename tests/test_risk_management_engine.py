import pytest
from datetime import datetime, timedelta, timezone
from nifty_algo.risk_management_engine import RiskManagementEngine, RiskEngineConfig

IST = timezone(timedelta(hours=5, minutes=30))

def test_risk_management_circuit_breaker_daily_loss():
    cfg = RiskEngineConfig(max_daily_loss_inr=500.0)
    engine = RiskManagementEngine(cfg)
    
    # 1. First trade loss ₹300
    engine.record_completed_trade("T1", gross_pnl=-250.0, net_pnl=-300.0, exit_reason="SL")
    can_enter, reason = engine.can_initiate_new_trade(has_active_position=False)
    # Blocked by cooldown
    assert "REJECTED_LOSS_COOLDOWN_ACTIVE" in reason
    
    # Fast forward past cooldown
    t_after_cd = datetime.now(IST) + timedelta(minutes=20)
    can_enter, reason = engine.can_initiate_new_trade(has_active_position=False, current_time_ist=t_after_cd)
    assert can_enter is True
    
    # 2. Second trade loss ₹250 (Total loss = ₹550 > ₹500 limit)
    engine.record_completed_trade("T2", gross_pnl=-200.0, net_pnl=-250.0, exit_reason="SL", timestamp=t_after_cd)
    can_enter, reason = engine.can_initiate_new_trade(has_active_position=False, current_time_ist=t_after_cd + timedelta(minutes=20))
    assert can_enter is False
    assert "CIRCUIT_BREAKER_ACTIVE" in reason or "DAILY_LOSS_LIMIT" in reason
    assert engine.circuit_breaker.is_tripped is True

def test_risk_management_consecutive_losses():
    cfg = RiskEngineConfig(max_consecutive_losses=2, max_daily_loss_inr=5000.0)
    engine = RiskManagementEngine(cfg)
    now = datetime.now(IST)
    
    engine.record_completed_trade("T1", -50.0, -80.0, "SL", timestamp=now)
    assert engine.consecutive_losses == 1
    
    # Fast forward 16 mins
    t2 = now + timedelta(minutes=16)
    engine.record_completed_trade("T2", -50.0, -80.0, "SL", timestamp=t2)
    assert engine.consecutive_losses == 2
    assert engine.circuit_breaker.is_tripped is True

def test_risk_management_dynamic_stop_loss():
    cfg = RiskEngineConfig(min_stop_loss_pts=2.5, max_stop_loss_pts=6.0)
    engine = RiskManagementEngine(cfg)
    
    # Spot ATR = 15, Delta = 0.50, Spread = 0.50
    sl = engine.compute_dynamic_stop_loss(entry_premium=100.0, spot_atr=15.0, option_delta=0.50, bid_ask_spread=0.50)
    assert 2.5 <= sl <= 6.0
    # Tick alignment to 0.05
    assert round(sl % 0.05, 4) in (0.0, 0.05)

def test_risk_management_two_stage_exit():
    engine = RiskManagementEngine()
    buy_avg = 100.0
    current_stop = 96.0  # -4 pts initial stop
    
    # Case 1: Minor movement (+0.5 pts) -> no change in stop
    new_stop, reason = engine.compute_two_stage_exit_price(buy_avg, 100.5, current_stop, 100.5)
    assert new_stop == current_stop
    assert reason == "MAINTAIN_CURRENT_STOP"
    
    # Case 2: In profit +2.0 pts -> Stage 1 Breakeven + Charges Lock
    new_stop, reason = engine.compute_two_stage_exit_price(buy_avg, 102.0, current_stop, 102.0)
    assert new_stop > buy_avg  # Locks entry + charges offset!
    assert "STAGE_1_BREAKEVEN" in reason
    
    # Case 3: Reached +3.0 pts -> Stage 2 Trailing Lock
    new_stop_stage2, reason_stage2 = engine.compute_two_stage_exit_price(buy_avg, 102.5, new_stop, 103.0)
    assert new_stop_stage2 >= 101.5  # Trails 1.5 pts behind highest (103.0 - 1.5 = 101.5)
    assert "STAGE_2_TRAILING" in reason_stage2
