"""
CANSLIM Monitor - Position Sizer
================================
Calculates share quantities for entries, pyramids, and exits.

Based on IBD methodology:
- Initial entry: 50% of target position
- Pyramid 1: Add 25% at +2-2.5% from entry
- Pyramid 2: Add 25% at +4-5% from entry
- TP1: Sell 1/3 at +20%
- TP2: Sell 1/2 of remaining at +25%
- Trail remainder with 10-week line or 21 EMA

Version: 1.0
Created: January 15, 2026
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from enum import Enum


class PositionPhase(Enum):
    """Position building phases."""
    INITIAL = "initial"      # 50% entry
    PYRAMID_1 = "pyramid_1"  # +25% (total 75%)
    PYRAMID_2 = "pyramid_2"  # +25% (total 100%)
    FULL = "full"            # 100% complete


class ExitPhase(Enum):
    """Position exit phases."""
    TP1 = "tp1"              # First profit take (1/3)
    TP2 = "tp2"              # Second profit take (1/2 remaining)
    TRAILING = "trailing"    # Final trailing portion
    CLOSED = "closed"        # Fully exited


@dataclass
class PositionSizeResult:
    """Result of position size calculation."""
    # Target position
    target_shares: int
    target_value: float
    
    # Initial entry
    initial_shares: int
    initial_value: float
    initial_pct: float = 50.0
    
    # Pyramid 1
    pyramid1_shares: int = 0
    pyramid1_trigger_pct: float = 2.5
    pyramid1_est_price: float = 0.0
    pyramid1_est_value: float = 0.0
    pyramid1_pct: float = 25.0
    
    # Pyramid 2
    pyramid2_shares: int = 0
    pyramid2_trigger_pct: float = 5.0
    pyramid2_est_price: float = 0.0
    pyramid2_est_value: float = 0.0
    pyramid2_pct: float = 25.0
    
    # Risk metrics
    risk_per_share: float = 0.0
    total_risk: float = 0.0
    risk_pct_of_account: float = 0.0
    
    # Summary
    phase: PositionPhase = PositionPhase.INITIAL
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'target_shares': self.target_shares,
            'target_value': round(self.target_value, 2),
            'initial': {
                'shares': self.initial_shares,
                'value': round(self.initial_value, 2),
                'pct': self.initial_pct
            },
            'pyramid1': {
                'shares': self.pyramid1_shares,
                'trigger_pct': self.pyramid1_trigger_pct,
                'est_price': round(self.pyramid1_est_price, 2),
                'est_value': round(self.pyramid1_est_value, 2),
                'pct': self.pyramid1_pct
            },
            'pyramid2': {
                'shares': self.pyramid2_shares,
                'trigger_pct': self.pyramid2_trigger_pct,
                'est_price': round(self.pyramid2_est_price, 2),
                'est_value': round(self.pyramid2_est_value, 2),
                'pct': self.pyramid2_pct
            },
            'risk': {
                'per_share': round(self.risk_per_share, 2),
                'total': round(self.total_risk, 2),
                'pct_of_account': round(self.risk_pct_of_account, 2)
            },
            'phase': self.phase.value
        }


@dataclass
class ProfitExitResult:
    """Result of profit exit calculation."""
    # TP1: Sell 1/3 at +20%
    tp1_shares: int
    tp1_trigger_pct: float = 20.0
    tp1_price: float = 0.0
    remaining_after_tp1: int = 0
    
    # TP2: Sell 1/2 of remaining at +25%
    tp2_shares: int = 0
    tp2_trigger_pct: float = 25.0
    tp2_price: float = 0.0
    remaining_after_tp2: int = 0
    
    # Trailing: Rest trails 10-week or 21 EMA
    trailing_shares: int = 0
    trailing_method: str = "10-week line"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'tp1': {
                'shares_to_sell': self.tp1_shares,
                'trigger_pct': self.tp1_trigger_pct,
                'price': round(self.tp1_price, 2),
                'remaining': self.remaining_after_tp1
            },
            'tp2': {
                'shares_to_sell': self.tp2_shares,
                'trigger_pct': self.tp2_trigger_pct,
                'price': round(self.tp2_price, 2),
                'remaining': self.remaining_after_tp2
            },
            'trailing': {
                'shares': self.trailing_shares,
                'method': self.trailing_method
            }
        }


class PositionSizer:
    """
    Calculate share quantities for entries and exits.
    
    IBD Rules:
    - "Start with 50%, add 25%, add 25% for full position"
    - Never risk more than 1% of account per trade
    - Position size = Risk Amount / Stop Distance
    - Take profits at 20-25% gains
    """
    
    def __init__(
        self,
        account_risk_pct: float = 1.0,
        max_position_pct: float = 10.0,
        initial_pct: float = 50.0,
        pyramid1_pct: float = 25.0,
        pyramid2_pct: float = 25.0,
        pyramid1_trigger: float = 2.5,
        pyramid2_trigger: float = 5.0,
        tp1_pct: float = 20.0,
        tp2_pct: float = 25.0,
        lot_size: int = 5
    ):
        """
        Initialize position sizer.
        
        Args:
            account_risk_pct: Max % of account to risk per trade (default 1%)
            max_position_pct: Max % of account in single position (default 10%)
            initial_pct: Initial entry as % of target (default 50%)
            pyramid1_pct: First pyramid add as % of target (default 25%)
            pyramid2_pct: Second pyramid add as % of target (default 25%)
            pyramid1_trigger: % above entry to trigger pyramid 1 (default 2.5%)
            pyramid2_trigger: % above entry to trigger pyramid 2 (default 5%)
            tp1_pct: % gain to trigger first profit take (default 20%)
            tp2_pct: % gain to trigger second profit take (default 25%)
            lot_size: Round shares to this lot size (default 5)
        """
        self.account_risk_pct = account_risk_pct
        self.max_position_pct = max_position_pct
        self.initial_pct = initial_pct
        self.pyramid1_pct = pyramid1_pct
        self.pyramid2_pct = pyramid2_pct
        self.pyramid1_trigger = pyramid1_trigger
        self.pyramid2_trigger = pyramid2_trigger
        self.tp1_pct = tp1_pct
        self.tp2_pct = tp2_pct
        self.lot_size = lot_size
    
    def calculate_target_position(
        self,
        account_value: float,
        entry_price: float,
        stop_price: float
    ) -> PositionSizeResult:
        """
        Calculate full position size based on risk management.
        
        Uses the smaller of:
        1. Max position by account % (e.g., 10% of $100k = $10k)
        2. Max position by risk % (e.g., 1% risk / 8% stop = 12.5%)
        
        Args:
            account_value: Total account value
            entry_price: Planned entry price
            stop_price: Hard stop price
        
        Returns:
            PositionSizeResult with full breakdown
        """
        # Calculate risk per share
        risk_per_share = entry_price - stop_price
        if risk_per_share <= 0:
            raise ValueError(f"Stop price must be below entry: {stop_price} >= {entry_price}")
        
        # Method 1: Max position by account percentage
        max_position_dollars = account_value * (self.max_position_pct / 100)
        max_shares_by_account = int(max_position_dollars / entry_price)
        
        # Method 2: Max position by risk percentage
        max_risk_dollars = account_value * (self.account_risk_pct / 100)
        max_shares_by_risk = int(max_risk_dollars / risk_per_share)
        
        # Target is the smaller of the two (most conservative)
        target_shares = min(max_shares_by_account, max_shares_by_risk)
        
        # Round to lot size
        target_shares = self._round_to_lot(target_shares)
        
        if target_shares <= 0:
            target_shares = self.lot_size  # Minimum position
        
        # Calculate phase allocations
        initial_shares = self._round_to_lot(int(target_shares * self.initial_pct / 100))
        pyramid1_shares = self._round_to_lot(int(target_shares * self.pyramid1_pct / 100))
        
        # Pyramid 2 gets the remainder to ensure we reach exactly target
        pyramid2_shares = target_shares - initial_shares - pyramid1_shares
        
        # Calculate estimated prices for pyramids
        pyramid1_price = entry_price * (1 + self.pyramid1_trigger / 100)
        pyramid2_price = entry_price * (1 + self.pyramid2_trigger / 100)
        
        return PositionSizeResult(
            target_shares=target_shares,
            target_value=target_shares * entry_price,
            initial_shares=initial_shares,
            initial_value=initial_shares * entry_price,
            initial_pct=self.initial_pct,
            pyramid1_shares=pyramid1_shares,
            pyramid1_trigger_pct=self.pyramid1_trigger,
            pyramid1_est_price=pyramid1_price,
            pyramid1_est_value=pyramid1_shares * pyramid1_price,
            pyramid1_pct=self.pyramid1_pct,
            pyramid2_shares=pyramid2_shares,
            pyramid2_trigger_pct=self.pyramid2_trigger,
            pyramid2_est_price=pyramid2_price,
            pyramid2_est_value=pyramid2_shares * pyramid2_price,
            pyramid2_pct=self.pyramid2_pct,
            risk_per_share=risk_per_share,
            total_risk=target_shares * risk_per_share,
            risk_pct_of_account=(target_shares * risk_per_share) / account_value * 100,
            phase=PositionPhase.INITIAL
        )
    
    def calculate_profit_exits(
        self,
        current_shares: int,
        avg_cost: float,
        eight_week_hold_active: bool = False
    ) -> ProfitExitResult:
        """
        Calculate share quantities for profit taking.
        
        Standard rules:
        - TP1: Sell 1/3 at +20% gain
        - TP2: Sell 1/2 of remaining at +25% gain
        - Trail: Hold rest until exit signal (10-week line or 21 EMA)
        
        8-Week Hold Exception:
        - If triggered (20%+ in 1-3 weeks), TP1 is suppressed
        - Position remains at 100% during 8-week hold
        - After 8 weeks expire, resume normal TP rules
        
        Args:
            current_shares: Total shares currently held
            avg_cost: Average cost basis
            eight_week_hold_active: If 8-week hold rule is active
        
        Returns:
            ProfitExitResult with exit plan
        """
        if eight_week_hold_active:
            # 8-week hold: No selling until hold expires
            return ProfitExitResult(
                tp1_shares=0,
                tp1_trigger_pct=self.tp1_pct,
                tp1_price=avg_cost * (1 + self.tp1_pct / 100),
                remaining_after_tp1=current_shares,
                tp2_shares=0,
                tp2_trigger_pct=self.tp2_pct,
                tp2_price=avg_cost * (1 + self.tp2_pct / 100),
                remaining_after_tp2=current_shares,
                trailing_shares=current_shares,
                trailing_method="8-week hold active - use 10-week line after expiry"
            )
        
        # Standard profit taking
        tp1_shares = self._round_to_lot(int(current_shares / 3))  # Sell 1/3
        remaining_after_tp1 = current_shares - tp1_shares
        
        tp2_shares = self._round_to_lot(int(remaining_after_tp1 / 2))  # Sell 1/2 of remaining
        trailing_shares = remaining_after_tp1 - tp2_shares
        
        return ProfitExitResult(
            tp1_shares=tp1_shares,
            tp1_trigger_pct=self.tp1_pct,
            tp1_price=avg_cost * (1 + self.tp1_pct / 100),
            remaining_after_tp1=remaining_after_tp1,
            tp2_shares=tp2_shares,
            tp2_trigger_pct=self.tp2_pct,
            tp2_price=avg_cost * (1 + self.tp2_pct / 100),
            remaining_after_tp2=trailing_shares,
            trailing_shares=trailing_shares,
            trailing_method="10-week line"
        )
    
    def calculate_avg_cost(
        self,
        entries: list[tuple[int, float]]
    ) -> float:
        """
        Calculate weighted average cost basis.
        
        Args:
            entries: List of (shares, price) tuples
        
        Returns:
            Weighted average cost per share
        """
        total_cost = 0.0
        total_shares = 0
        
        for shares, price in entries:
            if shares > 0 and price > 0:
                total_cost += shares * price
                total_shares += shares
        
        return total_cost / total_shares if total_shares > 0 else 0.0
    
    def calculate_current_position_pct(
        self,
        current_shares: int,
        target_shares: int
    ) -> float:
        """
        Calculate current position as % of target.
        
        Args:
            current_shares: Shares currently held
            target_shares: Target full position
        
        Returns:
            Percentage (50, 75, 100, etc.)
        """
        if target_shares <= 0:
            return 0.0
        return (current_shares / target_shares) * 100
    
    def get_position_phase(
        self,
        current_shares: int,
        target_shares: int
    ) -> PositionPhase:
        """
        Determine current position building phase.
        
        Args:
            current_shares: Shares currently held
            target_shares: Target full position
        
        Returns:
            PositionPhase enum
        """
        pct = self.calculate_current_position_pct(current_shares, target_shares)
        
        if pct >= 99:  # Allow for rounding
            return PositionPhase.FULL
        elif pct >= 74:
            return PositionPhase.PYRAMID_2
        elif pct >= 49:
            return PositionPhase.PYRAMID_1
        else:
            return PositionPhase.INITIAL
    
    def _round_to_lot(self, shares: int) -> int:
        """Round shares to nearest lot size for cleaner orders."""
        if shares <= 0:
            return 0
        return max(self.lot_size, round(shares / self.lot_size) * self.lot_size)
    
    def format_entry_action(self, result: PositionSizeResult, symbol: str) -> str:
        """
        Format entry action for Discord alert.
        
        Args:
            result: PositionSizeResult from calculate_target_position
            symbol: Stock symbol
        
        Returns:
            Formatted action string
        """
        return (
            f"▶ ACTION: Buy {result.initial_shares} shares (50% initial position)\n"
            f"   Target Full Position: {result.target_shares} shares\n"
            f"   Estimated Cost: ${result.initial_value:,.2f}\n"
            f"   Total Risk: ${result.total_risk:,.2f} ({result.risk_pct_of_account:.1f}% of account)"
        )
    
    def format_pyramid_action(
        self,
        phase: PositionPhase,
        shares: int,
        current_shares: int,
        target_shares: int
    ) -> str:
        """
        Format pyramid action for Discord alert.
        
        Args:
            phase: Which pyramid (PYRAMID_1 or PYRAMID_2)
            shares: Shares to add
            current_shares: Current position
            target_shares: Target position
        
        Returns:
            Formatted action string
        """
        new_total = current_shares + shares
        new_pct = self.calculate_current_position_pct(new_total, target_shares)
        
        if phase == PositionPhase.PYRAMID_1:
            return f"▶ ACTION: Add {shares} shares (brings position to {new_pct:.0f}%)"
        else:
            return f"▶ ACTION: Add {shares} shares (completes full position - {new_pct:.0f}%)"
    
    def format_tp_action(
        self,
        exit_result: ProfitExitResult,
        phase: str,
        current_pnl_pct: float
    ) -> str:
        """
        Format take profit action for Discord alert.
        
        Args:
            exit_result: ProfitExitResult from calculate_profit_exits
            phase: "tp1" or "tp2"
            current_pnl_pct: Current P&L percentage
        
        Returns:
            Formatted action string
        """
        if phase == "tp1":
            return (
                f"▶ ACTION: Sell {exit_result.tp1_shares} shares ({current_pnl_pct:.1f}% gain)\n"
                f"   Remaining: {exit_result.remaining_after_tp1} shares"
            )
        else:
            return (
                f"▶ ACTION: Sell {exit_result.tp2_shares} shares ({current_pnl_pct:.1f}% gain)\n"
                f"   Trailing: {exit_result.trailing_shares} shares with {exit_result.trailing_method}"
            )


# =============================================================================
# STANDALONE TESTING
# =============================================================================

def main():
    """Test the position sizer."""
    sizer = PositionSizer()
    
    print("=" * 60)
    print("POSITION SIZER TEST")
    print("=" * 60)
    
    # Test case: $100k account, $50 stock, 7% stop
    account = 100000
    entry = 50.00
    stop = 46.00  # 8% stop
    
    print(f"\nAccount: ${account:,}")
    print(f"Entry: ${entry:.2f}")
    print(f"Stop: ${stop:.2f} ({((entry - stop) / entry * 100):.1f}% risk)")
    
    result = sizer.calculate_target_position(account, entry, stop)
    
    print(f"\n--- Target Position ---")
    print(f"Target Shares: {result.target_shares}")
    print(f"Target Value: ${result.target_value:,.2f}")
    print(f"Risk per Share: ${result.risk_per_share:.2f}")
    print(f"Total Risk: ${result.total_risk:.2f} ({result.risk_pct_of_account:.1f}% of account)")
    
    print(f"\n--- Entry Plan ---")
    print(f"Initial (50%): {result.initial_shares} shares @ ${entry:.2f} = ${result.initial_value:,.2f}")
    print(f"Pyramid 1 (25%): {result.pyramid1_shares} shares @ ${result.pyramid1_est_price:.2f}")
    print(f"Pyramid 2 (25%): {result.pyramid2_shares} shares @ ${result.pyramid2_est_price:.2f}")
    
    # Test profit exits
    print(f"\n--- Profit Exit Plan ---")
    exit_plan = sizer.calculate_profit_exits(result.target_shares, entry)
    
    print(f"TP1 (+{exit_plan.tp1_trigger_pct}%): Sell {exit_plan.tp1_shares} shares @ ${exit_plan.tp1_price:.2f}")
    print(f"   Remaining: {exit_plan.remaining_after_tp1} shares")
    print(f"TP2 (+{exit_plan.tp2_trigger_pct}%): Sell {exit_plan.tp2_shares} shares @ ${exit_plan.tp2_price:.2f}")
    print(f"   Trailing: {exit_plan.trailing_shares} shares via {exit_plan.trailing_method}")
    
    # Test 8-week hold
    print(f"\n--- 8-Week Hold Mode ---")
    hold_plan = sizer.calculate_profit_exits(result.target_shares, entry, eight_week_hold_active=True)
    print(f"TP1: SUPPRESSED (8-week hold active)")
    print(f"Trailing: {hold_plan.trailing_shares} shares - {hold_plan.trailing_method}")
    
    # Format for Discord
    print(f"\n--- Discord Format ---")
    print(sizer.format_entry_action(result, "NVDA"))


if __name__ == "__main__":
    main()
