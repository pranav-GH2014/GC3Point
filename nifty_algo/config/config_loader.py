import os
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

logger = logging.getLogger("nifty_algo.config")

# Common search paths for config files (config.json is prioritized)
CONFIG_CANDIDATES = [
    os.path.join(os.getcwd(), "config.json"),
    os.path.join(os.getcwd(), "SUU388config.json"),
    "/root/nifty_3point_algo/config.json",
    "/root/nifty_3point_algo/SUU388config.json",
    r"C:\Baiju\TradingViewSensex\TradingView\SUU388config.json",
    r"C:\Baiju\TradingViewSensex\TradingView\config.json",
    "/root/senexsuu388/SUU388config.json",
]

@dataclass
class CapitalSettings:
    initial_capital_inr: float = 5000.0
    max_deployment_pct: float = 0.98
    reserved_cash_pct: float = 0.02
    reinvest_profits: bool = True
    verify_affordability_before_buy: bool = True

@dataclass
class TradingHours:
    timezone: str = "Asia/Kolkata"
    market_open: str = "09:15"
    evaluation_start: str = "09:15"
    entries_permitted_from: str = "09:20"
    pause_lunch_chop: bool = True
    lunch_chop_start: str = "11:30"
    lunch_chop_end: str = "13:00"
    stop_new_entries_time: str = "15:00"
    market_close: str = "15:30"

@dataclass
class RiskSettings:
    max_loss_per_trade_inr: Optional[float] = None  # UNRESOLVED: Must be confirmed before LIVE
    stop_loss_option_points: float = 5.0
    daily_max_loss_limit_inr: float = 1500.0
    charges_per_round_trip_estimate_inr: float = 60.0
    stop_structure_buffer_points: float = 2.0
    adverse_overnight_gap_threshold_pts: float = 40.0
    overnight_protection_discount_pts: float = 2.0
    allow_overnight_nrml: bool = True
    max_open_strategy_positions: int = 1

@dataclass
class ConfidenceEngineSettings:
    min_entry_score: float = 80.0
    high_conviction_min_score: float = 85.0
    wait_zone_min_score: float = 65.0
    min_room_to_opposing_level_pts: float = 8.0
    weights: Dict[str, float] = field(default_factory=lambda: {
        "market_structure": 20.0,
        "breakout_and_false_breakout": 15.0,
        "liquidity_and_fvg": 10.0,
        "candle_confirmation": 10.0,
        "ema_and_vwap": 10.0,
        "adx_and_momentum": 10.0,
        "volume_profile": 10.0,
        "open_interest_and_breadth": 10.0,
        "vix_time_and_news": 5.0,
    })

@dataclass
class MomentumOverrideSettings:
    enabled: bool = True
    rapid_move_points: float = 50.0
    rapid_move_window_minutes: int = 5
    allow_low_adx_override: bool = True

@dataclass
class OptionSelectorSettings:
    preferred_delta_min: float = 0.35
    preferred_delta_max: float = 0.65
    max_bid_ask_spread_pts: float = 1.0
    min_volume: int = 5000
    min_open_interest: int = 50000
    min_premium: float = 15.0
    max_premium: float = 250.0

@dataclass
class OpportunityArbitrationSettings:
    min_confidence_score: float = 80.0
    primary_engines: List[str] = field(default_factory=lambda: ["ENGINE_1_MOMENTUM", "ENGINE_4_BREAKOUT"])
    secondary_boosters: List[str] = field(default_factory=lambda: ["ENGINE_3_TRAP", "ENGINE_6_OI_INTEL"])
    booster_boost_pts: float = 8.0
    opposing_penalty_pts: float = 6.0
    allow_standalone_boosters: bool = False

@dataclass
class HeavyweightSettings:
    enabled: bool = True
    hdfc_token: int = 341249
    reliance_token: int = 738561
    icici_token: int = 1270529
    full_alignment_boost_pts: float = 10.0
    partial_alignment_boost_pts: float = 5.0
    divergence_trap_penalty_pts: float = 10.0
    opposing_penalty_pts: float = 15.0
    fast_move_target_pts: float = 15.0

@dataclass
class AppConfig:
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    public_token: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    static_ip: str = ""
    server_port: int = 8002
    simulation_mode: bool = True  # DEFAULT TO PAPER/DRY-RUN MODE
    live_execution_enabled: bool = False  # NEVER LIVE BY DEFAULT
    selected_symbol: str = "NIFTY"
    active_symbol: str = "NIFTY"
    exchange: str = "NFO"
    underlying_token: int = 256265
    product_type: str = "NRML"
    fixed_target_expiry_date: str = "2027-01-31"
    target_premium_points: float = 3.0
    break_even_activation_pts: Optional[float] = None
    trading_mode: str = "OPPORTUNITY"
    strike_selection: str = "ATM"
    buy_limit_discount_offset: float = 0.45
    buy_order_timeout_seconds: int = 30
    re_entry_cooldown_seconds: int = 180
    max_consecutive_losses: int = 3
    disable_stop_loss: bool = True  # Stop Loss disabled as requested - exit at profit only
    auto_exit_only_at_profit: bool = True  # Auto exit only at target profit
    capital: CapitalSettings = field(default_factory=CapitalSettings)
    trading_hours: TradingHours = field(default_factory=TradingHours)
    risk: RiskSettings = field(default_factory=RiskSettings)
    confidence: ConfidenceEngineSettings = field(default_factory=ConfidenceEngineSettings)
    momentum_override: MomentumOverrideSettings = field(default_factory=MomentumOverrideSettings)
    option_selector: OptionSelectorSettings = field(default_factory=OptionSelectorSettings)
    arbitration: OpportunityArbitrationSettings = field(default_factory=OpportunityArbitrationSettings)
    sqlite_path: str = "nifty_algo_production.db"
    post_target_snapshots_minutes: List[int] = field(default_factory=lambda: [1, 3, 5, 10, 15, 30])
    heavyweights: Optional[HeavyweightSettings] = None
    raw_config: Dict[str, Any] = field(default_factory=dict)


