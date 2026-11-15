import pandas as pd
from run_six_engine_comparison import SixEngineBacktestRunner
from nifty_algo.execution.trade_execution_engine import TradeExecutionEngine

class ComparativeBERunner(SixEngineBacktestRunner):
    def run_be_test(self, df, active_mask, enable_be=True, label="Test"):
        be_pts = 2.0 if enable_be else 999.0
        
        # Override TradeExecutionEngine inside run_simulation
        lot_size = 65
        exec_engine = TradeExecutionEngine(
            lot_size=lot_size,
            target_pts=3.0,
            break_even_activation_pts=be_pts,
            max_premium_loss_cap=5.0,
            strike_selection="ATM"
        )
        
        # Run standard simulation using this exec_engine
        df = df.copy()
        df["day"] = df["date"].dt.date
        df["time_str"] = df["date"].dt.strftime("%H:%M")

        df_indexed = df.set_index("date")
        df_3m_all = df_indexed.resample("3min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
        }).dropna().reset_index()
        df_3m_all["day"] = df_3m_all["date"].dt.date

        days_in_order = sorted(df["day"].unique())
        df_records = df.to_dict("records")
        df_3m_records = df_3m_all.to_dict("records")

        day_indices = {}
        for idx, r in enumerate(df_records):
            d = r["day"]
            if d not in day_indices:
                day_indices[d] = []
            day_indices[d].append(idx)

        day_3m_indices = {}
        for idx, r in enumerate(df_3m_records):
            d = r["day"]
            if d not in day_3m_indices:
                day_3m_indices[d] = []
            day_3m_indices[d].append(idx)

        pdl_map = {}
        pdh_map = {}
        for i, d in enumerate(days_in_order):
            if i > 0:
                prev_d = days_in_order[i - 1]
                prev_idxs = day_indices[prev_d]
                prev_highs = [df_records[k]["high"] for k in prev_idxs]
                prev_lows = [df_records[k]["low"] for k in prev_idxs]
                pdh_map[d] = max(prev_highs)
                pdl_map[d] = min(prev_lows)
            else:
                pdh_map[d] = None
                pdl_map[d] = None

        trades = []
        active_trade = None
        current_day = None
        consecutive_losses = 0
        cooldown_until_idx = -1

        for i in range(25, len(df_records)):
            curr_bar = df_records[i]
            bar_day = curr_bar["day"]
            time_str = curr_bar["time_str"]

            if bar_day != current_day:
                current_day = bar_day
                consecutive_losses = 0
                cooldown_until_idx = -1

            if active_trade:
                tr = exec_engine.process_exit_conditions(
                    active_trade=active_trade,
                    curr_bar=curr_bar,
                    bar_idx=i,
                    entry_bar_idx=active_trade["entry_bar_idx"]
                )
                if tr:
                    trades.append(tr)
                    if tr.exit_reason == "INITIAL_SL":
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0
                    active_trade = None
                    cooldown_until_idx = i + 1
                    continue

            is_trading_hours = ("09:20" <= time_str < "15:00")
            if self.config.trading_hours.pause_lunch_chop:
                if self.config.trading_hours.lunch_chop_start <= time_str < self.config.trading_hours.lunch_chop_end:
                    is_trading_hours = False

            can_open = is_trading_hours and (consecutive_losses < 3) and (i >= cooldown_until_idx)

            day_idxs = day_indices[bar_day]
            start_day_idx = day_idxs[0]
            if (i - start_day_idx) < 15:
                continue

            c1_slice = df_records[start_day_idx : i + 1]
            sub_1m = df.iloc[max(0, i - 100) : i + 1]

            m3_idxs = [k for k in day_3m_indices.get(bar_day, []) if df_3m_records[k]["date"] <= curr_bar["date"]]
            if len(m3_idxs) < 5:
                continue
            c3_slice = [df_3m_records[k] for k in m3_idxs]

            from nifty_algo.indicators.technical import TechnicalIndicators
            indicators = TechnicalIndicators.analyze_indicators(sub_1m)
            today_1m_df = df.iloc[start_day_idx : i + 1]
            today_3m_df = df_3m_all.iloc[m3_idxs]
            structure = self.structure_engine.compute_structure(
                today_1m_df, today_3m_df, pdh=pdh_map.get(bar_day), pdl=pdl_map.get(bar_day)
            )

            oi_mock = {"oi_bias": "BULLISH_PE_WRITING" if indicators.get("ema_bullish") else "BEARISH_CE_WRITING", "pcr": 1.2 if indicators.get("ema_bullish") else 0.8}

            decision, _ = self.coordinator.evaluate_all_engines(
                candles_1m=c1_slice,
                candles_3m=c3_slice,
                structure=structure,
                indicators=indicators,
                oi_data=oi_mock,
                has_open_position=(active_trade is not None),
                bar_idx=i,
                active_engine_mask=active_mask
            )

            if not decision.should_execute or not can_open:
                continue

            dir_str = "BULLISH" if decision.direction == "CE" else "BEARISH"
            strike, delta, base_prem = exec_engine.select_strike(curr_bar["close"], dir_str)
            entry_premium = base_prem - self.config.buy_limit_discount_offset + exec_engine.slippage_entry
            initial_stop = entry_premium - exec_engine.max_premium_loss_cap

            active_trade = {
                "trade_id": f"TRD_{len(trades)+1:03d}",
                "entry_time": time_str,
                "entry_bar_idx": i,
                "direction": dir_str,
                "strike": strike,
                "delta": delta,
                "entry_spot": curr_bar["close"],
                "entry_premium": entry_premium,
                "current_stop": initial_stop,
                "be_activated": False,
                "setup_name": decision.primary_strategy,
                "confidence": decision.combined_confidence,
                "contributing_factors": decision.contributing_strategies,
                "mfe": 0.0,
                "mae": 0.0
            }

        total_trades = len(trades)
        wins = sum(1 for t in trades if t.exit_reason == "TARGET")
        be_exits = sum(1 for t in trades if t.exit_reason == "BREAK_EVEN")
        sl_exits = sum(1 for t in trades if t.exit_reason == "INITIAL_SL")
        gross_pnl = sum(t.gross_pnl for t in trades)
        charges = sum(t.charges for t in trades)
        net_pnl = sum(t.net_pnl for t in trades)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_wins = sum(t.gross_pnl for t in trades if t.gross_pnl > 0)
        gross_losses = abs(sum(t.gross_pnl for t in trades if t.gross_pnl < 0))
        pf = (gross_wins / gross_losses) if gross_losses > 0 else 99.9

        peak = 0.0
        max_dd = 0.0
        cum = 0.0
        for t in trades:
            cum += t.net_pnl
            if cum > peak:
                peak = cum
            if (peak - cum) > max_dd:
                max_dd = peak - cum

        return {
            "label": label,
            "enable_be": enable_be,
            "trades": total_trades,
            "win_rate": round(win_rate, 1),
            "targets": wins,
            "be_exits": be_exits,
            "sl_exits": sl_exits,
            "gross_pnl": round(gross_pnl, 2),
            "charges": round(charges, 2),
            "net_pnl": round(net_pnl, 2),
            "profit_factor": round(pf, 2),
            "max_dd": round(max_dd, 2)
        }

