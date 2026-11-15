import pytest
from nifty_algo.config.config_loader import AppConfig
from nifty_algo.notifications.telegram import TelegramNotifier

def test_telegram_message_formatting():
    config = AppConfig(
        telegram_bot_token="test_token",
        telegram_chat_id="test_chat",
        static_ip="127.0.0.1",
        server_port=8002
    )
    notifier = TelegramNotifier(config)

    # Disable network dispatch in tests
    notifier.enabled = False

    # 1. Signal triggered
    order_specs = {
        "tradingsymbol": "NIFTY26NOV24000CE",
        "lot_size": 65,
        "ltp": 120.0
    }
    struct_details = "  • Direction: BULLISH\n  • Setup: Breakout and Retest\n  • VWAP: Above"
    assert notifier.send_message("Test message") is True

    # 2. Position closed alert formatting
    notifier.notify_position_closed(
        symbol="NIFTY26NOV24000CE",
        buy_avg=119.55,
        sell_avg=122.55,
        qty=65,
        gross_pnl=195.0,
        net_pnl=142.50,
        charges=52.50,
        daily_realized_pnl=142.50,
        new_capital=5142.50,
        exit_reason="Target +3.0 Points Hit on Broker"
    )

    # 3. Post-target milestone
    notifier.notify_post_target_milestone(
        symbol="NIFTY26NOV24000CE",
        entry_price=119.55,
        exit_price=122.55,
        milestone="+5.0 Points",
        current_price=124.55
    )
