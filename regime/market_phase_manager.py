"""
Market Phase Manager
====================

Centralized controller for market phase state transitions following IBD methodology.

This module is the single source of truth for:
- Current market phase (CONFIRMED_UPTREND, UPTREND_PRESSURE, RALLY_ATTEMPT, CORRECTION)
- Phase transition logic
- Phase change detection and alerting

IBD Phase Transition Rules:
- CORRECTION → RALLY_ATTEMPT: First up day after new low
- RALLY_ATTEMPT → CORRECTION: Price undercuts rally low
- RALLY_ATTEMPT → CONFIRMED_UPTREND: FTD (Day 4+, +1.25%, higher volume)
- CONFIRMED_UPTREND → UPTREND_PRESSURE: 5-6 D-days accumulate
- UPTREND_PRESSURE → CONFIRMED_UPTREND: D-days drop below threshold OR FTD
- UPTREND_PRESSURE → CORRECTION: 7+ D-days OR severe breakdown

Usage:
    manager = MarketPhaseManager.from_config(config, db_session)

    # Update phase based on current data
    transition = manager.update_phase(dist_data, ftd_data)

    if transition.phase_changed:
        send_phase_change_alert(transition)
"""

import logging
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import desc

from .models_regime import (
    MarketPhaseHistory, PhaseChangeType, DDayTrend
)
from .ftd_tracker import MarketPhase

logger = logging.getLogger(__name__)


@dataclass
class PhaseTransition:
    """Result of a phase update check."""
    previous_phase: MarketPhase
    current_phase: MarketPhase
    phase_changed: bool
    change_type: PhaseChangeType
    trigger_reason: str
    trigger_details: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def is_upgrade(self) -> bool:
        return self.change_type == PhaseChangeType.UPGRADE

    @property
    def is_downgrade(self) -> bool:
        return self.change_type == PhaseChangeType.DOWNGRADE


@dataclass
class CombinedDistributionData:
    """Combined distribution data for SPY and QQQ (for type hints)."""
    spy_count: int
    qqq_count: int
    spy_5day_delta: int
    qqq_5day_delta: int
    trend: DDayTrend
    spy_dates: List[date]
    qqq_dates: List[date]

    # Expiration tracking
    spy_expired_today: int = 0
    qqq_expired_today: int = 0
    expiration_details: List[dict] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return self.spy_count + self.qqq_count

    @property
    def total_expired_today(self) -> int:
        """Total D-days that expired today."""
        return self.spy_expired_today + self.qqq_expired_today

    @property
    def had_expirations(self) -> bool:
        """True if any D-days expired today."""
        return self.total_expired_today > 0


@dataclass
class FTDData:
    """Follow-Through Day data for regime calculation (for type hints)."""
    market_phase: str
    in_rally_attempt: bool
    rally_day: int
    has_confirmed_ftd: bool
    ftd_still_valid: bool
    days_since_ftd: Optional[int]
    ftd_today: bool
    rally_failed_today: bool
    ftd_score_adjustment: float

    # Enhanced tracking
    ftd_gain_pct: Optional[float] = None
    ftd_volume_ratio: Optional[float] = None
    rally_low: Optional[float] = None
    rally_low_date: Optional[date] = None
    previous_phase: Optional[str] = None


@dataclass
class RallyStatus:
    """Current rally attempt status (for type hints)."""
    in_rally_attempt: bool
    rally_day: int
    rally_low: Optional[float] = None
    rally_low_date: Optional[date] = None
    failed_today: bool = False