class ConfigLoader:
    """Loads configuration from environment variables, json files (local & TradingView SUU388 paths)."""

    @staticmethod
    def find_config_file(custom_path: Optional[str] = None) -> Optional[str]:
        if custom_path and os.path.isfile(custom_path):
            return custom_path
        for candidate in CONFIG_CANDIDATES:
            if os.path.isfile(candidate):
                return candidate
        return None

    @classmethod
    def load(cls, custom_path: Optional[str] = None) -> AppConfig:
        config_path = cls.find_config_file(custom_path)
        raw_dict: Dict[str, Any] = {}
        if config_path:
            logger.info("Loading configuration from file: %s", config_path)
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    raw_dict = json.load(f)
            except Exception as e:
                logger.error("Failed to read config file %s: %s", config_path, e)
        else:
            logger.warning("No configuration JSON file found; falling back to environment variables.")

        # Environment variable overrides
        api_key = os.getenv("KITE_API_KEY", raw_dict.get("api_key", ""))
        api_secret = os.getenv("KITE_API_SECRET", raw_dict.get("api_secret", ""))
        access_token = os.getenv("KITE_ACCESS_TOKEN", raw_dict.get("access_token", ""))
        public_token = os.getenv("KITE_PUBLIC_TOKEN", raw_dict.get("public_token", ""))
        telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", raw_dict.get("telegram_bot_token", ""))
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", raw_dict.get("telegram_chat_id", ""))
        static_ip = os.getenv("VPS_STATIC_IP", raw_dict.get("static_ip", ""))

        # Simulation / Live switches - strict safety default
        sim_env = os.getenv("SIMULATION_MODE")
        if sim_env is not None:
            simulation_mode = sim_env.lower() in ("true", "1", "yes")
        else:
            simulation_mode = raw_dict.get("simulation_mode", True)

        live_env = os.getenv("LIVE_EXECUTION_ENABLED")
        if live_env is not None:
            live_execution_enabled = live_env.lower() in ("true", "1", "yes")
        else:
            live_execution_enabled = raw_dict.get("live_execution_enabled", False)

        # Force safety rule: live_execution_enabled can ONLY be True if simulation_mode is False
        if simulation_mode:
            live_execution_enabled = False

        app_cfg = AppConfig(
            api_key=api_key,
            api_secret=api_secret,
            access_token=access_token,
            public_token=public_token,
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=telegram_chat_id,
            static_ip=static_ip,
            server_port=int(raw_dict.get("server_port", 8002)),
            simulation_mode=simulation_mode,
            live_execution_enabled=live_execution_enabled,
            selected_symbol=raw_dict.get("selected_symbol", "NIFTY"),
            active_symbol=raw_dict.get("active_symbol", "NIFTY"),
            exchange=raw_dict.get("exchange", "NFO"),
            underlying_token=int(raw_dict.get("underlying_instrument_token", 256265)),
            product_type=raw_dict.get("product_type", "NRML"),
            fixed_target_expiry_date=raw_dict.get("fixed_target_expiry_date", "2027-01-31"),
            target_premium_points=float(raw_dict.get("target_premium_points", 3.0)),
            break_even_activation_pts=(
                float(raw_dict["break_even_activation_pts"])
                if raw_dict.get("break_even_activation_pts") is not None
                else None
            ),
            trading_mode=raw_dict.get("trading_mode", "OPPORTUNITY"),
            strike_selection=raw_dict.get("strike_selection", "ATM"),
            buy_limit_discount_offset=float(raw_dict.get("buy_limit_discount_offset", 0.45)),
            buy_order_timeout_seconds=int(raw_dict.get("buy_order_timeout_seconds", 30)),
            re_entry_cooldown_seconds=int(raw_dict.get("re_entry_cooldown_seconds", 180)),
            max_consecutive_losses=int(raw_dict.get("max_consecutive_losses", 3)),
            disable_stop_loss=bool(raw_dict.get("disable_stop_loss", True)),
            auto_exit_only_at_profit=bool(raw_dict.get("auto_exit_only_at_profit", True)),
            raw_config=raw_dict,
        )

        # Capital sub-settings
        cap_dict = raw_dict.get("capital_settings", {})
        app_cfg.capital = CapitalSettings(
            initial_capital_inr=float(cap_dict.get("initial_capital_inr", 5000.0)),
            max_deployment_pct=float(cap_dict.get("max_deployment_pct", 0.98)),
            reserved_cash_pct=float(cap_dict.get("reserved_cash_pct", 0.02)),
            reinvest_profits=bool(cap_dict.get("reinvest_profits", True)),
            verify_affordability_before_buy=bool(cap_dict.get("verify_affordability_before_buy", True)),
        )

        # Risk sub-settings
        risk_dict = raw_dict.get("risk_management", {})
        app_cfg.risk = RiskSettings(
            max_loss_per_trade_inr=float(risk_dict.get("max_loss_per_trade_inr")) if risk_dict.get("max_loss_per_trade_inr") is not None else None,
            stop_loss_option_points=float(risk_dict.get("stop_loss_option_points")) if risk_dict.get("stop_loss_option_points") is not None else 0.0,
            daily_max_loss_limit_inr=float(risk_dict.get("daily_max_loss_limit_inr", 1500.0)),
            charges_per_round_trip_estimate_inr=float(risk_dict.get("charges_per_round_trip_estimate_inr", 60.0)),
            stop_structure_buffer_points=float(risk_dict.get("stop_structure_buffer_points", 2.0)),
            adverse_overnight_gap_threshold_pts=float(risk_dict.get("adverse_overnight_gap_threshold_pts", 40.0)),
            overnight_protection_discount_pts=float(risk_dict.get("overnight_protection_discount_pts", 2.0)),
            allow_overnight_nrml=bool(risk_dict.get("allow_overnight_nrml", True)),
            max_open_strategy_positions=int(risk_dict.get("max_open_strategy_positions", 1)),
        )

        # Trading hours sub-settings
        th_dict = raw_dict.get("trading_hours", {})
        app_cfg.trading_hours = TradingHours(
            timezone=th_dict.get("timezone", "Asia/Kolkata"),
            market_open=th_dict.get("market_open", "09:15"),
            evaluation_start=th_dict.get("evaluation_start", "09:15"),
            entries_permitted_from=th_dict.get("entries_permitted_from", "09:20"),
            pause_lunch_chop=bool(th_dict.get("pause_lunch_chop", True)),
            lunch_chop_start=th_dict.get("lunch_chop_start", "11:30"),
            lunch_chop_end=th_dict.get("lunch_chop_end", "13:00"),
            stop_new_entries_time=th_dict.get("stop_new_entries_time", "15:00"),
            market_close=th_dict.get("market_close", "15:30"),
        )

        # Confidence sub-settings
        conf_dict = raw_dict.get("confidence_engine", {})
        app_cfg.confidence = ConfidenceEngineSettings(
            min_entry_score=float(conf_dict.get("min_entry_score", 80.0)),
            high_conviction_min_score=float(conf_dict.get("high_conviction_min_score", 85.0)),
            wait_zone_min_score=float(conf_dict.get("wait_zone_min_score", 65.0)),
            min_room_to_opposing_level_pts=float(conf_dict.get("min_room_to_opposing_level_pts", 8.0)),
            weights=conf_dict.get("weights", app_cfg.confidence.weights),
        )

        # Opportunity Arbitration sub-settings
        arb_dict = raw_dict.get("opportunity_arbitration", {})
        app_cfg.arbitration = OpportunityArbitrationSettings(
            min_confidence_score=float(arb_dict.get("min_confidence_score", 80.0)),
            primary_engines=arb_dict.get("primary_engines", ["ENGINE_1_MOMENTUM", "ENGINE_4_BREAKOUT"]),
            secondary_boosters=arb_dict.get("secondary_boosters", ["ENGINE_3_TRAP", "ENGINE_6_OI_INTEL"]),
            booster_boost_pts=float(arb_dict.get("booster_boost_pts", 8.0)),
            opposing_penalty_pts=float(arb_dict.get("opposing_penalty_pts", 6.0)),
            allow_standalone_boosters=bool(arb_dict.get("allow_standalone_boosters", False)),
        )

        # Heavyweights sub-settings (Big 3 Movers: HDFC, Reliance, ICICI)
        hw_dict = raw_dict.get("heavyweights", {})
        app_cfg.heavyweights = HeavyweightSettings(
            enabled=bool(hw_dict.get("enabled", True)),
            hdfc_token=int(hw_dict.get("hdfc_token", 341249)),
            reliance_token=int(hw_dict.get("reliance_token", 738561)),
            icici_token=int(hw_dict.get("icici_token", 1270529)),
            full_alignment_boost_pts=float(hw_dict.get("full_alignment_boost_pts", 10.0)),
            partial_alignment_boost_pts=float(hw_dict.get("partial_alignment_boost_pts", 5.0)),
            divergence_trap_penalty_pts=float(hw_dict.get("divergence_trap_penalty_pts", 10.0)),
            opposing_penalty_pts=float(hw_dict.get("opposing_penalty_pts", 15.0)),
            fast_move_target_pts=float(hw_dict.get("fast_move_target_pts", 15.0)),
        )

        return app_cfg
