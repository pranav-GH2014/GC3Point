import pytest
from fastapi.testclient import TestClient
from nifty_algo.monitoring.server_admin import create_admin_app
from nifty_algo.database.db import DatabaseManager

class MockNotifier:
    def __init__(self):
        self.enabled = False
        self.last_msg = ""
    def send_message(self, text, parse_mode="HTML"):
        self.last_msg = text
        return True

class MockBotController:
    def __init__(self):
        self.latest_nifty_spot = 25050.0
        self.notifier = MockNotifier()
        self.config = type("Config", (), {"static_ip": "127.0.0.1"})()

    def get_runtime_status(self):
        return {
            "mode": "PAPER",
            "is_trading_frozen": False,
            "consecutive_losses": 0,
            "capital": 5000.0,
            "open_position": None
        }

    def get_chart_data(self):
        return {
            "capital": 3971.0,
            "latest_spot": 25050.0,
            "candles": [
                {"time": 1700000000, "open": 25000.0, "high": 25020.0, "low": 24995.0, "close": 25015.0, "volume": 1200},
                {"time": 1700000060, "open": 25015.0, "high": 25055.0, "low": 25010.0, "close": 25050.0, "volume": 2500}
            ],
            "structure": {
                "supports": [24980.0, 25000.0],
                "resistances": [25080.0, 25100.0]
            },
            "heavyweights": {
                "summary": "FULL_BULLISH_ALIGNMENT",
                "is_bullish_aligned": True
            },
            "active_trade": {
                "trade_id": "TRD_001",
                "tradingsymbol": "NIFTY26NOV25050CE",
                "direction": "CE",
                "entry_premium": 130.0,
                "target_premium": 145.0,
                "target_pts": 15.0,
                "sl_premium": 125.0,
                "sl_pts": 5.0,
                "entry_spot": 25020.0,
                "spot_target": 25050.0,
                "spot_sl": 25010.0,
                "current_opt_ltp": 138.0,
                "unrealized_pts": 8.0,
                "unrealized_pnl": 520.0,
                "quantity": 65,
                "status": "OPEN"
            },
            "recent_trades": [
                {"tradingsymbol": "NIFTY26NOV25000CE", "option_type": "CE", "net_pnl": 195.0, "exit_reason": "Target Hit"}
            ],
            "oi_intel": {
                "has_data": True,
                "pcr": 1.15,
                "call_wall": {"strike": 25200.0, "oi": 5000000, "oi_formatted": "50.0 L", "prediction": "WILL_CROSS", "confidence": 85},
                "put_wall": {"strike": 25000.0, "oi": 6000000, "oi_formatted": "60.0 L", "prediction": "BOUNCE_EXPECTED", "confidence": 80}
            }
        }

    def update_active_trade_target(self, new_target_pts: float):
        return True, f"Target updated to +{new_target_pts:.1f} pts"

def test_admin_chart_api_endpoint(tmp_path):
    import json
    db_file = str(tmp_path / "test.db")
    db = DatabaseManager(db_file)
    bot = MockBotController()
    app = create_admin_app(bot, db)
    
    # Direct route testing without TestClient event-loop lock in Python 3.14
    routes = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
    
    class DummyRequest:
        def __init__(self, cookies=None, headers=None):
            self.cookies = cookies or {}
            self.headers = headers or {}

    class DummyResponse:
        def __init__(self):
            self.cookies = {}
        def set_cookie(self, key, value, **kwargs):
            self.cookies[key] = value

    # 1. Test GET / unauthenticated -> returns Telegram Login page
    dashboard_fn = routes["/"]
    unauth_req = DummyRequest()
    html_unauth = dashboard_fn(unauth_req)
    unauth_str = html_unauth.body.decode()
    assert "Operator Login" in unauth_str
    assert "Send Login Code to Telegram" in unauth_str

    # 2. Test Telegram Auth Flow (/auth/request-code and /auth/verify-code)
    req_code_fn = routes["/auth/request-code"]
    res_req = req_code_fn(unauth_req)
    assert res_req["status"] == "SUCCESS"
    assert "Verification code" in res_req["message"]
    # Check that code was in message
    import re
    match = re.search(r"<code>(\d{6})</code>", bot.notifier.last_msg)
    assert match is not None
    otp_code = match.group(1)

    verify_code_fn = routes["/auth/verify-code"]
    dummy_resp = DummyResponse()
    res_verify = verify_code_fn({"code": otp_code}, dummy_resp)
    assert res_verify["status"] == "SUCCESS"
    session_id = res_verify["session_id"]
    assert "nifty_admin_session" in dummy_resp.cookies

    # 3. Test GET / authenticated with session cookie -> returns TradingView visualizer
    auth_req = DummyRequest(cookies={"nifty_admin_session": session_id})
    html_res = dashboard_fn(auth_req)
    body_str = html_res.body.decode()
    assert "LightweightCharts" in body_str
    assert "hud-pnl" in body_str
    assert "spot-price" in body_str
    assert "oi-radar-pill" in body_str
    assert "Logout" in body_str

    # 4. Test GET /api/chart-data with auth
    chart_fn = routes["/api/chart-data"]
    json_res = chart_fn(auth_req)
    data = json.loads(json_res.body.decode())
    assert data["capital"] == 3971.0
    assert len(data["candles"]) == 2
    assert 25000.0 in data["structure"]["supports"]
    assert data["active_trade"]["target_pts"] == 15.0
    assert data["active_trade"]["unrealized_pnl"] == 520.0
    assert data["heavyweights"]["is_bullish_aligned"] is True
    assert "oi_intel" in data
    assert data["oi_intel"]["call_wall"]["prediction"] == "WILL_CROSS"

    # 5. Test POST /api/update-target (synchronous)
    update_fn = routes["/api/update-target"]
    res = update_fn({"target_pts": 8.0}, auth_req)
    assert res["status"] == "SUCCESS"
    assert res["target_pts"] == 8.0