class MarketPhaseManager:
    """
    Centralized market phase state manager.

    Responsibilities:
    - Track current market phase
    - Evaluate phase transition conditions
    - Record phase history
    - Generate phase change events

    Phase Hierarchy (most bullish to most bearish):
    1. CONFIRMED_UPTREND (Green)
    2. UPTREND_PRESSURE (Yellow)
    3. RALLY_ATTEMPT (Yellow, transitional)
    4. CORRECTION (Red)
    """

    # Phase transition thresholds
    DEFAULT_THRESHOLDS = {
        # D-day thresholds for phase changes
        'pressure_min_ddays': 5,      # Min D-days for UPTREND_PRESSURE
        'correction_min_ddays': 7,    # Min D-days for CORRECTION
        'confirmed_max_ddays': 4,     # Max D-days to stay CONFIRMED

        # FTD thresholds
        'ftd_min_gain_pct': 1.25,     # Min % gain for FTD
        'ftd_min_rally_day': 4,       # Earliest day for FTD

        # Rally thresholds
        'rally_undercut_buffer': 0.0,  # Buffer below rally low (0 = exact)
    }

    # Phase ordering for upgrade/downgrade detection
    PHASE_ORDER = {
        MarketPhase.CONFIRMED_UPTREND: 4,
        MarketPhase.UPTREND_PRESSURE: 3,
        MarketPhase.RALLY_ATTEMPT: 2,
        MarketPhase.CORRECTION: 1,
        MarketPhase.MARKET_IN_CORRECTION: 1,
    }

    def __init__(
        self,
        db_session: Session,
        thresholds: dict = None
    ):
        """
        Initialize phase manager.

        Args:
            db_session: SQLAlchemy session
            thresholds: Optional threshold overrides
        """
        self.db = db_session
        self.thresholds = {**self.DEFAULT_THRESHOLDS}
        if thresholds:
            self.thresholds.update(thresholds)

        self._current_phase: Optional[MarketPhase] = None
        self._phase_start_date: Optional[date] = None

    @classmethod
    def from_config(cls, config: dict, db_session: Session) -> 'MarketPhaseManager':
        """Create manager from config dict."""
        phase_config = config.get('market_phase', {})
        thresholds = phase_config.get('thresholds', {})
        return cls(db_session=db_session, thresholds=thresholds)

    @property
    def current_phase(self) -> MarketPhase:
        """Get current market phase, loading from DB if needed."""
        if self._current_phase is None:
            self._load_current_phase()
        return self._current_phase or MarketPhase.CORRECTION

    def _load_current_phase(self):
        """Load current phase from most recent history record."""
        latest = self.db.query(MarketPhaseHistory).order_by(
            desc(MarketPhaseHistory.phase_date),
            desc(MarketPhaseHistory.id)
        ).first()

        if latest:
            try:
                self._current_phase = MarketPhase(latest.new_phase)
                self._phase_start_date = latest.phase_date
            except ValueError:
                logger.warning(f"Unknown phase in history: {latest.new_phase}")
                self._current_phase = MarketPhase.CORRECTION
        else:
            self._current_phase = MarketPhase.CORRECTION

    def update_phase(
        self,
        dist_data: Any,  # CombinedDistributionData from distribution_tracker
        ftd_data: Any = None,  # MarketPhaseStatus from ftd_tracker
        rally_status: RallyStatus = None,
        current_date: date = None
    ) -> PhaseTransition:
        """
        Evaluate and update market phase based on current data.

        This is the main entry point for phase updates. It evaluates
        all transition conditions and records any phase change.

        Args:
            dist_data: Current distribution day data
            ftd_data: Follow-through day status
            rally_status: Current rally attempt status
            current_date: Date for evaluation (default: today)

        Returns:
            PhaseTransition with details of any change
        """
        eval_date = current_date or date.today()
        previous_phase = self.current_phase

        # Evaluate new phase
        new_phase, trigger_reason, trigger_details = self._evaluate_phase(
            dist_data, ftd_data, rally_status
        )

        # Determine if phase changed
        phase_changed = new_phase != previous_phase
        change_type = self._get_change_type(previous_phase, new_phase)

        # Record transition
        transition = PhaseTransition(
            previous_phase=previous_phase,
            current_phase=new_phase,
            phase_changed=phase_changed,
            change_type=change_type,
            trigger_reason=trigger_reason,
            trigger_details=trigger_details
        )

        if phase_changed:
            self._record_phase_change(transition, dist_data, ftd_data, eval_date)
            self._current_phase = new_phase
            self._phase_start_date = eval_date

            logger.info(
                f"PHASE CHANGE: {previous_phase.value} -> {new_phase.value} "
                f"({trigger_reason})"
            )

        return transition

    def _evaluate_phase(
        self,
        dist_data: Any,
        ftd_data: Any,
        rally_status: RallyStatus
    ) -> Tuple[MarketPhase, str, dict]:
        """
        Evaluate what phase the market should be in.

        Returns:
            (new_phase, trigger_reason, trigger_details)
        """
        t = self.thresholds
        current = self.current_phase

        # Extract key metrics from dist_data
        spy_count = getattr(dist_data, 'spy_count', 0)
        qqq_count = getattr(dist_data, 'qqq_count', 0)
        max_ddays = max(spy_count, qqq_count)
        total_ddays = spy_count + qqq_count

        # Extract FTD metrics
        has_active_ftd = False
        ftd_today = False
        ftd_gain_pct = None

        if ftd_data:
            has_active_ftd = getattr(ftd_data, 'has_confirmed_ftd', False) and \
                            getattr(ftd_data, 'ftd_still_valid', False)
            ftd_today = getattr(ftd_data, 'any_ftd_today', False) or \
                       getattr(ftd_data, 'ftd_today', False)
            ftd_gain_pct = getattr(ftd_data, 'ftd_gain_pct', None)

        # Extract rally metrics
        in_rally = False
        rally_day = 0
        rally_failed = False

        if rally_status:
            in_rally = rally_status.in_rally_attempt
            rally_day = rally_status.rally_day
            rally_failed = rally_status.failed_today
        elif ftd_data:
            # Try to get from ftd_data if rally_status not provided
            in_rally = getattr(ftd_data, 'in_rally_attempt', False)
            rally_day = getattr(ftd_data, 'rally_day', 0)
            rally_failed = getattr(ftd_data, 'any_rally_failed', False) or \
                          getattr(ftd_data, 'rally_failed_today', False)

        # Check for expiration-driven improvement
        had_expirations = getattr(dist_data, 'had_expirations', False) or \
                         getattr(dist_data, 'total_expired_today', 0) > 0

        details = {
            'max_ddays': max_ddays,
            'total_ddays': total_ddays,
            'spy_ddays': spy_count,
            'qqq_ddays': qqq_count,
            'has_active_ftd': has_active_ftd,
            'ftd_today': ftd_today,
            'rally_day': rally_day,
            'had_expirations': had_expirations,
        }

        # === PHASE EVALUATION LOGIC ===

        # Check for FTD (highest priority upgrade)
        if ftd_today:
            details['ftd_gain_pct'] = ftd_gain_pct
            return (
                MarketPhase.CONFIRMED_UPTREND,
                "Follow-Through Day confirmed",
                details
            )

        # Check for rally failure (immediate downgrade to CORRECTION)
        if rally_failed and current == MarketPhase.RALLY_ATTEMPT:
            return (
                MarketPhase.CORRECTION,
                "Rally attempt failed - undercut rally low",
                details
            )

        # === CORRECTION STATE ===
        if current == MarketPhase.CORRECTION:
            # Only way out is rally attempt start
            if in_rally and rally_day >= 1:
                return (
                    MarketPhase.RALLY_ATTEMPT,
                    f"Rally attempt started - Day {rally_day}",
                    details
                )
            return (MarketPhase.CORRECTION, "In correction, awaiting rally", details)

        # === RALLY_ATTEMPT STATE ===
        if current == MarketPhase.RALLY_ATTEMPT:
            # Continue rally attempt
            if in_rally:
                return (
                    MarketPhase.RALLY_ATTEMPT,
                    f"Rally attempt continuing - Day {rally_day}",
                    details
                )
            # Rally ended without FTD
            return (
                MarketPhase.CORRECTION,
                "Rally attempt ended without FTD",
                details
            )

        # === UPTREND_PRESSURE STATE ===
        if current == MarketPhase.UPTREND_PRESSURE:
            # Check for improvement (D-days dropping due to expiration or rally)
            if max_ddays <= t['confirmed_max_ddays']:
                if has_active_ftd:
                    trigger = "D-days dropped"
                    if had_expirations:
                        trigger = "D-days expired"
                    return (
                        MarketPhase.CONFIRMED_UPTREND,
                        f"{trigger} to {max_ddays} - upgrading to Confirmed Uptrend",
                        details
                    )

            # Check for deterioration
            if max_ddays >= t['correction_min_ddays']:
                return (
                    MarketPhase.CORRECTION,
                    f"D-days reached {max_ddays} - downgrading to Correction",
                    details
                )

            # Stay in pressure
            return (
                MarketPhase.UPTREND_PRESSURE,
                f"Uptrend under pressure - {max_ddays} D-days",
                details
            )

        # === CONFIRMED_UPTREND STATE ===
        if current == MarketPhase.CONFIRMED_UPTREND:
            # Check for pressure
            if max_ddays >= t['pressure_min_ddays']:
                return (
                    MarketPhase.UPTREND_PRESSURE,
                    f"D-days reached {max_ddays} - downgrading to Uptrend Under Pressure",
                    details
                )

            # Stay confirmed
            return (
                MarketPhase.CONFIRMED_UPTREND,
                f"Confirmed uptrend - {max_ddays} D-days",
                details
            )

        # Default fallback
        logger.warning(f"Unhandled phase state: {current}")
        return (MarketPhase.CORRECTION, "Unknown state - defaulting to Correction", details)

    def _get_change_type(
        self,
        old_phase: MarketPhase,
        new_phase: MarketPhase
    ) -> PhaseChangeType:
        """Determine if transition is upgrade, downgrade, or lateral."""
        if old_phase == new_phase:
            return PhaseChangeType.NONE

        old_order = self.PHASE_ORDER.get(old_phase, 0)
        new_order = self.PHASE_ORDER.get(new_phase, 0)

        if new_order > old_order:
            return PhaseChangeType.UPGRADE
        elif new_order < old_order:
            return PhaseChangeType.DOWNGRADE
        else:
            return PhaseChangeType.LATERAL

    def _record_phase_change(
        self,
        transition: PhaseTransition,
        dist_data: Any,
        ftd_data: Any,
        change_date: date
    ):
        """Record phase change to history table."""
        spy_count = getattr(dist_data, 'spy_count', 0) if dist_data else 0
        qqq_count = getattr(dist_data, 'qqq_count', 0) if dist_data else 0
        spy_expired = getattr(dist_data, 'spy_expired_today', 0) if dist_data else 0
        qqq_expired = getattr(dist_data, 'qqq_expired_today', 0) if dist_data else 0

        ftd_active = False
        ftd_gain = None
        if ftd_data:
            ftd_active = getattr(ftd_data, 'has_confirmed_ftd', False)
            ftd_gain = transition.trigger_details.get('ftd_gain_pct')

        history = MarketPhaseHistory(
            phase_date=change_date,
            previous_phase=transition.previous_phase.value,
            new_phase=transition.current_phase.value,
            change_type=transition.change_type.value,
            trigger_reason=transition.trigger_reason,
            spy_dday_count=spy_count,
            qqq_dday_count=qqq_count,
            total_dday_count=spy_count + qqq_count,
            ftd_active=ftd_active,
            rally_day=transition.trigger_details.get('rally_day', 0),
            spy_expired_today=spy_expired,
            qqq_expired_today=qqq_expired,
            ftd_gain_pct=ftd_gain
        )

        self.db.add(history)
        self.db.commit()

        logger.info(f"Recorded phase change: {history}")

    def get_phase_history(
        self,
        days: int = 30,
        end_date: date = None
    ) -> List[MarketPhaseHistory]:
        """Get recent phase change history."""
        end = end_date or date.today()
        start = end - timedelta(days=days)

        return self.db.query(MarketPhaseHistory).filter(
            MarketPhaseHistory.phase_date >= start,
            MarketPhaseHistory.phase_date <= end
        ).order_by(desc(MarketPhaseHistory.phase_date)).all()

    def get_days_in_current_phase(self) -> int:
        """Get number of days in current phase."""
        if self._phase_start_date:
            return (date.today() - self._phase_start_date).days
        return 0

    def force_phase(
        self,
        new_phase: MarketPhase,
        reason: str,
        dist_data: Any = None
    ) -> PhaseTransition:
        """
        Force a phase change (for manual overrides).

        Use sparingly - primarily for alignment with official IBD status.
        """
        previous = self.current_phase

        transition = PhaseTransition(
            previous_phase=previous,
            current_phase=new_phase,
            phase_changed=True,
            change_type=self._get_change_type(previous, new_phase),
            trigger_reason=f"MANUAL OVERRIDE: {reason}"
        )

        self._record_phase_change(transition, dist_data, None, date.today())
        self._current_phase = new_phase
        self._phase_start_date = date.today()

        logger.warning(f"FORCED PHASE CHANGE: {previous.value} -> {new_phase.value} ({reason})")

        return transition

    def check_ftd_from_pressure(
        self,
        ftd_data: Any
    ) -> Optional[PhaseTransition]:
        """
        Check for FTD that can upgrade from UPTREND_UNDER_PRESSURE.

        IBD allows FTD to occur even during UPTREND_PRESSURE, bringing
        the market back to CONFIRMED_UPTREND without needing a correction first.
        """
        if self.current_phase != MarketPhase.UPTREND_PRESSURE:
            return None

        ftd_today = getattr(ftd_data, 'any_ftd_today', False) or \
                   getattr(ftd_data, 'ftd_today', False)

        if ftd_today:
            ftd_gain = getattr(ftd_data, 'ftd_gain_pct', None)

            transition = PhaseTransition(
                previous_phase=MarketPhase.UPTREND_PRESSURE,
                current_phase=MarketPhase.CONFIRMED_UPTREND,
                phase_changed=True,
                change_type=PhaseChangeType.UPGRADE,
                trigger_reason="FTD from Uptrend Under Pressure - upgrading to Confirmed",
                trigger_details={'ftd_gain_pct': ftd_gain, 'from_pressure': True}
            )

            self._record_phase_change(transition, None, ftd_data, date.today())
            self._current_phase = MarketPhase.CONFIRMED_UPTREND
            self._phase_start_date = date.today()

            logger.info("FTD detected from UPTREND_PRESSURE - upgrading to CONFIRMED_UPTREND")
            return transition

        return None

    def get_phase_summary(self) -> Dict[str, Any]:
        """Get current phase summary for display."""
        return {
            'current_phase': self.current_phase.value,
            'phase_start_date': self._phase_start_date,
            'days_in_phase': self.get_days_in_current_phase(),
            'phase_order': self.PHASE_ORDER.get(self.current_phase, 0),
        }


