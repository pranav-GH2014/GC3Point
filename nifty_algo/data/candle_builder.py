import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Callable
import pandas as pd

logger = logging.getLogger("nifty_algo.candles")

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

class MultiTimeframeCandleAggregator:
    """
    Maintains and builds streaming completed candles across 1m, 3m, 5m, and 15m intervals.
    Filters duplicate ticks and handles stale data.
    """

    def __init__(self, token: int, on_candle_close: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.token = token
        self.on_candle_close = on_candle_close
        self.last_tick_time: Optional[datetime] = None
        self.last_tick_price: Optional[float] = None
        
        # Buffer for current forming candle per timeframe: { "1m": {...}, "3m": {...}, ... }
        self.timeframes = ["1m", "3m", "5m", "15m"]
        self.tf_minutes = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}
        self.forming_candles: Dict[str, Optional[Dict[str, Any]]] = {tf: None for tf in self.timeframes}
        self.history: Dict[str, List[Dict[str, Any]]] = {tf: [] for tf in self.timeframes}
        self.max_history = 500

    def load_historical_candles(self, timeframe: str, candles: List[Dict[str, Any]]):
        """Pre-populates indicator and structure calculation history from Kite historical API."""
        if timeframe in self.history:
            self.history[timeframe] = candles[-self.max_history:]
            logger.info("Loaded %d historical %s candles for token %d", len(candles), timeframe, self.token)

    def on_tick(self, tick: Dict[str, Any]):
        """Processes an incoming live tick and triggers candle roll-over on completion."""
        last_price = tick.get("last_price")
        if last_price is None or last_price <= 0:
            return

        tick_timestamp = tick.get("last_trade_time") or tick.get("exchange_timestamp")
        if not tick_timestamp:
            tick_timestamp = datetime.now(IST)
        elif tick_timestamp.tzinfo is None:
            tick_timestamp = tick_timestamp.replace(tzinfo=IST)
        else:
            tick_timestamp = tick_timestamp.astimezone(IST)

        # Check stale tick
        if self.last_tick_time and tick_timestamp < self.last_tick_time:
            # Out-of-order or duplicate tick
            return

        volume = tick.get("volume", 0)
        self.last_tick_time = tick_timestamp
        self.last_tick_price = last_price

        for tf in self.timeframes:
            self._update_timeframe(tf, tick_timestamp, last_price, volume)

    def _get_candle_bucket_start(self, dt: datetime, minutes: int) -> datetime:
        total_minutes = dt.minute
        bucket_minute = (total_minutes // minutes) * minutes
        return dt.replace(minute=bucket_minute, second=0, microsecond=0)

    def _update_timeframe(self, tf: str, dt: datetime, price: float, cum_volume: int):
        mins = self.tf_minutes[tf]
        bucket_start = self._get_candle_bucket_start(dt, mins)
        current = self.forming_candles[tf]

        if current is None:
            self.forming_candles[tf] = {
                "date": bucket_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
                "start_cum_volume": cum_volume
            }
            return

        if bucket_start > current["date"]:
            # Previous candle is complete!
            completed_candle = {
                "date": current["date"],
                "open": current["open"],
                "high": current["high"],
                "low": current["low"],
                "close": current["close"],
                "volume": max(0, cum_volume - current.get("start_cum_volume", cum_volume))
            }
            self.history[tf].append(completed_candle)
            if len(self.history[tf]) > self.max_history:
                self.history[tf].pop(0)

            # Notify listener
            if self.on_candle_close:
                self.on_candle_close(tf, completed_candle)

            # Start new forming candle
            self.forming_candles[tf] = {
                "date": bucket_start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
                "start_cum_volume": cum_volume
            }
        else:
            # Update current forming candle
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price

    def get_dataframe(self, tf: str) -> pd.DataFrame:
        if not self.history[tf]:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(self.history[tf])
        try:
            df["date"] = pd.to_datetime(df["date"], utc=True)
        except Exception:
            try:
                df["date"] = pd.to_datetime(df["date"])
            except Exception as e:
                logger.warning("Error converting candle dates to datetime: %s", e)
        return df
