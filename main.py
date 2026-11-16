import os
import sys
import time
import signal
import logging
import argparse
import threading
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

from typing import Dict, Any, List, Optional, Tuple
import uvicorn

from nifty_algo.config.config_loader import ConfigLoader, AppConfig
from nifty_algo.database.db import DatabaseManager
from nifty_algo.data.kite_client import SafeKiteClient
from nifty_algo.data.websocket_feed import RobustWebSocketFeed
from nifty_algo.data.candle_builder import MultiTimeframeCandleAggregator
from nifty_algo.indicators.technical import TechnicalIndicators
from nifty_algo.indicators.volume_profile import VolumeProfileAnalyzer
from nifty_algo.indicators.open_interest import OpenInterestAnalyzer
from nifty_algo.market_structure.structure_engine import MarketStructureEngine
from nifty_algo.strategies import (
    BreakoutRetestSetup,
    LiquiditySweepReversalSetup,
    VWAPReclaimSetup,
    VWAPRejectionSetup,
    TrendContinuationSetup,
    OpeningRangeBreakoutSetup,
    SupportReversalSetup,
    ResistanceRejectionSetup,
    FVGConfirmationSetup,
)
from nifty_algo.strategies.opportunity_engine import OpportunityEngine, OpportunityDecision
from nifty_algo.strategies.multi_opportunity_coordinator import MultiOpportunityCoordinator
from nifty_algo.execution.trade_execution_engine import TradeExecutionEngine
from nifty_algo.confidence.scorer import ConfidenceScorer
from nifty_algo.option_selector.selector import OptionSelector
from nifty_algo.risk.risk_manager import RiskManager, PreLiveCheckFailedError
from nifty_algo.risk.charges import ZerodhaOptionChargesCalculator
from nifty_algo.execution.order_manager import OrderExecutionManager
from nifty_algo.execution.exit_manager import ExitSafetyManager, BrokerStateUncertainError
from nifty_algo.execution.reconciler import BrokerReconciler
from nifty_algo.position_manager.position_tracker import PositionTracker
from nifty_algo.position_manager.overnight_manager import OvernightPositionManager
from nifty_algo.post_target_logger.logger import PostTargetMovementLogger
from nifty_algo.notifications.telegram import TelegramNotifier
from nifty_algo.monitoring.server_admin import create_admin_app
from nifty_algo.indicators.heavyweight_alignment_engine import HeavyweightAlignmentEngine

# Structured Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("nifty_algo_execution.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("nifty_algo.main")