# Convenience functions for standalone use
def get_phase_emoji(phase: MarketPhase) -> str:
    """Get emoji for a market phase."""
    emoji_map = {
        MarketPhase.CONFIRMED_UPTREND: '🟢',
        MarketPhase.UPTREND_PRESSURE: '🟡',
        MarketPhase.RALLY_ATTEMPT: '🟡',
        MarketPhase.CORRECTION: '🔴',
        MarketPhase.MARKET_IN_CORRECTION: '🔴'
    }
    return emoji_map.get(phase, '⚪')


def get_phase_guidance(phase: MarketPhase) -> str:
    """Get action guidance for a market phase."""
    guidance = {
        MarketPhase.CONFIRMED_UPTREND:
            "✅ Green light for new positions\n"
            "✅ Buy leading stocks at pivot points\n"
            "✅ Full position sizes appropriate\n"
            "✅ Let winners run",

        MarketPhase.UPTREND_PRESSURE:
            "⚠️ Yellow light - proceed with caution\n"
            "⚠️ Stop taking new positions\n"
            "⚠️ Tighten stops on existing holdings\n"
            "⚠️ Prepare to raise cash if conditions worsen",

        MarketPhase.RALLY_ATTEMPT:
            "📊 Rally attempt in progress\n"
            "📊 Watch for Follow-Through Day\n"
            "📊 Build watchlist of leading stocks\n"
            "📊 Do NOT buy until FTD confirms",

        MarketPhase.CORRECTION:
            "🛑 Red light - defensive mode\n"
            "🛑 No new long positions\n"
            "🛑 Honor all stop losses\n"
            "🛑 Raise cash, preserve capital\n"
            "🛑 Wait for Follow-Through Day",

        MarketPhase.MARKET_IN_CORRECTION:
            "🛑 Red light - defensive mode\n"
            "🛑 No new long positions\n"
            "🛑 Honor all stop losses\n"
            "🛑 Wait for Follow-Through Day"
    }

    return guidance.get(phase, "Monitor conditions closely")


if __name__ == '__main__':
    # Quick test
    logging.basicConfig(level=logging.INFO)

    print("MarketPhaseManager module loaded successfully")
    print(f"Phase hierarchy: {MarketPhaseManager.PHASE_ORDER}")
    print(f"Default thresholds: {MarketPhaseManager.DEFAULT_THRESHOLDS}")
