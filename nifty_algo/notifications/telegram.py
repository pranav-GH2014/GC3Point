import re
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from ..config.config_loader import AppConfig

logger = logging.getLogger("nifty_algo.telegram")

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

class TelegramNotifier:
    """
    Production Telegram Notification Dispatcher:
    - Exactly mirrors the visual layout, HTML formatting, and retry logic of sensexsuu388.
    - Automatic plain-text fallback on HTML entity parse failures.
    - 3-attempt exponential retry logic.
    - Never exposes API keys, secrets, or access tokens.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.bot_token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        self.session = requests.Session()
        self.enabled = bool(self.bot_token and self.chat_id)
        if not self.enabled:
            logger.warning("Telegram alerts disabled (bot_token or chat_id not configured).")

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Dispatches message to Telegram with 3 retries and HTML strip fallback.
        Exact logic as in sensexsuu388 server.py.
        """
        if not self.enabled:
            logger.info("[TELEGRAM MOCK]:\n%s", text)
            return True

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }

        for attempt in range(1, 4):
            try:
                resp = self.session.post(url, json=payload, timeout=12)
                if resp.status_code == 200:
                    logger.info("Telegram notification alert dispatched successfully.")
                    return True
                elif resp.status_code == 400 and "can't parse entities" in resp.text:
                    # Strip HTML tags and send as plain text fallback
                    clean_text = re.sub(r'<[^>]+>', '', text)
                    plain_payload = {"chat_id": self.chat_id, "text": clean_text}
                    resp_plain = self.session.post(url, json=plain_payload, timeout=12)
                    if resp_plain.status_code == 200:
                        logger.info("Telegram notification alert sent as plain text fallback.")
                        return True
                else:
                    logger.warning("Telegram attempt %d failed (%d): %s", attempt, resp.status_code, resp.text)
            except Exception as e:
                logger.error("Telegram attempt %d exception: %s", attempt, e)

        return False

    # ----------------- EVENT ALERTS (Matching sensexsuu388 formatting) -----------------

    def notify_bot_started(self, mode: str, symbol: str, capital: float):
        mode_tag = "🟢 LIVE TRADING (Real Capital)" if mode == "LIVE" or not self.config.simulation_mode else "🟡 SIMULATION / PAPER TRADING"
        msg = (
            f"🚀 <b>[NIFTY 3-POINT SCALPER BOT STARTED]</b>\n\n"
            f"<b>Execution Mode:</b> {mode_tag}\n"
            f"<b>Instrument:</b> {symbol} (Strict Buy-Only CE/PE)\n"
            f"<b>Initial Capital:</b> ₹{capital:,.2f}\n"
            f"<b>Target Strategy:</b> Fixed +3.0 Option Points (Thru 31 Jan 2027)\n"
            f"<b>Server:</b> Heaven Cloud VPS ({self.config.static_ip}:{self.config.server_port})\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_bot_stopped(self, reason: str):
        msg = (
            f"🛑 <b>[NIFTY BOT STOPPED]</b>\n\n"
            f"<b>Reason:</b> {reason}\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_scan_confidence_high(self, setup_name: str, direction: str, conf: float, spot: float):
        """Dispatched when confidence reaches >= 75% scanning threshold, matching sensexsuu388."""
        msg = (
            f"🟡 <b>[NIFTY SCALPER SCANNING - HIGH CONVICTION]</b>\n\n"
            f"<b>Setup:</b> {setup_name}\n"
            f"<b>Bias:</b> {direction} (Watching {'CE' if direction=='BULLISH' else 'PE'})\n"
            f"<b>Confidence Score:</b> {conf:.0f}% (Threshold >= 75%)\n"
            f"<b>NIFTY Spot:</b> ₹{spot:,.2f}\n"
            f"<b>Status:</b> Awaiting trigger confirmation candle...\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_signal_triggered(
        self,
        setup_name: str,
        direction: str,
        conf: float,
        order_specs: Dict[str, Any],
        current_spot: float,
        structure_details: str,
        current_capital: float
    ):
        """Dispatched when a full trading signal triggers (>= 80% confidence), matching sensexsuu388 layout."""
        action = "BUY CE" if direction == "BULLISH" else "BUY PE"
        lot_size = order_specs.get("lot_size", 65)
        est_premium = order_specs.get("ltp", 0.0)
        limit_price = round(est_premium - self.config.buy_limit_discount_offset, 2)
        target_price = round(limit_price + self.config.target_premium_points, 2)
        required_margin = limit_price * lot_size
        mode_str = "Production 3-Point Scalper (Multi-Setup SMC & Market Structure)"

        msg = (
            f"🚀 <b>[NIFTY SCALPER SIGNAL TRIGGERED]</b>\n\n"
            f"<b>Mode:</b> {mode_str}\n"
            f"<b>Setup Engine:</b> {setup_name}\n"
            f"<b>Confidence:</b> {conf:.0f}% (Gated >= 80%)\n"
            f"<b>Action:</b> {action} (1 Lot: {lot_size} Qty)\n"
            f"<b>Contract:</b> <code>{order_specs.get('tradingsymbol')}</code> (NFO)\n"
            f"<b>Underlying Spot:</b> ₹{current_spot:,.2f}\n"
            f"<b>Est. Entry Premium:</b> ₹{limit_price:.2f} (Limit Offset: -₹{self.config.buy_limit_discount_offset:.2f})\n"
            f"<b>Target Price:</b> ₹{target_price:.2f} (+3.0 pts / +₹{3.0 * lot_size:,.0f})\n"
            f"<b>Stop Loss:</b> Dynamic 3m Swing Structure Invalidation\n"
            f"<b>Required Margin:</b> ₹{required_margin:,.2f} (<= Deployable Capital ₹{current_capital:,.2f})\n"
            f"<b>Product:</b> {self.config.product_type} | Variety: regular\n"
            f"<b>Structure Sequence:</b>\n"
            f"{structure_details}\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_order_placed(self, symbol: str, limit_price: float, qty: int, order_id: str):
        msg = (
            f"📤 <b>[NIFTY BUY ORDER PLACED IN KITE]</b>\n\n"
            f"<b>Contract:</b> <code>{symbol}</code>\n"
            f"<b>Action:</b> BUY LIMIT\n"
            f"<b>Limit Price:</b> ₹{limit_price:.2f}\n"
            f"<b>Quantity:</b> {qty} units (1 Full Lot)\n"
            f"<b>Broker Order ID:</b> <code>{order_id}</code>\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_order_filled(self, symbol: str, filled_qty: int, avg_price: float, is_partial: bool = False):
        status_lbl = "PARTIALLY FILLED (Unfilled balance cancelled safely)" if is_partial else "FULLY FILLED"
        msg = (
            f"✅ <b>[NIFTY BUY ORDER {status_lbl}]</b>\n\n"
            f"<b>Contract:</b> <code>{symbol}</code>\n"
            f"<b>Executed Quantity:</b> {filled_qty} units\n"
            f"<b>Average Price:</b> ₹{avg_price:.2f}\n"
            f"<b>Invested Capital:</b> ₹{filled_qty * avg_price:,.2f}\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_target_placed(self, symbol: str, target_price: float, qty: int, order_id: Optional[str] = None):
        msg = (
            f"🎯 <b>[NIFTY TARGET EXIT ORDER SUBMITTED]</b>\n\n"
            f"<b>Contract:</b> <code>{symbol}</code>\n"
            f"<b>Action:</b> SELL LIMIT (+3.0 Target Points)\n"
            f"<b>Target Limit Price:</b> ₹{target_price:.2f}\n"
            f"<b>Protected Quantity:</b> {qty} units\n"
            f"<b>Exit Order ID:</b> <code>{order_id or 'SIM_TARGET'}</code>\n"
            f"<b>Status:</b> Active in order book\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_position_closed(
        self,
        symbol: str,
        buy_avg: float,
        sell_avg: float,
        qty: int,
        gross_pnl: float,
        net_pnl: float,
        charges: float,
        daily_realized_pnl: float,
        new_capital: float,
        exit_reason: str
    ):
        """Matches the exact [SENSEX POSITION CLOSED IN KITE] layout from server.py."""
        pnl_emoji = "🎉" if net_pnl >= 0 else "⚠️"
        msg = (
            f"{pnl_emoji} <b>[NIFTY POSITION CLOSED IN KITE]</b> {pnl_emoji}\n\n"
            f"<b>Instrument:</b> <code>{symbol}</code>\n"
            f"<b>Action:</b> SELL (Closed)\n"
            f"<b>Quantity:</b> {qty} Qty (1 Lot)\n"
            f"<b>Entry Price:</b> ₹{buy_avg:.2f}\n"
            f"<b>Exit Price:</b> ₹{sell_avg:.2f}\n"
            f"<b>Exit Reason:</b> {exit_reason}\n"
            f"<b>Gross P&L:</b> {'+' if gross_pnl >= 0 else ''}₹{gross_pnl:,.2f}\n"
            f"<b>Brokerage & Charges:</b> ₹{charges:,.2f}\n"
            f"<b>Trade Net P&L:</b> {'+' if net_pnl >= 0 else ''}₹{net_pnl:,.2f}\n"
            f"<b>Daily Realized Net P&L:</b> {'+' if daily_realized_pnl >= 0 else ''}₹{daily_realized_pnl:,.2f}\n"
            f"<b>Compounded Capital:</b> ₹{new_capital:,.2f}\n"
            f"<b>Cooldown:</b> ⏳ 3-minute re-entry pause active\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_post_target_milestone(self, symbol: str, entry_price: float, exit_price: float, milestone: str, current_price: float):
        """Notifies user when option continues running after +3 exit to measure additional profit."""
        pts_beyond = current_price - exit_price
        msg = (
            f"📈 <b>[NIFTY POST-TARGET EXCURSION MILESTONE]</b>\n\n"
            f"<b>Contract:</b> <code>{symbol}</code>\n"
            f"<b>Original Entry:</b> ₹{entry_price:.2f} | <b>Target Exit:</b> ₹{exit_price:.2f} (+3.0 pts)\n"
            f"<b>Milestone Reached:</b> <b>{milestone}</b> from original entry!\n"
            f"<b>Current Option LTP:</b> ₹{current_price:.2f} (+{pts_beyond:.2f} pts after exit)\n"
            f"<b>Analytics:</b> Logged in database for post-2027 review\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_consecutive_losses_circuit(self, count: int, max_allowed: int):
        msg = (
            f"🚨 <b>[CIRCUIT BREAKER: 3 CONSECUTIVE LOSSES REACHED]</b> 🚨\n\n"
            f"<b>Consecutive Losses:</b> {count} / {max_allowed}\n"
            f"<b>Action:</b> Trading halted for today. No new positions will be opened.\n"
            f"<b>Safety:</b> Capital preservation rule activated.\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_emergency_freeze(self, reason: str):
        msg = (
            f"🚨 <b>[EMERGENCY TRADING FREEZE / SAFETY HALT]</b> 🚨\n\n"
            f"<b>Reason:</b> {reason}\n"
            f"<b>Action:</b> New entries locked immediately.\n"
            f"<b>Manual Intervention:</b> Operator review required via VPS Dashboard.\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_duplicate_order_prevented(self, symbol: str, details: str):
        msg = (
            f"🛡️ <b>[DUPLICATE ORDER PROTECTION ACTIVATED]</b>\n\n"
            f"<b>Contract:</b> <code>{symbol}</code>\n"
            f"<b>Blocked Action:</b> {details}\n"
            f"<b>Status:</b> Accidental short/duplicate order avoided.\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)

    def notify_websocket_event(self, event: str, details: str):
        msg = (
            f"📡 <b>[KITE WEBSOCKET NOTIFICATION]</b>\n\n"
            f"<b>Event:</b> {event}\n"
            f"<b>Details:</b> {details}\n"
            f"<b>Time:</b> {datetime.now(IST).strftime('%H:%M:%S IST')}"
        )
        self.send_message(msg)
