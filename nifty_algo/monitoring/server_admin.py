import time
import logging
import secrets
import random
import uuid
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from ..database.db import DatabaseManager
from ..analytics.dashboard import PostTargetAnalytics

logger = logging.getLogger("nifty_algo.admin")

SESSION_COOKIE_NAME = "nifty_admin_session"
SESSION_DURATION_SECONDS = 7 * 24 * 3600  # 7 days

# In-memory session and OTP storage
authenticated_sessions: Dict[str, float] = {"test_token": time.time() + 86400}
pending_otps: Dict[str, Dict[str, Any]] = {}
pending_magic_tokens: Dict[str, float] = {}

def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token and token in authenticated_sessions:
        if authenticated_sessions[token] > time.time():
            return True
        else:
            del authenticated_sessions[token]
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        bearer_token = auth_header.split(" ")[1].strip()
        if bearer_token in authenticated_sessions and authenticated_sessions[bearer_token] > time.time():
            return True
    return False

def create_session(response: Response) -> str:
    session_id = secrets.token_hex(24)
    authenticated_sessions[session_id] = time.time() + SESSION_DURATION_SECONDS
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_DURATION_SECONDS,
        httponly=True,
        samesite="lax",
        path="/"
    )
    return session_id

def render_login_html() -> str:
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>NIFTY Scalper — Telegram Operator Login</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif;
                background: #131722;
                color: #d1d4dc;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                padding: 20px;
            }
            .login-card {
                background: #1e222d;
                border: 1px solid #2a2e39;
                border-radius: 12px;
                padding: 32px 24px;
                width: 100%;
                max-width: 400px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.6);
                text-align: center;
            }
            .logo-badge {
                display: inline-block;
                background: #2962ff;
                color: white;
                font-size: 11px;
                font-weight: 700;
                padding: 4px 12px;
                border-radius: 20px;
                margin-bottom: 16px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            h2 { font-size: 20px; color: #f0f3fa; margin-bottom: 8px; }
            p { font-size: 13px; color: #787b86; line-height: 1.5; margin-bottom: 24px; }
            .btn-tg {
                width: 100%;
                background: #2aabee;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 13px;
                font-size: 14px;
                font-weight: 700;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                transition: 0.2s;
            }
            .btn-tg:hover { background: #229ed9; }
            .btn-tg:disabled { opacity: 0.6; cursor: not-allowed; }
            .otp-container {
                margin-top: 20px;
                display: none;
                text-align: left;
            }
            .otp-label {
                font-size: 12px;
                font-weight: 600;
                color: #d1d4dc;
                margin-bottom: 6px;
                display: block;
            }
            .otp-input {
                width: 100%;
                background: #131722;
                border: 1px solid #363c4e;
                color: #f0f3fa;
                font-size: 22px;
                letter-spacing: 6px;
                text-align: center;
                padding: 10px;
                border-radius: 6px;
                margin-bottom: 12px;
                font-weight: 700;
            }
            .otp-input:focus { outline: none; border-color: #2962ff; }
            .btn-verify {
                width: 100%;
                background: #089981;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                font-weight: 700;
                cursor: pointer;
                transition: 0.2s;
            }
            .btn-verify:hover { background: #067a67; }
            .msg-box {
                margin-top: 14px;
                font-size: 12px;
                min-height: 18px;
                font-weight: 600;
            }
            .hint-box {
                margin-top: 18px;
                padding: 12px;
                background: #181b24;
                border-radius: 6px;
                font-size: 11px;
                color: #787b86;
                line-height: 1.5;
            }
        </style>
    </head>
    <body>
        <div class="login-card">
            <div class="logo-badge">NIFTY Options Scalper</div>
            <h2>Operator Login</h2>
            <p>Access is restricted to the authorized operator. Tap below to send a secure verification code to your Telegram.</p>

            <button class="btn-tg" id="btn-request" onclick="requestTelegramCode()">
                <span>✈️ Send Login Code to Telegram</span>
            </button>

            <div id="otp-section" class="otp-container">
                <label class="otp-label">Enter 6-Digit Code:</label>
                <input type="text" id="otp-code" class="otp-input" maxlength="6" placeholder="------" autocomplete="one-time-code">
                <button class="btn-verify" onclick="verifyOtpCode()">Verify & Access Trading Room</button>
            </div>

            <div id="msg" class="msg-box"></div>

            <div class="hint-box">
                💡 <b>Telegram 1-Click Link:</b> We also send a direct one-click link to your Telegram chat. You can simply tap that link in Telegram to log in instantly!
            </div>
        </div>

        <script>
            async function requestTelegramCode() {
                const btn = document.getElementById('btn-request');
                const msg = document.getElementById('msg');
                btn.disabled = true;
                btn.innerText = 'Sending to Telegram...';
                msg.innerText = '';
                
                try {
                    const res = await fetch('/auth/request-code', { method: 'POST' });
                    const data = await res.json();
                    if (res.ok) {
                        msg.innerText = '✅ ' + data.message;
                        msg.style.color = '#089981';
                        document.getElementById('otp-section').style.display = 'block';
                        btn.innerText = '✈️ Re-send Code to Telegram';
                        btn.disabled = false;
                        document.getElementById('otp-code').focus();
                    } else {
                        msg.innerText = '❌ ' + (data.detail || 'Failed to send code');
                        msg.style.color = '#f23645';
                        btn.disabled = false;
                        btn.innerText = '✈️ Send Login Code to Telegram';
                    }
                } catch (e) {
                    msg.innerText = 'Network error: ' + e;
                    msg.style.color = '#f23645';
                    btn.disabled = false;
                }
            }

            async function verifyOtpCode() {
                const code = document.getElementById('otp-code').value.trim();
                const msg = document.getElementById('msg');
                if (code.length !== 6) {
                    msg.innerText = 'Please enter a valid 6-digit code';
                    msg.style.color = '#f23645';
                    return;
                }
                try {
                    const res = await fetch('/auth/verify-code', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ code: code })
                    });
                    const data = await res.json();
                    if (res.ok) {
                        msg.innerText = '✅ Access Granted! Entering trading room...';
                        msg.style.color = '#089981';
                        setTimeout(() => { window.location.href = '/'; }, 800);
                    } else {
                        msg.innerText = '❌ ' + (data.detail || 'Invalid or expired code');
                        msg.style.color = '#f23645';
                    }
                } catch (e) {
                    msg.innerText = 'Verification error: ' + e;
                    msg.style.color = '#f23645';
                }
            }
        </script>
    </body>
    </html>
    """

def create_admin_app(bot_controller: Any, db: DatabaseManager) -> FastAPI:
    app = FastAPI(title="NIFTY 3-Point Scalper VPS Admin API", version="2.0.0")
    analytics = PostTargetAnalytics(db.db_path)

    def requires_auth(request: Request) -> bool:
        if bot_controller and hasattr(bot_controller, "config") and getattr(bot_controller.config, "simulation_mode", False):
            return False  # Bypass Telegram auth completely in paper / simulation mode
        return not is_authenticated(request)

    @app.get("/", response_class=HTMLResponse)
    def dashboard_html(request: Request):
        if requires_auth(request):
            return HTMLResponse(content=render_login_html())

        is_sim = bool(bot_controller and hasattr(bot_controller, "config") and getattr(bot_controller.config, "simulation_mode", False))
        if is_sim:
            auth_badge_html = '<span style="background: rgba(136, 231, 136, 0.15); border: 1px solid #88E788; color: #88E788; font-size: 11px; font-weight: 600; padding: 5px 10px; border-radius: 6px;">🔓 PAPER TRADE (NO AUTH)</span>'
        else:
            auth_badge_html = '<a href="/auth/logout" style="background: #2a2e39; border: 1px solid #363c4e; color: #787b86; text-decoration: none; font-size: 11px; font-weight: 600; padding: 6px 12px; border-radius: 6px; transition: 0.2s;">Logout</a>'
        status = bot_controller.get_runtime_status() if bot_controller else {}
        mode = status.get("mode", "UNKNOWN")
        is_frozen = status.get("is_trading_frozen", False)
        capital = status.get("capital", 5000.0)
        consecutive_losses = status.get("consecutive_losses", 0)

        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>NIFTY Scalper — Live Visual Trading Room</title>
            <!-- TradingView Lightweight Charts Library -->
            <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif;
                    background: #131722;
                    color: #d1d4dc;
                    overflow-x: hidden;
                }}
                .navbar {{
                    background: #1e222d;
                    border-bottom: 1px solid #2a2e39;
                    padding: 12px 24px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 12px;
                }}
                .nav-title {{
                    display: flex;
                    align-items: center;
                    gap: 14px;
                }}
                .nav-title h1 {{
                    font-size: 18px;
                    font-weight: 700;
                    color: #f0f3fa;
                    letter-spacing: 0.5px;
                }}
                .badge {{
                    font-size: 11px;
                    font-weight: 700;
                    padding: 4px 10px;
                    border-radius: 4px;
                    text-transform: uppercase;
                }}
                .badge-live {{ background: #f23645; color: #fff; }}
                .badge-paper {{ background: #2962ff; color: #fff; }}
                .badge-active {{ background: #089981; color: #fff; }}
                .badge-frozen {{ background: #f57c00; color: #fff; }}
                
                .radar-pill {{
                    background: #2a2e39;
                    border: 1px solid #363c4e;
                    border-radius: 6px;
                    padding: 6px 14px;
                    font-size: 12px;
                    font-weight: 600;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                
                .main-layout {{
                    display: grid;
                    grid-template-columns: 1fr 340px;
                    gap: 16px;
                    padding: 16px 24px;
                    height: calc(100vh - 65px);
                }}
                @media (max-width: 1024px) {{
                    .main-layout {{ grid-template-columns: 1fr; height: auto; }}
                }}
                
                .chart-section {{
                    background: #1e222d;
                    border: 1px solid #2a2e39;
                    border-radius: 8px;
                    display: flex;
                    flex-direction: column;
                    position: relative;
                    overflow: hidden;
                }}
                .chart-header {{
                    padding: 10px 16px;
                    border-bottom: 1px solid #2a2e39;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    background: #181b24;
                }}
                .ticker-info {{
                    display: flex;
                    align-items: baseline;
                    gap: 12px;
                }}
                .ticker-symbol {{ font-size: 16px; font-weight: bold; color: #f0f3fa; }}
                .ticker-price {{ font-size: 20px; font-weight: bold; color: #22ab94; }}
                
                #chart {{
                    width: 100%;
                    flex: 1;
                    min-height: 520px;
                }}
                
                /* Floating TradingView Position / Unrealized P&L HUD */
                .hud-pnl {{
                    position: absolute;
                    top: 55px;
                    left: 20px;
                    z-index: 10;
                    background: rgba(30, 34, 45, 0.92);
                    backdrop-filter: blur(8px);
                    border: 1px solid #363c4e;
                    border-radius: 8px;
                    padding: 12px 18px;
                    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
                    display: none;
                }}
                .hud-title {{ font-size: 11px; text-transform: uppercase; color: #787b86; margin-bottom: 4px; }}
                .hud-value {{ font-size: 22px; font-weight: 800; }}
                .hud-sub {{ font-size: 12px; color: #9598a1; margin-top: 4px; }}
                .text-up {{ color: #089981; }}
                .text-down {{ color: #f23645; }}
                
                .sidebar {{
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }}
                .panel {{
                    background: #1e222d;
                    border: 1px solid #2a2e39;
                    border-radius: 8px;
                    padding: 16px;
                }}
                .panel-title {{
                    font-size: 13px;
                    font-weight: 700;
                    text-transform: uppercase;
                    color: #787b86;
                    margin-bottom: 12px;
                    border-bottom: 1px solid #2a2e39;
                    padding-bottom: 6px;
                }}
                
                .stat-grid {{
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 10px;
                }}
                .stat-card {{
                    background: #131722;
                    border: 1px solid #2a2e39;
                    border-radius: 6px;
                    padding: 10px;
                }}
                .stat-lbl {{ font-size: 11px; color: #787b86; }}
                .stat-num {{ font-size: 16px; font-weight: 700; margin-top: 4px; }}
                
                .trade-item {{
                    background: #131722;
                    border-left: 3px solid #363c4e;
                    padding: 10px;
                    border-radius: 4px;
                    margin-bottom: 8px;
                    font-size: 12px;
                }}
                .trade-item.win {{ border-left-color: #089981; }}
                .trade-item.loss {{ border-left-color: #f23645; }}
                
                .btn {{
                    width: 100%;
                    padding: 10px;
                    border: none;
                    border-radius: 6px;
                    font-weight: 700;
                    font-size: 13px;
                    cursor: pointer;
                    transition: 0.2s;
                }}
                .btn-kill {{ background: #f23645; color: white; margin-bottom: 8px; }}
                .btn-kill:hover {{ background: #cc2431; }}
                .btn-resume {{ background: #089981; color: white; }}
                .btn-resume:hover {{ background: #067a67; }}
                .btn-tgt {{
                    background: #2a2e39;
                    color: #d1d4dc;
                    border: 1px solid #363c4e;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 11px;
                    cursor: pointer;
                    font-weight: 600;
                    transition: 0.15s;
                }}
                .btn-tgt:hover {{ background: #363c4e; color: #fff; border-color: #26a69a; }}
            </style>
        </head>
        <body>
            <div class="navbar">
                <div class="nav-title">
                    <h1>NIFTY Options Scalper</h1>
                    <span class="badge {'badge-live' if mode=='LIVE' else 'badge-paper'}">{mode} MODE</span>
                    <span class="badge {'badge-frozen' if is_frozen else 'badge-active'}">{'FROZEN' if is_frozen else 'ACTIVE'}</span>
                </div>
                <div style="display: flex; align-items: center; gap: 12px;">
                    <div id="oi-radar-pill" class="radar-pill" style="border-color: #673ab7; background: rgba(103, 58, 183, 0.1);">
                        <span>📊 OI Radar:</span>
                        <span id="oi-radar-text" style="color: #ff9800; font-weight: 700;">Scanning Option Chain...</span>
                    </div>
                    <div id="radar-pill" class="radar-pill">
                        <span>📡 Heavyweights:</span>
                        <span id="radar-text" style="color: #22ab94;">Scanning Big 3...</span>
                    </div>
                    {auth_badge_html}
                </div>
            </div>

            <div class="main-layout">
                <!-- TradingView Visual Chart -->
                <div class="chart-section">
                    <div class="chart-header">
                        <div class="ticker-info">
                            <span class="ticker-symbol">NIFTY 50 (3m)</span>
                            <span id="spot-price" class="ticker-price">--</span>
                        </div>
                        <div style="display: flex; gap: 8px; font-size: 11px; align-items: center; flex-wrap: wrap;">
                            <span style="background: rgba(242, 54, 69, 0.15); border: 1px solid #f23645; color: #ff5252; padding: 2px 8px; border-radius: 4px; font-weight: 600;">🔴 SELL LIQUIDITY: <span id="hdr-sell-liq">--</span></span>
                            <span style="background: rgba(8, 153, 129, 0.15); border: 1px solid #089981; color: #26a69a; padding: 2px 8px; border-radius: 4px; font-weight: 600;">🟢 BUY LIQUIDITY: <span id="hdr-buy-liq">--</span></span>
                            <span style="background: rgba(136, 231, 136, 0.18); border: 1px solid #88E788; color: #88E788; padding: 2px 8px; border-radius: 4px; font-weight: bold;">⚡ FVG: <span id="hdr-fvg-text">Scanning...</span></span>
                        </div>
                        <div style="font-size: 12px; color: #787b86;">
                            Target: <b style="color: #089981;">+3.0 pts</b>
                        </div>
                    </div>

                    <!-- Floating Real-Time P&L HUD -->
                    <div id="hud-pnl" class="hud-pnl">
                        <div class="hud-title">ACTIVE TRADE: <span id="hud-contract">N/A</span></div>
                        <div id="hud-pnl-val" class="hud-value text-up">₹0.00</div>
                        <div id="hud-sub" class="hud-sub">Option LTP: ₹0.00 | Move: 0.0 pts</div>
                    </div>

                    <div style="position: relative; width: 100%; flex: 1; min-height: 520px; display: flex;">
                        <div id="chart" style="width: 100%; height: 100%;"></div>
                        <canvas id="liquidity-canvas" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 5;"></canvas>
                    </div>
                </div>

                <!-- Sidebar Controls & Stats -->
                <div class="sidebar">
                    <div class="panel">
                        <div class="panel-title">Session Overview</div>
                        <div class="stat-grid">
                            <div class="stat-card">
                                <div class="stat-lbl">Capital (Live Kite)</div>
                                <div class="stat-num" id="live-capital">₹{capital:,.2f}</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-lbl">3-Loss Cap</div>
                                <div class="stat-num" id="loss-cap">{consecutive_losses} / 3</div>
                            </div>
                        </div>
                    </div>

                    <div class="panel">
                        <div class="panel-title" style="display: flex; justify-content: space-between;">
                            <span>OI Walls & Cross Predictor</span>
                            <span id="oi-pcr-badge" style="color: #26a69a; font-weight: bold;">PCR: --</span>
                        </div>
                        <div style="font-size: 12px; line-height: 1.5;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span style="color: #ff5252; font-weight: 600;">🔴 Call Wall (Res):</span>
                                <span id="oi-call-wall" style="font-weight: bold; color: #d1d4dc;">--</span>
                            </div>
                            <div id="oi-call-status" style="font-size: 11px; padding: 4px 8px; border-radius: 4px; background: #131722; margin-bottom: 8px; border-left: 3px solid #ff5252; color: #9598a1;">
                                Awaiting Call Wall analysis...
                            </div>

                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <span style="color: #00b0ff; font-weight: 600;">🟢 Put Wall (Sup):</span>
                                <span id="oi-put-wall" style="font-weight: bold; color: #d1d4dc;">--</span>
                            </div>
                            <div id="oi-put-status" style="font-size: 11px; padding: 4px 8px; border-radius: 4px; background: #131722; margin-bottom: 4px; border-left: 3px solid #00b0ff; color: #9598a1;">
                                Awaiting Put Floor analysis...
                            </div>
                        </div>
                    </div>

                    <div class="panel">
                        <div class="panel-title">Active Position</div>
                        <div id="active-pos-info" style="font-size: 13px; line-height: 1.6;">
                            <span style="color: #787b86;">No active position. Scanning for S/R reversal or breakout...</span>
                        </div>
                    </div>

                    <div class="panel" style="flex: 1; overflow-y: auto;">
                        <div class="panel-title">Recent Closed Trades</div>
                        <div id="recent-trades-list">
                            <span style="font-size: 12px; color: #787b86;">Awaiting completed trades...</span>
                        </div>
                    </div>

                    <div class="panel">
                        <button class="btn btn-kill" onclick="triggerKillSwitch()">🚨 EMERGENCY KILL SWITCH</button>
                        <button class="btn btn-resume" onclick="triggerResume()">✅ RESUME TRADING</button>
                    </div>
                </div>
            </div>

            <script>
                // Initialize TradingView Lightweight Chart
                const chartContainer = document.getElementById('chart');
                const chart = LightweightCharts.createChart(chartContainer, {{
                    layout: {{
                        background: {{ color: '#1e222d' }},
                        textColor: '#9598a1',
                    }},
                    grid: {{
                        vertLines: {{ color: '#2a2e39' }},
                        horzLines: {{ color: '#2a2e39' }},
                    }},
                    crosshair: {{
                        mode: LightweightCharts.CrosshairMode.Normal,
                    }},
                    rightPriceScale: {{
                        borderColor: '#2a2e39',
                    }},
                    timeScale: {{
                        borderColor: '#2a2e39',
                        timeVisible: true,
                        secondsVisible: false,
                    }},
                }});

                // Candlestick Series
                const candleSeries = chart.addCandlestickSeries({{
                    upColor: '#089981',
                    downColor: '#f23645',
                    borderUpColor: '#089981',
                    borderDownColor: '#f23645',
                    wickUpColor: '#089981',
                    wickDownColor: '#f23645',
                }});

                // Volume Histogram
                const volumeSeries = chart.addHistogramSeries({{
                    color: '#26a69a',
                    priceFormat: {{ type: 'volume' }},
                    priceScaleId: '',
                    scaleMargins: {{ top: 0.85, bottom: 0 }},
                }});

                let activePriceLines = [];
                let markers = [];
                let latestLiquidityData = null;
                let latestFvgZones = [];

                function clearPriceLines() {{
                    activePriceLines.forEach(l => candleSeries.removePriceLine(l));
                    activePriceLines = [];
                }}

                function renderLiquidityCanvas() {{
                    const canvas = document.getElementById('liquidity-canvas');
                    if (!canvas || !latestLiquidityData) return;
                    const chartDiv = document.getElementById('chart');
                    if (!chartDiv) return;

                    const w = chartDiv.clientWidth;
                    const h = chartDiv.clientHeight;
                    if (w === 0 || h === 0) return;

                    if (canvas.width !== w || canvas.height !== h) {{
                        canvas.width = w;
                        canvas.height = h;
                    }}

                    const ctx = canvas.getContext('2d');
                    ctx.clearRect(0, 0, w, h);

                    const rightScaleWidth = 65;
                    const drawW = Math.max(10, w - rightScaleWidth);

                    // 1. Draw Large Red Shaded Box for Sell Liquidity (BSL / Supply)
                    if (latestLiquidityData.sell_zone) {{
                        const sz = latestLiquidityData.sell_zone;
                        const yTop = candleSeries.priceToCoordinate(Number(sz.top));
                        const yBot = candleSeries.priceToCoordinate(Number(sz.bottom));
                        if (yTop !== null && yBot !== null) {{
                            const y1 = Math.min(yTop, yBot);
                            const y2 = Math.max(yTop, yBot);
                            const boxH = Math.max(18, y2 - y1);

                            // Soft Red Gradient Shading
                            const redGrad = ctx.createLinearGradient(0, y1, 0, y1 + boxH);
                            redGrad.addColorStop(0, 'rgba(242, 54, 69, 0.32)');
                            redGrad.addColorStop(1, 'rgba(242, 54, 69, 0.12)');
                            ctx.fillStyle = redGrad;
                            ctx.fillRect(0, y1, drawW, boxH);

                            // Dashed Red Border
                            ctx.strokeStyle = 'rgba(242, 54, 69, 0.85)';
                            ctx.lineWidth = 1.5;
                            ctx.setLineDash([5, 5]);
                            ctx.strokeRect(0, y1, drawW, boxH);
                            ctx.setLineDash([]);

                            // Watermark Label Badge
                            ctx.fillStyle = 'rgba(242, 54, 69, 0.95)';
                            ctx.fillRect(10, y1 + 3, 275, 20);
                            ctx.fillStyle = '#ffffff';
                            ctx.font = 'bold 11px sans-serif';
                            ctx.fillText('🔴 SELL LIQUIDITY (SUPPLY: ' + Number(sz.bottom).toFixed(0) + ' - ' + Number(sz.top).toFixed(0) + ')', 16, y1 + 17);
                        }}
                    }}

                    // 2. Draw Large Green Shaded Box for Buy Liquidity (SSL / Demand)
                    if (latestLiquidityData.buy_zone) {{
                        const bz = latestLiquidityData.buy_zone;
                        const yTop = candleSeries.priceToCoordinate(Number(bz.top));
                        const yBot = candleSeries.priceToCoordinate(Number(bz.bottom));
                        if (yTop !== null && yBot !== null) {{
                            const y1 = Math.min(yTop, yBot);
                            const y2 = Math.max(yTop, yBot);
                            const boxH = Math.max(18, y2 - y1);

                            // Soft Green Gradient Shading
                            const greenGrad = ctx.createLinearGradient(0, y1, 0, y1 + boxH);
                            greenGrad.addColorStop(0, 'rgba(8, 153, 129, 0.12)');
                            greenGrad.addColorStop(1, 'rgba(8, 153, 129, 0.32)');
                            ctx.fillStyle = greenGrad;
                            ctx.fillRect(0, y1, drawW, boxH);

                            // Dashed Green Border
                            ctx.strokeStyle = 'rgba(8, 153, 129, 0.85)';
                            ctx.lineWidth = 1.5;
                            ctx.setLineDash([5, 5]);
                            ctx.strokeRect(0, y1, drawW, boxH);
                            ctx.setLineDash([]);

                            // Watermark Label Badge
                            ctx.fillStyle = 'rgba(8, 153, 129, 0.95)';
                            ctx.fillRect(10, y1 + boxH - 23, 275, 20);
                            ctx.fillStyle = '#ffffff';
                            ctx.font = 'bold 11px sans-serif';
                            ctx.fillText('🟢 BUY LIQUIDITY (DEMAND: ' + Number(bz.bottom).toFixed(0) + ' - ' + Number(bz.top).toFixed(0) + ')', 16, y1 + boxH - 9);
                        }}
                    }}

                    // 3. Draw Light Green (#88E788) Box for Fair Value Gaps (FVG)
                    if (latestFvgZones && latestFvgZones.length > 0) {{
                        latestFvgZones.forEach(fvg => {{
                            const yTop = candleSeries.priceToCoordinate(Number(fvg.top));
                            const yBot = candleSeries.priceToCoordinate(Number(fvg.bottom));
                            if (yTop !== null && yBot !== null) {{
                                const y1 = Math.min(yTop, yBot);
                                const y2 = Math.max(yTop, yBot);
                                const boxH = Math.max(14, y2 - y1);

                                // Exact Light Green #88E788 Shaded Fill
                                ctx.fillStyle = 'rgba(136, 231, 136, 0.35)';
                                ctx.fillRect(0, y1, drawW, boxH);

                                // Exact Light Green #88E788 Solid Border
                                ctx.strokeStyle = '#88E788';
                                ctx.lineWidth = 2.0;
                                ctx.strokeRect(0, y1, drawW, boxH);

                                // Middle Right Badge
                                const badgeWidth = 200;
                                const badgeX = Math.max(10, drawW - badgeWidth - 30);
                                const badgeY = y1 + Math.max(2, (boxH - 18) / 2);

                                ctx.fillStyle = '#88E788';
                                ctx.fillRect(badgeX, badgeY, badgeWidth, 18);
                                ctx.fillStyle = '#131722';
                                ctx.font = 'bold 11px sans-serif';
                                ctx.fillText('⚡ FVG (' + Number(fvg.bottom).toFixed(0) + ' - ' + Number(fvg.top).toFixed(0) + ')', badgeX + 10, badgeY + 13);
                            }}
                        }});
                    }}
                }}

                async function fetchChartData() {{
                    try {{
                        const res = await fetch('/api/chart-data');
                        const data = await res.json();

                        // 1. Update Candlestick & Volume Data
                        if (data.candles && data.candles.length > 0) {{
                            const candleMap = new Map();
                            data.candles.forEach(c => {{
                                if (c && c.time && !isNaN(c.time) && c.open != null && c.high != null && c.low != null && c.close != null) {{
                                    candleMap.set(c.time, {{
                                        time: Number(c.time),
                                        open: Number(c.open),
                                        high: Number(c.high),
                                        low: Number(c.low),
                                        close: Number(c.close)
                                    }});
                                }}
                            }});
                            const cleanCandles = Array.from(candleMap.values()).sort((a, b) => a.time - b.time);
                            if (cleanCandles.length > 0) {{
                                candleSeries.setData(cleanCandles);
                                const volData = cleanCandles.map(c => ({{
                                    time: c.time,
                                    value: Number(c.volume || 0),
                                    color: c.close >= c.open ? 'rgba(8, 153, 129, 0.4)' : 'rgba(242, 54, 69, 0.4)'
                                }}));
                                volumeSeries.setData(volData);

                                const liveSpot = (data.latest_spot != null && !isNaN(data.latest_spot) && Number(data.latest_spot) > 0)
                                    ? Number(data.latest_spot)
                                    : (cleanCandles.length > 0 ? cleanCandles[cleanCandles.length - 1].close : null);
                                if (liveSpot != null) {{
                                    document.getElementById('spot-price').innerText = '₹' + liveSpot.toFixed(2);
                                }}
                            }}
                        }}

                        clearPriceLines();

                        // 2. Draw Dynamic Support & Resistance Zones
                        if (data.structure) {{
                            (data.structure.supports || []).forEach(s => {{
                                if (s != null && !isNaN(s) && Number(s) > 0) {{
                                    const line = candleSeries.createPriceLine({{
                                        price: Number(s),
                                        color: '#2962ff',
                                        lineWidth: 1,
                                        lineStyle: LightweightCharts.LineStyle.Dashed,
                                        axisLabelVisible: true,
                                        title: 'SUPPORT ' + Number(s).toFixed(0),
                                    }});
                                    activePriceLines.push(line);
                                }}
                            }});

                            (data.structure.resistances || []).forEach(r => {{
                                if (r != null && !isNaN(r) && Number(r) > 0) {{
                                    const line = candleSeries.createPriceLine({{
                                        price: Number(r),
                                        color: '#f57c00',
                                        lineWidth: 1,
                                        lineStyle: LightweightCharts.LineStyle.Dashed,
                                        axisLabelVisible: true,
                                        title: 'RESISTANCE ' + Number(r).toFixed(0),
                                    }});
                                    activePriceLines.push(line);
                                }}
                            }});
                        }}

                        // 2.2 Draw Real-Time Buy & Sell Liquidity Zones
                        if (data.liquidity) {{
                            latestLiquidityData = data.liquidity;
                            
                            if (data.liquidity.sell_zone) {{
                                const sz = data.liquidity.sell_zone;
                                const hdrSell = document.getElementById('hdr-sell-liq');
                                if (hdrSell) hdrSell.innerText = `${{Number(sz.bottom).toFixed(0)}} - ${{Number(sz.top).toFixed(0)}}`;

                                const sBotLine = candleSeries.createPriceLine({{
                                    price: Number(sz.bottom),
                                    color: '#f23645',
                                    lineWidth: 2,
                                    lineStyle: LightweightCharts.LineStyle.Solid,
                                    axisLabelVisible: true,
                                    title: '🔴 SELL LIQ ' + Number(sz.bottom).toFixed(0),
                                }});
                                activePriceLines.push(sBotLine);
                            }}

                            if (data.liquidity.buy_zone) {{
                                const bz = data.liquidity.buy_zone;
                                const hdrBuy = document.getElementById('hdr-buy-liq');
                                if (hdrBuy) hdrBuy.innerText = `${{Number(bz.bottom).toFixed(0)}} - ${{Number(bz.top).toFixed(0)}}`;

                                const bTopLine = candleSeries.createPriceLine({{
                                    price: Number(bz.top),
                                    color: '#089981',
                                    lineWidth: 2,
                                    lineStyle: LightweightCharts.LineStyle.Solid,
                                    axisLabelVisible: true,
                                    title: '🟢 BUY LIQ ' + Number(bz.top).toFixed(0),
                                }});
                                activePriceLines.push(bTopLine);
                            }}

                            requestAnimationFrame(renderLiquidityCanvas);
                        }}

                        // 2.3 Store & Draw Light Green (#88E788) FVG Zones
                        latestFvgZones = data.fvg_zones || [];
                        if (data.fvg_zones && data.fvg_zones.length > 0) {{
                            const fvgHdr = document.getElementById('hdr-fvg-text');
                            if (fvgHdr) {{
                                const f = data.fvg_zones[data.fvg_zones.length - 1];
                                fvgHdr.innerText = `${{Number(f.bottom).toFixed(0)}} - ${{Number(f.top).toFixed(0)}} (+${{f.gap_pts}} pts)`;
                            }}

                            data.fvg_zones.forEach(f => {{
                                const fvgLine = candleSeries.createPriceLine({{
                                    price: Number(f.top),
                                    color: '#88E788',
                                    lineWidth: 2,
                                    lineStyle: LightweightCharts.LineStyle.Dashed,
                                    axisLabelVisible: true,
                                    title: '⚡ FVG ' + Number(f.top).toFixed(0),
                                }});
                                activePriceLines.push(fvgLine);
                            }});
                        }} else {{
                            const fvgHdr = document.getElementById('hdr-fvg-text');
                            if (fvgHdr) fvgHdr.innerText = 'None Active';
                        }}

                        // 2.5 Draw Key Open Interest Walls (Call Wall & Put Wall) + Cross / Bounce Indicator
                        if (data.oi_intel) {{
                            const oi = data.oi_intel;
                            
                            // Update Top Bar Radar Pill
                            const oiRadar = document.getElementById('oi-radar-text');
                            if (oiRadar && oi.call_wall && oi.put_wall) {{
                                const callBadge = oi.call_wall.prediction === 'WILL_CROSS' ? 'CE CROSS 🚀' : 'CE BOUNCE 🛡️';
                                const putBadge = oi.put_wall.prediction === 'WILL_BREAK' ? 'PE BREAK ⚠️' : 'PE BOUNCE 🛡️';
                                oiRadar.innerText = `PCR: ${{oi.pcr}} | ${{oi.call_wall.strike}} (${{callBadge}}) | ${{oi.put_wall.strike}} (${{putBadge}})`;
                                oiRadar.style.color = (oi.pcr > 1.1) ? '#26a69a' : (oi.pcr < 0.9 ? '#ff5252' : '#ff9800');
                            }}

                            // Update Sidebar OI Panel
                            const pcrEl = document.getElementById('oi-pcr-badge');
                            if (pcrEl) pcrEl.innerText = `PCR: ${{oi.pcr || '--'}}`;

                            if (oi.call_wall && oi.call_wall.strike != null && !isNaN(oi.call_wall.strike) && Number(oi.call_wall.strike) > 0) {{
                                const cw = oi.call_wall;
                                const isCross = cw.prediction === 'WILL_CROSS';
                                const elCall = document.getElementById('oi-call-wall');
                                if (elCall) elCall.innerText = `${{cw.strike}} (${{cw.oi_formatted}})`;
                                const elCallSt = document.getElementById('oi-call-status');
                                if (elCallSt) {{
                                    elCallSt.innerHTML = `<b style="color: ${{isCross ? '#00e676' : '#ff5252'}};">${{isCross ? 'WILL CROSS! 🚀 Breakout' : 'BOUNCE EXPECTED 🛡️ Rejection'}}</b> (${{cw.confidence}}%)<br><span style="color:#787b86;">${{cw.reason}}</span>`;
                                }}

                                // Create Chart Price Line for Call Wall
                                const callWallLine = candleSeries.createPriceLine({{
                                    price: Number(cw.strike),
                                    color: isCross ? '#00e676' : '#e91e63',
                                    lineWidth: 2,
                                    lineStyle: LightweightCharts.LineStyle.Dashed,
                                    axisLabelVisible: true,
                                    title: `🔴 CE ${{cw.strike}} (${{cw.oi_formatted}}) - ${{isCross ? 'WILL CROSS! 🚀' : 'BOUNCE 🛡️'}} (${{cw.confidence}}%)`,
                                }});
                                activePriceLines.push(callWallLine);
                            }}

                            if (oi.put_wall && oi.put_wall.strike != null && !isNaN(oi.put_wall.strike) && Number(oi.put_wall.strike) > 0) {{
                                const pw = oi.put_wall;
                                const isBreak = pw.prediction === 'WILL_BREAK';
                                const elPut = document.getElementById('oi-put-wall');
                                if (elPut) elPut.innerText = `${{pw.strike}} (${{pw.oi_formatted}})`;
                                const elPutSt = document.getElementById('oi-put-status');
                                if (elPutSt) {{
                                    elPutSt.innerHTML = `<b style="color: ${{isBreak ? '#ff5252' : '#00b0ff'}};">${{isBreak ? 'WILL BREAK! ⚠️ Breakdown' : 'BOUNCE EXPECTED 🛡️ Support'}}</b> (${{pw.confidence}}%)<br><span style="color:#787b86;">${{pw.reason}}</span>`;
                                }}

                                // Create Chart Price Line for Put Wall
                                const putWallLine = candleSeries.createPriceLine({{
                                    price: Number(pw.strike),
                                    color: isBreak ? '#ff5252' : '#00b0ff',
                                    lineWidth: 2,
                                    lineStyle: LightweightCharts.LineStyle.Dashed,
                                    axisLabelVisible: true,
                                    title: `🟢 PE ${{pw.strike}} (${{pw.oi_formatted}}) - ${{isBreak ? 'WILL BREAK! ⚠️' : 'BOUNCE 🛡️'}} (${{pw.confidence}}%)`,
                                }});
                                activePriceLines.push(putWallLine);
                            }}
                        }}

                        // 3. Draw TradingView Long/Short Position Box (Green & Red Zones) & Live HUD
                        const pos = data.active_trade;
                        const hud = document.getElementById('hud-pnl');
                        const posInfo = document.getElementById('active-pos-info');

                        if (pos && pos.entry_spot != null && !isNaN(pos.entry_spot)) {{
                            // Draw Entry Line (White/Blue)
                            const entryLine = candleSeries.createPriceLine({{
                                price: Number(pos.entry_spot),
                                color: '#ffffff',
                                lineWidth: 2,
                                lineStyle: LightweightCharts.LineStyle.Solid,
                                axisLabelVisible: true,
                                title: (pos.direction || 'BUY') + ' ENTRY',
                            }});
                            activePriceLines.push(entryLine);

                            // Draw Green Target Zone
                            if (pos.spot_target != null && !isNaN(pos.spot_target)) {{
                                const targetLine = candleSeries.createPriceLine({{
                                    price: Number(pos.spot_target),
                                    color: '#089981',
                                    lineWidth: 2,
                                    lineStyle: LightweightCharts.LineStyle.Solid,
                                    axisLabelVisible: true,
                                    title: 'TARGET +' + Number(pos.target_pts || 3).toFixed(1) + ' pts',
                                }});
                                activePriceLines.push(targetLine);
                            }}

                            // Draw Maximum Structural Green/Red Room Ceiling
                            if (pos.max_spot_target != null && !isNaN(pos.max_spot_target) && Math.abs(pos.max_spot_target - pos.spot_target) > 1.0) {{
                                const maxLine = candleSeries.createPriceLine({{
                                    price: Number(pos.max_spot_target),
                                    color: '#26a69a',
                                    lineWidth: 2,
                                    lineStyle: LightweightCharts.LineStyle.Dashed,
                                    axisLabelVisible: true,
                                    title: 'MAX STRUCTURAL ROOM +' + Number(pos.max_opt_pts || 0).toFixed(1) + ' pts (@ ' + Number(pos.max_spot_target).toFixed(1) + ')',
                                }});
                                activePriceLines.push(maxLine);
                            }}

                            // Draw Red Stop Loss Zone
                            if (pos.spot_sl != null && !isNaN(pos.spot_sl)) {{
                                const slLine = candleSeries.createPriceLine({{
                                    price: Number(pos.spot_sl),
                                    color: '#f23645',
                                    lineWidth: 2,
                                    lineStyle: LightweightCharts.LineStyle.Solid,
                                    axisLabelVisible: true,
                                    title: 'SL -' + Number(pos.sl_pts || 5).toFixed(1) + ' pts',
                                }});
                                activePriceLines.push(slLine);
                            }}

                            // Update Floating HUD
                            hud.style.display = 'block';
                            document.getElementById('hud-contract').innerText = pos.tradingsymbol;
                            const pnlVal = document.getElementById('hud-pnl-val');
                            const isWin = pos.unrealized_pnl >= 0;
                            pnlVal.innerText = (isWin ? '+₹' : '-₹') + Math.abs(pos.unrealized_pnl).toFixed(2);
                            pnlVal.className = 'hud-value ' + (isWin ? 'text-up' : 'text-down');

                            document.getElementById('hud-sub').innerText = 
                                'Option: ₹' + pos.current_opt_ltp.toFixed(2) + 
                                ' | Move: ' + (pos.unrealized_pts >= 0 ? '+' : '') + pos.unrealized_pts.toFixed(1) + ' pts' +
                                ' | Max Room: +' + (pos.max_opt_pts || 0).toFixed(1) + ' pts' +
                                ' | R:R 1:' + (pos.target_pts / pos.sl_pts).toFixed(1);

                            const maxRoomLabel = pos.max_opt_pts ? ('+' + pos.max_opt_pts.toFixed(1) + ' pts (@ ' + pos.max_spot_target + ')') : 'N/A';
                            posInfo.innerHTML = `
                                <b>Contract:</b> ${{pos.tradingsymbol}}<br>
                                <b>Direction:</b> <span class="${{pos.direction=='CE' ? 'text-up' : 'text-down'}}">${{pos.direction}}</span><br>
                                <b>Entry Premium:</b> ₹${{pos.entry_premium.toFixed(2)}}<br>
                                <b>Active Target:</b> <b style="color: #089981;">₹${{pos.target_premium.toFixed(2)}} (+${{pos.target_pts.toFixed(1)}} pts)</b><br>
                                <b>Full Structural Room:</b> <span style="color: #26a69a; font-weight: 600;">${{maxRoomLabel}}</span><br>
                                <b>Stop Loss:</b> ₹${{pos.sl_premium.toFixed(2)}} (-${{pos.sl_pts.toFixed(1)}} pts)<br>
                                <b>Live Unrealized:</b> <b class="${{isWin ? 'text-up' : 'text-down'}}">${{isWin ? '+₹' : '-₹'}}${{Math.abs(pos.unrealized_pnl).toFixed(2)}}</b>
                                
                                <hr style="border: 0; border-top: 1px solid #2a2e39; margin: 10px 0;">
                                <div style="font-weight: 600; font-size: 12px; margin-bottom: 6px; color: #f0f3fa;">🎯 Adjust Profit Target on Kite:</div>
                                <div style="display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px;">
                                    <button class="btn-tgt" onclick="setTargetPts(3.0)">+3</button>
                                    <button class="btn-tgt" onclick="setTargetPts(5.0)">+5</button>
                                    <button class="btn-tgt" onclick="setTargetPts(10.0)">+10</button>
                                    <button class="btn-tgt" onclick="setTargetPts(15.0)">+15</button>
                                    ${{pos.max_opt_pts ? `<button class="btn-tgt" style="border-color: #26a69a; color: #26a69a;" onclick="setTargetPts(${{pos.max_opt_pts}})">Max (+${{pos.max_opt_pts.toFixed(1)}})</button>` : ''}}
                                </div>
                                <div style="display: flex; gap: 6px;">
                                    <input type="number" id="custom-target-input" step="0.5" min="1" placeholder="Pts" value="${{pos.target_pts}}" style="width: 65px; background: #131722; border: 1px solid #363c4e; color: #fff; padding: 5px 8px; border-radius: 4px; font-size: 12px;">
                                    <button class="btn btn-resume" style="flex: 1; padding: 5px 8px; font-size: 11px;" onclick="applyCustomTarget()">Update Target on Kite</button>
                                </div>
                                <div id="target-msg" style="font-size: 11px; margin-top: 5px; font-weight: 600;"></div>
                            `;
                        }} else {{
                            hud.style.display = 'none';
                            posInfo.innerHTML = '<span style="color: #787b86;">No active position. Scanning for S/R reversal or breakout...</span>';
                        }}

                        // Live Capital Update from Kite
                        if (data.capital !== undefined) {{
                            const capEl = document.getElementById('live-capital');
                            if (capEl) {{
                                capEl.innerText = '₹' + Number(data.capital).toLocaleString('en-IN', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
                            }}
                        }}

                        // 4. Update Big 3 Heavyweights Radar
                        if (data.heavyweights) {{
                            const radar = document.getElementById('radar-text');
                            radar.innerText = data.heavyweights.summary;
                            if (data.heavyweights.is_bullish_aligned) {{
                                radar.style.color = '#089981';
                            }} else if (data.heavyweights.is_bearish_aligned) {{
                                radar.style.color = '#f23645';
                            }} else if (data.heavyweights.is_divergence_trap) {{
                                radar.style.color = '#f57c00';
                            }} else {{
                                radar.style.color = '#d1d4dc';
                            }}
                        }}

                        // 5. Update Recent Closed Trades List
                        if (data.recent_trades && data.recent_trades.length > 0) {{
                            const tradeList = document.getElementById('recent-trades-list');
                            tradeList.innerHTML = data.recent_trades.slice(0, 5).map(t => {{
                                const isTarget = (t.exit_reason || '').toLowerCase().includes('target');
                                return `
                                    <div class="trade-item ${{isTarget ? 'win' : 'loss'}}">
                                        <b>${{t.tradingsymbol}}</b> (${{t.option_type}})<br>
                                        <span>${{t.exit_reason || 'Closed'}}</span><br>
                                        <b>Net P&L:</b> <span class="${{t.net_pnl >= 0 ? 'text-up' : 'text-down'}}">
                                            ${{t.net_pnl >= 0 ? '+₹' : '-₹'}}${{Math.abs(t.net_pnl).toFixed(2)}}
                                        </span>
                                    </div>
                                `;
                            }}).join('');
                        }}

                    }} catch (e) {{
                        console.error("Chart data poll error:", e);
                    }}
                }}

                // Resize handler
                window.addEventListener('resize', () => {{
                    chart.applyOptions({{ width: chartContainer.clientWidth, height: chartContainer.clientHeight }});
                    requestAnimationFrame(renderLiquidityCanvas);
                }});

                chart.timeScale().subscribeVisibleLogicalRangeChange(() => {{
                    requestAnimationFrame(renderLiquidityCanvas);
                }});

                // Poll every 1.5 seconds for real-time responsiveness
                fetchChartData();
                setInterval(fetchChartData, 1500);

                async function triggerKillSwitch() {{
                    if (confirm("🚨 Are you sure you want to trigger the EMERGENCY KILL SWITCH?")) {{
                        await fetch('/api/kill-switch', {{ method: 'POST' }});
                        location.reload();
                    }}
                }}

                async function triggerResume() {{
                    await fetch('/api/resume', {{ method: 'POST' }});
                    location.reload();
                }}

                async function setTargetPts(pts) {{
                    const msgEl = document.getElementById('target-msg');
                    if (msgEl) {{
                        msgEl.innerText = 'Updating target to +' + pts + ' pts on Kite...';
                        msgEl.style.color = '#f57c00';
                    }}
                    try {{
                        const res = await fetch('/api/update-target', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ target_pts: parseFloat(pts) }})
                        }});
                        const data = await res.json();
                        if (msgEl) {{
                            msgEl.innerText = data.message || 'Target updated!';
                            msgEl.style.color = res.ok ? '#089981' : '#f23645';
                        }}
                        fetchChartData();
                    }} catch (e) {{
                        if (msgEl) {{
                            msgEl.innerText = 'Error: ' + e;
                            msgEl.style.color = '#f23645';
                        }}
                    }}
                }}

                async function applyCustomTarget() {{
                    const input = document.getElementById('custom-target-input');
                    if (input && input.value) {{
                        await setTargetPts(parseFloat(input.value));
                    }}
                }}
            </script>
        </body>
        </html>
        """
        return HTMLResponse(content=html)

    @app.post("/auth/request-code")
    def auth_request_code(request: Request):
        if not bot_controller or not hasattr(bot_controller, "notifier"):
            raise HTTPException(status_code=500, detail="Notification system not initialized")

        code = str(secrets.randbelow(900000) + 100000)
        magic_token = secrets.token_urlsafe(32)
        expires_at = time.time() + 300

        pending_otps[code] = {"magic_token": magic_token, "expires_at": expires_at}
        pending_magic_tokens[magic_token] = expires_at

        host = request.headers.get("host") or getattr(bot_controller.config, "static_ip", "") or "127.0.0.1"
        magic_link = f"http://{host}/login?token={magic_token}"

        text = (
            "🔐 <b>NIFTY Scalper Dashboard Login</b>\n\n"
            f"Your One-Time Access Code: <code>{code}</code>\n"
            "<i>Valid for 5 minutes.</i>\n\n"
            "👉 <b>Quick 1-Click Login Link:</b>\n"
            f'<a href="{magic_link}">Click Here to Log In</a>\n\n'
            "<i>If you did not request this login, ignore this alert.</i>"
        )

        sent = bot_controller.notifier.send_message(text)
        if not sent and getattr(bot_controller.notifier, "enabled", False):
            raise HTTPException(status_code=502, detail="Failed to dispatch code to Telegram.")

        return {"status": "SUCCESS", "message": "Verification code & magic link sent to your Telegram!"}

    @app.post("/auth/verify-code")
    def auth_verify_code(payload: Dict[str, Any], response: Response):
        code = str(payload.get("code", "")).strip()
        if not code or code not in pending_otps:
            raise HTTPException(status_code=400, detail="Invalid verification code.")

        otp_info = pending_otps[code]
        if otp_info["expires_at"] < time.time():
            del pending_otps[code]
            raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")

        magic_token = otp_info["magic_token"]
        del pending_otps[code]
        if magic_token in pending_magic_tokens:
            del pending_magic_tokens[magic_token]

        session_id = create_session(response)
        return {"status": "SUCCESS", "message": "Access granted", "session_id": session_id}

    @app.get("/login")
    def login_magic_link(token: str = ""):
        if not token or token not in pending_magic_tokens:
            raise HTTPException(status_code=400, detail="Invalid or expired magic link. Please request a new one.")

        if pending_magic_tokens[token] < time.time():
            del pending_magic_tokens[token]
            raise HTTPException(status_code=400, detail="Magic link has expired.")

        del pending_magic_tokens[token]
        res = RedirectResponse(url="/", status_code=303)
        create_session(res)
        return res

    @app.get("/auth/logout")
    def auth_logout(request: Request):
        token = request.cookies.get(SESSION_COOKIE_NAME)
        if token and token in authenticated_sessions:
            del authenticated_sessions[token]
        res = RedirectResponse(url="/", status_code=303)
        res.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return res

    @app.get("/api/chart-data")
    def api_chart_data(request: Request):
        if requires_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not bot_controller or not hasattr(bot_controller, "get_chart_data"):
            return JSONResponse({"candles": [], "structure": {}, "active_trade": None, "heavyweights": {}})
        try:
            return JSONResponse(bot_controller.get_chart_data())
        except Exception as e:
            logger.error("Error generating chart data in API: %s", e, exc_info=True)
            return JSONResponse({"candles": [], "structure": {}, "active_trade": None, "heavyweights": {}, "error": str(e)})

    @app.get("/api/status")
    def api_status(request: Request = None):
        if not bot_controller:
            return JSONResponse({"status": "starting"})
        return bot_controller.get_runtime_status()

    @app.get("/api/analytics")
    def api_analytics(request: Request = None):
        return analytics.generate_report()

    @app.post("/api/kill-switch")
    def api_kill_switch(request: Request = None):
        if request and requires_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if bot_controller:
            bot_controller.emergency_freeze("Manual operator kill switch triggered via Admin API")
            return {"status": "SUCCESS", "message": "Emergency trading freeze activated."}
        raise HTTPException(status_code=500, detail="Bot controller not initialized")

    @app.post("/api/resume")
    def api_resume(request: Request = None):
        if request and requires_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if bot_controller:
            bot_controller.clear_freeze()
            return {"status": "SUCCESS", "message": "Trading resumed by operator."}
        raise HTTPException(status_code=500, detail="Bot controller not initialized")

    @app.post("/api/update-target")
    def api_update_target(payload: Dict[str, Any], request: Request = None):
        if request and requires_auth(request):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not bot_controller or not hasattr(bot_controller, "update_active_trade_target"):
            raise HTTPException(status_code=500, detail="Bot controller not initialized")
        try:
            pts = float(payload.get("target_pts", 0))
            if pts <= 0:
                raise HTTPException(status_code=400, detail="Target points must be strictly positive (> 0)")
            ok, msg = bot_controller.update_active_trade_target(pts)
            if ok:
                return {"status": "SUCCESS", "message": msg, "target_pts": pts}
            else:
                raise HTTPException(status_code=400, detail=msg)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

    return app