if __name__ == "__main__":
    runner = ComparativeBERunner()
    df = runner.load_data()

    print("=" * 110)
    print("BACKTEST EXPERIMENT: WITH BE LOCK (+2.0 PTS) VS WITHOUT BE LOCK (PURE +3.0 TARGET VS SL)")
    print("Underlying: NIFTY ATM Options | Period: Nov 05 - Nov 13, 2026")
    print("=" * 110)

    experiments = [
        ("Recommended (Mom + Breakout Boosted by Trap & OI)", ['ENGINE_1_MOMENTUM', 'ENGINE_4_BREAKOUT', 'ENGINE_3_TRAP', 'ENGINE_6_OI_INTEL']),
        ("Engine 1 Only (Momentum)", ['ENGINE_1_MOMENTUM']),
        ("Engine 4 Only (Breakout)", ['ENGINE_4_BREAKOUT']),
        ("All Six Engines Combined", None)
    ]

    results = []
    for exp_name, mask in experiments:
        r_with = runner.run_be_test(df, mask, enable_be=True, label=f"{exp_name} [WITH BE +2]")
        r_without = runner.run_be_test(df, mask, enable_be=False, label=f"{exp_name} [NO BE - Target +3 or SL]")
        results.append(r_with)
        results.append(r_without)

    df_res = pd.DataFrame(results)
    cols = ["label", "trades", "win_rate", "targets", "be_exits", "sl_exits", "gross_pnl", "charges", "net_pnl", "profit_factor", "max_dd"]
    print(df_res[cols].to_string(index=False))
