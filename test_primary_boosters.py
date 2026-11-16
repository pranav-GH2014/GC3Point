from run_six_engine_comparison import SixEngineBacktestRunner
from nifty_algo.strategies.signal_arbitration_engine import SignalArbitrationEngine, ArbitratedDecision

class BoosterArbitrator(SignalArbitrationEngine):
    def arbitrate(self, signals, indicators, has_open_position, current_bar_idx=0, **kwargs):
        if has_open_position:
            return ArbitratedDecision(False, None, 'NONE', [], 0.0, 'REJECT', 0.0, 5.0, 3.0, 'Position active', ['REJECTED_OPEN_POSITION_ACTIVE'])
        
        # Split into primary initiators and secondary boosters
        primary_sigs = [s for s in signals if s.triggered and s.strategy_id in ('ENGINE_1_MOMENTUM', 'ENGINE_4_BREAKOUT')]
        booster_sigs = [s for s in signals if s.triggered and s.strategy_id in ('ENGINE_3_TRAP', 'ENGINE_6_OI_INTEL')]
        
        if not primary_sigs:
            return ArbitratedDecision(False, None, 'NONE', [], 0.0, 'REJECT', 0.0, 5.0, 3.0, 'No primary driver', ['NO_PRIMARY_DRIVER'])
        
        # Best primary signal
        primary_sigs.sort(key=lambda s: s.confidence, reverse=True)
        best_p = primary_sigs[0]
        chosen_dir = best_p.direction
        
        # Check aligned boosters
        aligned_boosters = [b for b in booster_sigs if b.direction == chosen_dir]
        opposing_boosters = [b for b in booster_sigs if b.direction != chosen_dir]
        
        score = best_p.confidence
        # Booster addition (+8 pts per aligned booster)
        if aligned_boosters:
            score += 8.0 * len(aligned_boosters)
        # Opposing penalty (-6 pts)
        if opposing_boosters:
            score -= 6.0 * len(opposing_boosters)
            
        score = min(99.0, max(0.0, score))
        
        if score < self.min_confidence_threshold:
            return ArbitratedDecision(False, None, 'NONE', [], score, 'REJECT', 0.0, 5.0, 3.0, f'Score {score} < {self.min_confidence_threshold}', ['SCORE_BELOW_THRESHOLD'])
            
        contribs = [best_p.strategy_name] + [b.strategy_name for b in aligned_boosters]
        return ArbitratedDecision(
            should_execute=True,
            direction=chosen_dir,
            primary_strategy=best_p.strategy_name,
            contributing_strategies=contribs,
            combined_confidence=round(score, 1),
            decision_tier='QUALIFIED',
            reference_spot=best_p.reference_price,
            stop_loss_pts=best_p.stop_loss_pts,
            target_pts=3.0,
            entry_reason=f"Primary [{best_p.strategy_name}] boosted by {[b.strategy_name for b in aligned_boosters]}",
            rejection_reasons=[],
            duplicate_merged=(len(primary_sigs) > 1 or len(aligned_boosters) > 0)
        )

runner = SixEngineBacktestRunner()
runner.coordinator.arbitrator = BoosterArbitrator(min_confidence_threshold=80.0)
df = runner.load_data()
res = runner.run_simulation(
    df,
    active_engine_mask=['ENGINE_1_MOMENTUM', 'ENGINE_4_BREAKOUT', 'ENGINE_3_TRAP', 'ENGINE_6_OI_INTEL'],
    label='PrimaryDriversPlusBoosters'
)

print("=" * 80)
print("PRIMARY DRIVERS (MOMENTUM & BREAKOUT) + BOOSTERS (TRAP & OI) [MIN 80.0]")
print("=" * 80)
print(f"Total Trades: {res['executed_trades']} ({res['trades_per_day']} / day)")
print(f"Win Rate: {res['win_rate']}% | Wins (+3): {res['wins']} | BE (+2): {res['be_exits']} | SL: {res['sl_exits']}")
print(f"Gross P&L: Rs {res['gross_pnl']:+,.2f}")
print(f"Total Charges: Rs {res['charges']:,.2f}")
print(f"Net Realized P&L: Rs {res['net_pnl']:+,.2f}")
print(f"Profit Factor: {res['profit_factor']:.2f}")
print(f"Max Drawdown: Rs {res['max_drawdown']:,.2f}")
print(f"Avg Holding Time: {res['avg_holding_time_min']} min")

res_itm = runner.run_simulation(
    df,
    active_engine_mask=['ENGINE_1_MOMENTUM', 'ENGINE_4_BREAKOUT', 'ENGINE_3_TRAP', 'ENGINE_6_OI_INTEL'],
    strike_selection='ITM_1',
    label='ITM_1_Boosters'
)
print("\n" + "=" * 80)
print("ITM_1 (Delta ~0.60) PRIMARY + BOOSTERS [MIN 80.0]")
print("=" * 80)
print(f"Total Trades: {res_itm['executed_trades']} ({res_itm['trades_per_day']} / day)")
print(f"Win Rate: {res_itm['win_rate']}% | Wins (+3): {res_itm['wins']} | BE (+2): {res_itm['be_exits']} | SL: {res_itm['sl_exits']}")
print(f"Gross P&L: Rs {res_itm['gross_pnl']:+,.2f}")
print(f"Total Charges: Rs {res_itm['charges']:,.2f}")
print(f"Net Realized P&L: Rs {res_itm['net_pnl']:+,.2f}")
print(f"Profit Factor: {res_itm['profit_factor']:.2f}")
print(f"Max Drawdown: Rs {res_itm['max_drawdown']:,.2f}")