class NiftyTradingBot:
    """
    Main Orchestrator for NIFTY 50 Options-Buying Algorithm (+3 Fixed Target Engine).
    Controls data stream, signals, risk, execution, persistence, and VPS administration.
    """

    def __init__(self, config_path: Optional[str] = None, live_mode_override: bool = False):
        self.config: AppConfig = ConfigLoader.load(config_path)
        
        # Override live mode strictly if explicit CLI switch passed AND pre-live safety checks pass
        if live_mode_override:
            logger.info("Explicit --live CLI flag detected. Evaluating pre-live safety prerequisites...")
            self.config.simulation_mode = False
            self.config.live_execution_enabled = True

        self.db = DatabaseManager(self.config.sqlite_path)
        self.risk_manager = RiskManager(self.config)
        self.kite_client = SafeKiteClient(self.config)
        self.order_manager = OrderExecutionManager(self.config, self.kite_client, self.db)
        self.exit_manager = ExitSafetyManager(self.config, self.kite_client, self.db)
        self.reconciler = BrokerReconciler(self.config, self.kite_client, self.db)
        self.position_tracker = PositionTracker(self.config, self.db)
        self.overnight_manager = OvernightPositionManager(self.config)
        self.post_target_logger = PostTargetMovementLogger(self.db)
        self.notifier = TelegramNotifier(self.config)
        self.structure_engine = MarketStructureEngine(min_room_pts=self.config.confidence.min_room_to_opposing_level_pts)
        self.confidence_scorer = ConfidenceScorer(self.config)
        self.option_selector = OptionSelector(self.config)

        # Multi-Setup Opportunity Engine & Execution Safety
        self.opportunity_engine = OpportunityEngine(
            mode=getattr(self.config, "trading_mode", "OPPORTUNITY"),
            opportunity_min_score=getattr(self.config.confidence, "min_entry_score", 80.0),
            high_conviction_min_score=getattr(self.config.confidence, "high_conviction_min_score", 85.0),
        )
        self.exec_engine = TradeExecutionEngine(
            lot_size=65,
            target_pts=self.config.target_premium_points,
            break_even_activation_pts=getattr(self.config, "break_even_activation_pts", None),
            max_premium_loss_cap=getattr(self.config.risk, "stop_loss_option_points", 5.0) or 5.0,
            strike_selection=getattr(self.config, "strike_selection", "ATM"),
        )
        arb_cfg = getattr(self.config, "arbitration", None)
        self.multi_coordinator = MultiOpportunityCoordinator(
            min_confidence=arb_cfg.min_confidence_score if arb_cfg else 80.0,
            primary_engines=arb_cfg.primary_engines if arb_cfg else ["ENGINE_1_MOMENTUM", "ENGINE_4_BREAKOUT"],
            secondary_boosters=arb_cfg.secondary_boosters if arb_cfg else ["ENGINE_3_TRAP", "ENGINE_6_OI_INTEL"],
            booster_boost_pts=arb_cfg.booster_boost_pts if arb_cfg else 8.0,
            allow_standalone_boosters=arb_cfg.allow_standalone_boosters if arb_cfg else False
        )

        # Big 3 Heavyweight Alignment Booster & Chop Filter (HDFCBANK, RELIANCE, ICICIBANK)
        hw_cfg = getattr(self.config, "heavyweights", None)
        if hw_cfg and getattr(hw_cfg, "enabled", True):
            self.heavyweight_engine = HeavyweightAlignmentEngine(
                hdfc_token=hw_cfg.hdfc_token,
                reliance_token=hw_cfg.reliance_token,
                icici_token=hw_cfg.icici_token,
                alignment_boost_pts=hw_cfg.full_alignment_boost_pts,
                partial_boost_pts=hw_cfg.partial_alignment_boost_pts,
                divergence_trap_penalty_pts=hw_cfg.divergence_trap_penalty_pts,
                opposing_penalty_pts=hw_cfg.opposing_penalty_pts,
                fast_move_target_pts=getattr(hw_cfg, "fast_move_target_pts", 15.0),
            )
        else:
            self.heavyweight_engine = None

        # 9 Modular Setups
        self.setups = [
            BreakoutRetestSetup(),
            LiquiditySweepReversalSetup(),
            VWAPReclaimSetup(),
            VWAPRejectionSetup(),
            TrendContinuationSetup(),
            OpeningRangeBreakoutSetup(),
            SupportReversalSetup(),
            ResistanceRejectionSetup(),
            FVGConfirmationSetup(),
        ]

        # Candle Aggregators
        self.nifty_aggregator = MultiTimeframeCandleAggregator(self.config.underlying_token)
        self.is_running = False
        self.latest_nifty_spot = 0.0
        self.session_data: Dict[str, Any] = {}

        # Open Interest Intelligence & Cross Indicator
        self.latest_oi_intel: Optional[Dict[str, Any]] = None
        self._last_oi_fetch_time: float = 0.0
        self._oi_baseline_cache: Dict[str, float] = {}

    def start(self):
        logger.info("=" * 70)
        mode_str = "LIVE REAL MONEY" if not self.config.simulation_mode else "PAPER / DRY-RUN (Default Safe)"
        logger.info("STARTING NIFTY 50 OPTIONS-BUYING ENGINE | MODE: %s", mode_str)
        logger.info("TARGET POLICY: Fixed +3.0 Option Premium Points (Active thru 31 Jan 2027)")
        logger.info("=" * 70)

        # 1. Pre-Live Safety Verification
        if not self.config.simulation_mode:
            passed, failures = self.risk_manager.perform_pre_live_safety_checks()
            if not passed:
                logger.critical("PRE-LIVE SAFETY CHECKS FAILED:")
                for f in failures:
                    logger.critical(" - %s", f)
                raise PreLiveCheckFailedError("Live trading blocked by safety system.")

        # 2. Clock Synchronization Check
        self.kite_client.check_clock_synchronization()

        # 3. Database Session Initialization
        self.session_data = self.db.get_or_create_daily_session(self.config.capital.initial_capital_inr)
        self.risk_manager.set_consecutive_losses(self.session_data.get("consecutive_losses", 0))

        # 4. Startup Broker Reconciliation
        reconciled, msg, active_pos = self.reconciler.reconcile_on_startup()
        if not reconciled:
            self.emergency_freeze(f"Startup reconciliation failed: {msg}")
            return
        if active_pos:
            self.position_tracker.set_active_position(active_pos)

        # 5. Populate Option Instruments Cache
        if not self.config.simulation_mode:
            try:
                instruments = self.kite_client.get_instruments("NFO")
                self.option_selector.update_instruments(instruments)
            except Exception as e:
                logger.error("Failed to fetch NFO instruments from Kite: %s", e)

        # 5b. Preload Historical 1m & 3m Candles for Chart Visualizer & Structure Engine
        if not self.config.simulation_mode:
            try:
                today = datetime.now()
                from_date = (today - timedelta(days=4)).strftime("%Y-%m-%d 09:15:00")
                to_date = today.strftime("%Y-%m-%d %H:%M:%S")
                c1 = self.kite_client.get_historical_data(self.config.underlying_token, from_date, to_date, "minute")
                c3 = self.kite_client.get_historical_data(self.config.underlying_token, from_date, to_date, "3minute")
                if c1:
                    self.nifty_aggregator.load_historical_candles("1m", c1)
                    self.latest_nifty_spot = float(c1[-1]["close"])
                    logger.info("Preloaded %d 1m historical candles for NIFTY spot (Latest: %.2f)", len(c1), self.latest_nifty_spot)
                if c3:
                    self.nifty_aggregator.load_historical_candles("3m", c3)
                    logger.info("Preloaded %d 3m historical candles for NIFTY structure", len(c3))
            except Exception as e:
                logger.warning("Could not preload historical candles from Kite: %s", e)

        # 6. Start WebSocket Feed
        self.ws_feed = RobustWebSocketFeed(self.config, on_tick_callback=self._on_ticks_received)
        tokens_to_subscribe = [self.config.underlying_token]
        if self.heavyweight_engine:
            tokens_to_subscribe.extend(self.heavyweight_engine.get_tracked_tokens())
            logger.info("Subscribed WebSocket to NIFTY and Big 3 Heavyweights: %s", tokens_to_subscribe)
        self.ws_feed.set_tokens(tokens_to_subscribe)
        self.ws_feed.start()

        # 7. Start FastAPI Administration Server in Daemon Thread
        admin_app = create_admin_app(self, self.db)
        admin_thread = threading.Thread(
            target=uvicorn.run,
            args=(admin_app,),
            kwargs={"host": "0.0.0.0", "port": self.config.server_port, "log_level": "warning"},
            daemon=True
        )
        admin_thread.start()
        logger.info("VPS Admin Dashboard active at: http://%s:%d/", self.config.static_ip, self.config.server_port)

        # Notify Telegram
        self.notifier.notify_bot_started(
            mode=mode_str,
            symbol=self.config.active_symbol,
            capital=self.session_data.get("current_capital", self.config.capital.initial_capital_inr)
        )

        self.is_running = True
        self._main_execution_loop()

    def _on_ticks_received(self, ticks: List[Dict[str, Any]]):
        for tick in ticks:
            token = tick.get("instrument_token")
            last_price = tick.get("last_price", 0.0)

            if token == self.config.underlying_token:
                self.latest_nifty_spot = last_price
                self.nifty_aggregator.on_tick(tick)
            elif self.heavyweight_engine and token in self.heavyweight_engine.token_to_symbol:
                self.heavyweight_engine.on_tick(tick)

            # Route tick to post-target logger for active monitors
            if self.post_target_logger.active_monitors:
                # Check matching option quote
                for trade_id, obs in self.post_target_logger.active_monitors.items():
                    if obs.get("tradingsymbol"):
                        self.post_target_logger.on_tick(obs["tradingsymbol"], last_price, self.latest_nifty_spot)

    def _main_execution_loop(self):
        """Continuous evaluation loop for market scanning and order management."""
        while self.is_running:
            try:
                time.sleep(1.0)
                now_ist = datetime.now(IST)
                time_str = now_ist.strftime("%H:%M")

                # Trading Hours Gate (9:20 AM to 15:00 PM IST)
                if time_str < self.config.trading_hours.entries_permitted_from:
                    continue  # 9:15-9:20 AM evaluation only

                if time_str >= self.config.trading_hours.stop_new_entries_time:
                    # New entries stopped; existing positions continue to be managed
                    pass

                # Lunch Chop Pause (11:30 AM to 01:00 PM per Section 13E)
                if self.config.trading_hours.pause_lunch_chop:
                    if self.config.trading_hours.lunch_chop_start <= time_str < self.config.trading_hours.lunch_chop_end:
                        if not self.position_tracker.has_open_position:
                            continue  # Pause opening new trades during lunch chop

                # Check if system is frozen
                if self.risk_manager.is_frozen:
                    continue

                # 1. Manage Active Position (if open)
                if self.position_tracker.has_open_position:
                    self._manage_open_position()
                    continue

                # 2. Check if eligible to scan for new entries
                can_enter, reason = self.position_tracker.check_can_enter()
                if not can_enter:
                    continue

                if time_str >= self.config.trading_hours.stop_new_entries_time:
                    continue  # Do not open after 15:00

                # 3. Evaluate Market Data & Signals
                self._evaluate_market_opportunity()

            except Exception as e:
                logger.error("Error in main execution loop: %s", e, exc_info=True)
                time.sleep(2.0)

    def _evaluate_market_opportunity(self):
        df_1m = self.nifty_aggregator.get_dataframe("1m")
        df_3m = self.nifty_aggregator.get_dataframe("3m")

        if len(df_1m) < 20 or len(df_3m) < 10:
            return

        indicators = TechnicalIndicators.analyze_indicators(df_1m)
        structure = self.structure_engine.compute_structure(df_1m, df_3m)

        c1_list = df_1m.to_dict("records")
        c3_list = df_3m.to_dict("records")

        # Evaluate Big 3 Heavyweights (HDFC, Reliance, ICICI)
        hw_eval = self.heavyweight_engine.evaluate() if self.heavyweight_engine else None

        # Multi-Engine Opportunity Evaluation & Central Arbitration (Section 3 & 7)
        decision, raw_sigs = self.multi_coordinator.evaluate_all_engines(
            candles_1m=c1_list,
            candles_3m=c3_list,
            structure=structure,
            indicators=indicators,
            oi_data={"oi_bias": "NEUTRAL", "pcr": 1.0},
            has_open_position=self.position_tracker.has_open_position,
            heavyweight_eval=hw_eval
        )

        if not decision.should_execute:
            return

        direction = "BULLISH" if decision.direction == "CE" else "BEARISH"
        setup_name = decision.primary_strategy
        conf_score = decision.combined_confidence

        logger.info(
            "[VALID %s OPPORTUNITY IDENTIFIED] Direction: %s (%s) | Setup: %s | Score: %.1f/100 | Merged: %s | Contribs: %s",
            self.config.trading_mode, decision.direction, direction, setup_name, conf_score,
            decision.duplicate_merged, decision.contributing_strategies
        )

        # Select Option Contract (ATM or ITM_1 per config)
        contract = self._select_contract_for_signal(direction)
        if not contract:
            logger.warning("[CONTRACT SELECTION FAILED] Could not select contract for %s", direction)
            return

        # Capital & Lot Affordability Verification (Checked against live Kite balance)
        available_cap = self.get_live_capital()
        affordable, lot_size, aff_msg = self.risk_manager.verify_affordability(
            available_capital=available_cap,
            option_premium=contract["ltp"],
            lot_size=contract["lot_size"]
        )

        if not affordable:
            logger.warning("[TRADE SKIPPED] Affordability check failed: %s", aff_msg)
            return

        # Rich Telegram Signal Notification (matching sensexsuu388 formatting)
        struct_details = (
            f"  • Mode: {self.config.trading_mode}\n"
            f"  • Direction: {direction}\n"
            f"  • Setup: {setup_name}\n"
            f"  • Confidence: {conf_score:.1f}/100\n"
            f"  • 3m Structure Room: {structure.get('room_to_resistance', 0.0) if direction=='BULLISH' else structure.get('room_to_support', 0.0):.1f} pts\n"
            f"  • VWAP: {'Above' if indicators.get('price_above_vwap') else 'Below'} ({indicators.get('vwap', 0.0):.1f})\n"
            f"  • EMA 8/21: {'Bullish' if indicators.get('ema_bullish') else 'Bearish'}\n"
            f"  • Big 3 Heavyweights: {hw_eval.summary if hw_eval else 'N/A'}\n"
            f"  • Target: +{decision.target_pts:.1f} pts {'[SUPER_TREND_RUNNER]' if decision.target_pts > 3.0 else '[STANDARD_SCALP]'} | Break-Even Lock: {'+' + str(self.config.break_even_activation_pts) + ' pts' if getattr(self.config, 'break_even_activation_pts', None) else 'NONE (Pure Target/SL)'}"
        )
        self.notifier.notify_signal_triggered(
            setup_name=setup_name,
            direction=direction,
            conf=conf_score,
            order_specs=contract,
            current_spot=self.latest_nifty_spot,
            structure_details=struct_details,
            current_capital=available_cap
        )

        # Execute BUY Order
        self._execute_entry(contract, setup_name, conf_score, target_pts=decision.target_pts)

    def _select_contract_for_signal(self, direction: str) -> Optional[Dict[str, Any]]:
        strike_selection = getattr(self.config, "strike_selection", "ATM")
        if self.config.simulation_mode:
            # Paper mode: generate contract specifications
            strike_step = 50.0
            nifty_spot = self.latest_nifty_spot or 24000.0
            atm_strike = round(nifty_spot / strike_step) * strike_step
            opt_type = "CE" if direction == "BULLISH" else "PE"
            if strike_selection == "ITM_1":
                selected_strike = atm_strike - strike_step if opt_type == "CE" else atm_strike + strike_step
                sim_ltp = 135.0
            else:
                selected_strike = atm_strike
                sim_ltp = 115.0

            symbol = f"NIFTY_{int(selected_strike)}_{opt_type}"
            return {
                "instrument_token": 999999,
                "tradingsymbol": symbol,
                "strike": selected_strike,
                "expiry": "2026-11-26",
                "lot_size": 65,  # Dynamic lot size from broker master
                "ltp": sim_ltp,
                "spread": 0.5
            }

        # LIVE MODE: Query candidate contracts dynamically and fetch their live quotes
        candidates = self.option_selector.get_candidates(direction, self.latest_nifty_spot, limit=6)
        if not candidates:
            logger.warning("[OPTION SELECTOR] No candidate contracts found in cache for %s near %.1f", direction, self.latest_nifty_spot)
            return None

        symbols = [f"NFO:{c['tradingsymbol']}" for c in candidates]
        quotes = self.kite_client.get_quote(symbols)
        return self.option_selector.select_best_contract(direction, self.latest_nifty_spot, quotes)

    def _execute_entry(self, contract: Dict[str, Any], setup_name: str, confidence_score: float, target_pts: float = 3.0):
        import uuid
        trade_id = f"TRD_{datetime.now(IST).strftime('%Y%m%d%H%M%S')}"
        position_id = f"POS_{uuid.uuid4().hex[:10]}"
        tradingsymbol = contract["tradingsymbol"]
        lot_size = contract["lot_size"]
        current_premium = contract["ltp"]

        # Register position in state machine
        pos_record = {
            "position_id": position_id,
            "trade_id": trade_id,
            "instrument_token": contract["instrument_token"],
            "tradingsymbol": tradingsymbol,
            "option_type": "CE" if "CE" in tradingsymbol else "PE",
            "strike": contract["strike"],
            "expiry": contract["expiry"],
            "product": self.config.product_type,
            "status": "PENDING_BUY",
            "desired_quantity": lot_size,
            "filled_quantity": 0,
            "remaining_quantity": 0,
            "buy_avg_price": 0.0,
            "target_price": 0.0,
            "target_pts": target_pts,
            "opened_at_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        }
        self.db.create_position(pos_record)
        self.position_tracker.set_active_position(pos_record)

        # Place BUY Limit Order
        success, broker_order_id, filled_qty, avg_price, msg = self.order_manager.execute_buy(
            contract=contract,
            current_premium=current_premium,
            trade_id=trade_id,
            position_id=position_id
        )

        if not success or filled_qty == 0:
            logger.warning("[BUY FAILED] %s. Clearing pending position.", msg)
            self.db.close_position(position_id, 0.0, 0.0, 0.0, 0.0, f"BUY failed: {msg}")
            self.position_tracker.clear_position()
            return

        # BUY confirmed!
        target_price = round(avg_price + target_pts, 2)
        pos_record["status"] = "OPEN"
        pos_record["filled_quantity"] = filled_qty
        pos_record["remaining_quantity"] = filled_qty
        pos_record["buy_avg_price"] = avg_price
        pos_record["target_price"] = target_price
        pos_record["target_pts"] = target_pts

        self.db.update_position_fill(position_id, filled_qty, avg_price, target_price)
        self.position_tracker.set_active_position(pos_record)

        self.notifier.notify_order_filled(tradingsymbol, filled_qty, avg_price, is_partial=(filled_qty < lot_size))

        # Immediately place Target Exit Order (standard +3.0 or expanded fast-move +15.0)
        ok_sell, sell_order_id, tgt_price, sell_msg = self.exit_manager.place_fixed_target_exit(
            tradingsymbol=tradingsymbol,
            buy_avg_price=avg_price,
            expected_quantity=filled_qty,
            target_points_override=target_pts
        )

        if ok_sell:
            self.notifier.notify_target_placed(tradingsymbol, tgt_price, filled_qty, sell_order_id)
        else:
            logger.critical("[EXIT ORDER WARNING] Failed to place initial target order: %s", sell_msg)

    def _manage_open_position(self):
        """Monitors open position and verifies exit execution."""
        pos = self.position_tracker.current_position
        if not pos or pos.get("status") != "OPEN":
            return

        tradingsymbol = pos["tradingsymbol"]
        buy_avg = pos["buy_avg_price"]
        target_price = pos["target_price"]
        filled_qty = pos["filled_quantity"]

        # In Paper Mode: Check if simulated target hit
        if self.config.simulation_mode:
            # Check price progression
            # For demonstration in paper mode, trigger simulated target exit
            time.sleep(2.0)
            sell_avg = target_price
            gross_pnl = round((sell_avg - buy_avg) * filled_qty, 2)
            charges = ZerodhaOptionChargesCalculator.calculate(buy_avg, sell_avg, filled_qty)
            net_pnl = round(gross_pnl - charges.total_charges, 2)

            self._finalize_closed_position(pos, sell_avg, gross_pnl, net_pnl, charges.total_charges, "Target +3.0 Points Hit")
            return

        # LIVE MODE: Check broker order and position status
        try:
            verified_qty, _ = self.exit_manager.get_verified_remaining_long_quantity(tradingsymbol)
            if verified_qty == 0:
                # Position has closed on broker!
                # Fetch sell average price from trades
                trades = self.kite_client.get_trades()
                relevant_sell = [t for t in trades if t.get("tradingsymbol") == tradingsymbol and t.get("transaction_type") == "SELL"]
                sell_avg = relevant_sell[-1].get("average_price", target_price) if relevant_sell else target_price
                gross_pnl = round((sell_avg - buy_avg) * filled_qty, 2)
                charges = ZerodhaOptionChargesCalculator.calculate(buy_avg, sell_avg, filled_qty)
                net_pnl = round(gross_pnl - charges.total_charges, 2)

                self._finalize_closed_position(pos, sell_avg, gross_pnl, net_pnl, charges.total_charges, "Target +3.0 Points Hit on Broker")

        except Exception as e:
            logger.error("Error monitoring open position: %s", e)

    def _finalize_closed_position(self, pos: Dict[str, Any], sell_avg: float, gross_pnl: float, net_pnl: float, charges: float, exit_reason: str):
        tradingsymbol = pos["tradingsymbol"]
        trade_id = pos["trade_id"]
        position_id = pos["position_id"]
        buy_avg = pos["buy_avg_price"]
        qty = pos["filled_quantity"]

        self.db.close_position(position_id, sell_avg, gross_pnl, net_pnl, charges, exit_reason)
        today_ist = datetime.now(IST).strftime("%Y-%m-%d")
        is_loss = net_pnl < 0
        self.db.update_session_pnl(today_ist, gross_pnl, net_pnl, is_loss)
        self.risk_manager.record_trade_result(net_pnl)

        logger.info(
            "[POSITION CLOSED] %s | Buy: ₹%.2f | Sell: ₹%.2f | Gross P&L: ₹%+.2f | Net P&L: ₹%+.2f | Exit: %s",
            tradingsymbol, buy_avg, sell_avg, gross_pnl, net_pnl, exit_reason
        )

        self.notifier.notify_position_closed(
            symbol=tradingsymbol,
            buy_avg=buy_avg,
            sell_avg=sell_avg,
            qty=qty,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            charges=charges,
            daily_realized_pnl=self.session_data.get("net_pnl", net_pnl),
            new_capital=self.session_data.get("current_capital", self.config.capital.initial_capital_inr) + net_pnl,
            exit_reason=exit_reason
        )

        # Mandatory Post-Target Movement Observation Tracking
        self.post_target_logger.start_monitoring(
            trade_id=trade_id,
            position_id=position_id,
            tradingsymbol=tradingsymbol,
            buy_avg=buy_avg,
            actual_exit_price=sell_avg,
            exit_quantity=qty,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            nifty_underlying_exit=self.latest_nifty_spot
        )

        # Clear active position and begin mandatory 3-minute cooldown
        self.position_tracker.clear_position()

    def emergency_freeze(self, reason: str):
        self.risk_manager.set_consecutive_losses(3)
        self.notifier.notify_emergency_freeze(reason)
        logger.critical("[KILL SWITCH] Trading frozen. Reason: %s", reason)

    def clear_freeze(self):
        self.risk_manager.set_consecutive_losses(0)
        logger.info("[RESUME] Trading freeze cleared by operator.")

    def update_active_trade_target(self, new_target_pts: float) -> Tuple[bool, str]:
        """Manually updates the target points and order on Zerodha for the active position."""
        pos = self.position_tracker.current_position
        if not pos or pos.get("status") != "OPEN":
            return False, "No active open position to update."

        if new_target_pts <= 0:
            return False, "Target points must be strictly positive."

        tradingsymbol = pos["tradingsymbol"]
        buy_avg = float(pos.get("buy_avg_price", 0.0))
        new_target_price = round(buy_avg + new_target_pts, 2)
        position_id = pos["position_id"]

        ok, order_id, msg = self.exit_manager.modify_target_exit(tradingsymbol, new_target_price)
        if not ok:
            return False, msg

        # Update in-memory state and database
        pos["target_pts"] = new_target_pts
        pos["target_price"] = new_target_price
        self.position_tracker.set_active_position(pos)
        self.db.update_position_target(position_id, new_target_price)

        logger.info("[TARGET UPDATED] %s target updated to +%.1f pts (₹%.2f)", tradingsymbol, new_target_pts, new_target_price)
        self.notifier.notify_info(f"🎯 Target Adjusted manually for <b>{tradingsymbol}</b>: +{new_target_pts:.1f} pts (₹{new_target_price:.2f})")
        return True, f"Target updated to +{new_target_pts:.1f} pts (Limit: ₹{new_target_price:.2f})"

    def get_live_capital(self) -> float:
        """Fetches real-time equity available cash/margin from Kite API in LIVE mode."""
        if not self.config.simulation_mode:
            try:
                margins = self.kite_client.get_margins()
                eq = margins.get("equity", {})
                avail = eq.get("available", {})
                cash = float(avail.get("live_balance", 0.0) or avail.get("cash", 0.0) or eq.get("net", 0.0))
                if cash > 0:
                    return round(cash, 2)
            except Exception as e:
                logger.warning("Failed to fetch live Kite margins: %s", e)
        return float(self.session_data.get("current_capital", self.config.capital.initial_capital_inr))

    def get_runtime_status(self) -> Dict[str, Any]:
        return {
            "mode": "PAPER" if self.config.simulation_mode else "LIVE",
            "is_trading_frozen": self.risk_manager.is_frozen,
            "consecutive_losses": self.risk_manager.consecutive_losses,
            "capital": self.get_live_capital(),
            "cooldown_seconds_remaining": self.position_tracker.get_remaining_cooldown_seconds(),
            "latest_nifty_spot": self.latest_nifty_spot,
            "open_position": self.position_tracker.current_position,
        }

    def _refresh_oi_intel(self, force: bool = False) -> Dict[str, Any]:
        """
        Fetches quotes for active weekly ATM ± 8 strikes from Kite (or generates fallback),
        computes Open Interest Walls (Call Wall / Put Wall) and predictive Cross / Bounce indicators.
        Throttled to run at most once every 10 seconds to respect API limits.
        """
        now = time.time()
        if not force and self.latest_oi_intel and (now - self._last_oi_fetch_time) < 10.0:
            return self.latest_oi_intel

        spot = self.latest_nifty_spot or 25000.0
        hw_eval = self.heavyweight_engine.evaluate() if self.heavyweight_engine else None

        chain_data = []
        try:
            contracts = self.option_selector.get_active_expiry_contracts(spot, num_strikes=8)
            if contracts and self.kite_client:
                symbols = [f"NFO:{c['tradingsymbol']}" for c in contracts]
                quotes = self.kite_client.get_quote(symbols)
                for c in contracts:
                    sym = f"NFO:{c['tradingsymbol']}"
                    q = quotes.get(sym, {})
                    cur_oi = float(q.get("oi", 0))
                    ltp = float(q.get("last_price", 0.0))
                    ohlc = q.get("ohlc", {})
                    prev_close = float(ohlc.get("close", ltp))
                    price_chg = ltp - prev_close

                    base_oi = self._oi_baseline_cache.get(sym)
                    if base_oi is None:
                        self._oi_baseline_cache[sym] = cur_oi
                        oi_change = 0.0
                    else:
                        oi_change = cur_oi - base_oi

                    chain_data.append({
                        "tradingsymbol": c["tradingsymbol"],
                        "strike": float(c["strike"]),
                        "instrument_type": c["instrument_type"],
                        "oi": cur_oi,
                        "oi_change": oi_change,
                        "ltp": ltp,
                        "price_change": price_chg
                    })
        except Exception as e:
            logger.debug("Live OI quote fetch info: %s", e)

        oi_analysis = OpenInterestAnalyzer.calculate_oi_walls(chain_data, spot, hw_eval)
        self.latest_oi_intel = oi_analysis
        self._last_oi_fetch_time = now
        return oi_analysis

    def get_chart_data(self) -> Dict[str, Any]:
        """Provides structured real-time data for the TradingView-style automatic visualizer."""
        try:
            df_1m = self.nifty_aggregator.get_dataframe("1m")
            df_3m = self.nifty_aggregator.get_dataframe("3m")
        except Exception as e:
            logger.warning("Error fetching candle dataframes: %s", e)
            import pandas as pd
            df_1m = pd.DataFrame()
            df_3m = pd.DataFrame()

        candles_dict = {}
        if len(df_1m) > 0:
            for r in df_1m.tail(200).to_dict("records"):
                dt = r["date"]
                t_sec = int(dt.timestamp()) if hasattr(dt, "timestamp") else int(time.time())
                candles_dict[t_sec] = {
                    "time": t_sec,
                    "open": round(float(r["open"]), 2),
                    "high": round(float(r["high"]), 2),
                    "low": round(float(r["low"]), 2),
                    "close": round(float(r["close"]), 2),
                    "volume": float(r.get("volume", 0) or 0)
                }
        candles = [candles_dict[t] for t in sorted(candles_dict.keys())][-150:]

        structure = {}
        if len(df_1m) >= 15 and len(df_3m) >= 5:
            structure = self.structure_engine.compute_structure(df_1m, df_3m)

        supports = []
        resistances = []
        if structure:
            for s in [structure.get("last_swing_low"), structure.get("cdl"), structure.get("pdl"), structure.get("orb_low")]:
                if s is not None and s > 0 and s not in supports:
                    supports.append(round(float(s), 2))
            for r in [structure.get("last_swing_high"), structure.get("cdh"), structure.get("pdh"), structure.get("orb_high")]:
                if r is not None and r > 0 and r not in resistances:
                    resistances.append(round(float(r), 2))

        hw_eval = self.heavyweight_engine.evaluate() if self.heavyweight_engine else None

        active_pos = self.position_tracker.current_position
        pos_data = None
        if active_pos:
            entry_prem = float(active_pos.get("buy_avg_price", 0.0))
            tgt_pts = float(active_pos.get("target_pts", 3.0))
            tgt_prem = float(active_pos.get("target_price", entry_prem + tgt_pts))
            opt_type = active_pos.get("option_type", "CE")
            delta = 0.50
            entry_spot = self.latest_nifty_spot or (candles[-1]["close"] if candles else 25000.0)
            sl_pts = getattr(self.config.risk, "stop_loss_option_points", 5.0) or 5.0
            sl_prem = round(entry_prem - sl_pts, 2)

            spot_target = round(entry_spot + (tgt_pts / delta) if opt_type == "CE" else entry_spot - (tgt_pts / delta), 2)
            spot_sl = round(entry_spot - (sl_pts / delta) if opt_type == "CE" else entry_spot + (sl_pts / delta), 2)

            # Auto-calculate Full Structural Maximum Move (Room to nearest Resistance/Support)
            if opt_type == "CE":
                res_levels = [r for r in sorted(resistances) if r > entry_spot]
                max_spot_target = res_levels[0] if res_levels else round(entry_spot + 40.0, 2)
                max_spot_room = round(max(0.0, max_spot_target - entry_spot), 2)
            else:
                sup_levels = [s for s in sorted(supports, reverse=True) if s < entry_spot]
                max_spot_target = sup_levels[0] if sup_levels else round(entry_spot - 40.0, 2)
                max_spot_room = round(max(0.0, entry_spot - max_spot_target), 2)

            max_opt_pts = round(max_spot_room * delta, 1)
            max_opt_prem = round(entry_prem + max_opt_pts, 2)

            curr_spot = self.latest_nifty_spot or entry_spot
            spot_move = curr_spot - entry_spot
            est_opt_pts_move = (spot_move * delta) if opt_type == "CE" else (-spot_move * delta)
            curr_opt_ltp = round(max(0.5, entry_prem + est_opt_pts_move), 2)
            qty = int(active_pos.get("remaining_quantity", 65))
            unrealized_gross = round(est_opt_pts_move * qty, 2)

            pos_data = {
                "trade_id": active_pos.get("trade_id"),
                "tradingsymbol": active_pos.get("tradingsymbol"),
                "direction": opt_type,
                "entry_premium": entry_prem,
                "target_premium": tgt_prem,
                "target_pts": tgt_pts,
                "sl_premium": sl_prem,
                "sl_pts": sl_pts,
                "entry_spot": entry_spot,
                "spot_target": spot_target,
                "spot_sl": spot_sl,
                "max_spot_target": max_spot_target,
                "max_spot_room": max_spot_room,
                "max_opt_pts": max_opt_pts,
                "max_opt_prem": max_opt_prem,
                "current_opt_ltp": curr_opt_ltp,
                "unrealized_pts": round(est_opt_pts_move, 2),
                "unrealized_pnl": unrealized_gross,
                "quantity": qty,
                "status": active_pos.get("status"),
                "opened_at": active_pos.get("opened_at_ist")
            }

        try:
            recent_trades = self.db.get_recent_positions(limit=10)
        except Exception as e:
            logger.warning("Could not fetch recent positions: %s", e)
            recent_trades = []

        return {
            "capital": self.get_live_capital(),
            "latest_spot": self.latest_nifty_spot,
            "candles": candles,
            "structure": {
                "supports": sorted(supports),
                "resistances": sorted(resistances),
                "pdh": structure.get("pdh"),
                "pdl": structure.get("pdl"),
                "orb_high": structure.get("orb_high"),
                "orb_low": structure.get("orb_low"),
            },
            "heavyweights": {
                "summary": hw_eval.summary if hw_eval else "N/A",
                "is_bullish_aligned": hw_eval.is_bullish_aligned if hw_eval else False,
                "is_bearish_aligned": hw_eval.is_bearish_aligned if hw_eval else False,
                "is_divergence_trap": hw_eval.is_divergence_trap if hw_eval else False,
                "is_fast_mover": hw_eval.is_fast_mover if hw_eval else False,
                "stocks": hw_eval.details if hw_eval else {}
            },
            "active_trade": pos_data,
            "recent_trades": recent_trades,
            "oi_intel": self._refresh_oi_intel()
        }

    def stop(self, reason: str = "Operator signal"):
        logger.info("Stopping NIFTY trading bot: %s", reason)
        self.is_running = False
        if hasattr(self, "ws_feed"):
            self.ws_feed.stop()
        self.notifier.notify_bot_stopped(reason)

def main():
    parser = argparse.ArgumentParser(description="NIFTY 50 Options-Buying Bot (+3 Point Scalper)")
    parser.add_argument("--config", type=str, default=None, help="Path to custom config JSON")
    parser.add_argument("--live", action="store_true", help="Explicit switch to enable LIVE trading (default: PAPER)")
    parser.add_argument("--backtest", type=str, default=None, help="Run backtest on specified 1m CSV file")
    args = parser.parse_args()

    if args.backtest:
        from nifty_algo.backtesting.backtester import NiftyHistoricalBacktester
        cfg = ConfigLoader.load(args.config)
        backtester = NiftyHistoricalBacktester(cfg)
        import pandas as pd
        logger.info("Loading backtest data from: %s", args.backtest)
        df = pd.read_csv(args.backtest)
        results = backtester.run(df)
        import json
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS SUMMARY:")
        print("=" * 60)
        print(json.dumps(results, indent=2))
        return

    bot = NiftyTradingBot(config_path=args.config, live_mode_override=args.live)

    # Signal handling for graceful shutdown
    def handle_shutdown(signum, frame):
        logger.info("Received termination signal (%d). Shutting down gracefully...", signum)
        bot.stop(f"OS Signal {signum}")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    bot.start()

if __name__ == "__main__":
    main()
