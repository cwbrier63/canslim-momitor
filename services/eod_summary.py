"""
CANSLIM Monitor - End-of-Day Summary Report
============================================
Generates daily summary of breakout activity with volume confirmation.

Run at market close (4:00 PM ET) via scheduler or manually:
    python -m canslim_monitor.services.eod_summary

The report includes:
- All symbols that triggered breakout alerts today
- Final closing price and volume
- Volume confirmation (IBD standard: >40% above average)
- Action recommendations for next day
"""

import logging
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import pytz

from sqlalchemy import and_
from sqlalchemy.orm import Session


@dataclass
class BreakoutSummary:
    """Summary data for a single breakout."""
    symbol: str
    alert_time: datetime
    alert_price: float
    pivot: float
    final_price: float
    final_volume: int
    avg_volume_50d: int
    volume_ratio: float  # Full day volume / 50d avg
    distance_pct: float  # Final price vs pivot
    grade: str
    score: int
    volume_confirmed: bool  # True if volume_ratio >= 1.4 (40% above avg)
    action: str  # BUY, WATCH, AVOID


class EODSummaryService:
    """
    Generates end-of-day summary reports for breakout activity.
    """
    
    # IBD Volume Confirmation Threshold: 40-50% above average
    VOLUME_CONFIRM_THRESHOLD = 1.4  # 40% above average
    
    def __init__(
        self,
        db_session_factory,
        ibkr_client=None,
        discord_notifier=None,
        logger: Optional[logging.Logger] = None
    ):
        self.db_session_factory = db_session_factory
        self.ibkr_client = ibkr_client
        self.discord_notifier = discord_notifier
        self.logger = logger or logging.getLogger('canslim.eod')
    
    def generate_report(self, report_date: date = None) -> List[BreakoutSummary]:
        """
        Generate end-of-day summary for all breakout alerts.
        
        Args:
            report_date: Date to report on (default: today)
            
        Returns:
            List of BreakoutSummary objects
        """
        if report_date is None:
            report_date = date.today()
        
        self.logger.info(f"Generating EOD summary for {report_date}")
        
        # 1. Get all breakout alerts from today
        alerts = self._get_todays_alerts(report_date)
        
        if not alerts:
            self.logger.info("No breakout alerts found for today")
            return []
        
        self.logger.info(f"Found {len(alerts)} breakout alerts to summarize")
        
        # 2. Get final prices and volumes for each symbol
        summaries = []
        unique_symbols = set(a.symbol for a in alerts)
        
        for symbol in unique_symbols:
            # Get the most recent alert for this symbol
            symbol_alerts = [a for a in alerts if a.symbol == symbol]
            latest_alert = max(symbol_alerts, key=lambda x: x.created_at)
            
            summary = self._build_summary(latest_alert, report_date)
            if summary:
                summaries.append(summary)
        
        # 3. Sort by volume confirmation (confirmed first), then by grade
        summaries.sort(key=lambda x: (not x.volume_confirmed, x.grade))
        
        return summaries
    
    def _get_todays_alerts(self, report_date: date) -> List[Any]:
        """Get all breakout alerts from the specified date."""
        from ..data.models import Alert
        
        if not self.db_session_factory:
            return []
        
        session = self.db_session_factory()
        try:
            # Get alerts from today with BREAKOUT type
            start_of_day = datetime.combine(report_date, datetime.min.time())
            end_of_day = datetime.combine(report_date, datetime.max.time())
            
            alerts = session.query(Alert).filter(
                and_(
                    Alert.alert_type == 'BREAKOUT',
                    Alert.created_at >= start_of_day,
                    Alert.created_at <= end_of_day
                )
            ).all()
            
            # Detach from session to use outside
            for alert in alerts:
                session.expunge(alert)
            
            return alerts
            
        except Exception as e:
            self.logger.error(f"Error fetching alerts: {e}")
            return []
        finally:
            session.close()
    
    def _build_summary(self, alert: Any, report_date: date) -> Optional[BreakoutSummary]:
        """Build summary for a single alert."""
        from ..data.models import Position
        
        symbol = alert.symbol
        
        # Get position data
        session = self.db_session_factory()
        try:
            position = session.query(Position).filter(
                Position.symbol == symbol
            ).first()
            
            if not position:
                return None
            
            pivot = position.pivot or 0
            avg_volume = getattr(position, 'avg_volume_50d', 0) or 500000
            
        finally:
            session.close()
        
        # Get final price/volume from IBKR (or use alert data if after hours)
        final_price = getattr(alert, 'price', 0) or 0
        final_volume = 0
        
        if self.ibkr_client:
            try:
                quote = self.ibkr_client.get_quote(symbol)
                if quote:
                    final_price = quote.get('last', final_price) or final_price
                    final_volume = quote.get('volume', 0) or 0
            except Exception as e:
                self.logger.debug(f"Could not get quote for {symbol}: {e}")
        
        # Calculate metrics
        if pivot > 0:
            distance_pct = ((final_price - pivot) / pivot) * 100
        else:
            distance_pct = 0
        
        if avg_volume > 0 and final_volume > 0:
            volume_ratio = final_volume / avg_volume
        else:
            volume_ratio = 0
        
        # Determine if volume confirmed (IBD: 40%+ above average)
        volume_confirmed = volume_ratio >= self.VOLUME_CONFIRM_THRESHOLD
        
        # Extract grade/score from alert columns
        grade = getattr(alert, 'canslim_grade', '') or ''
        score = getattr(alert, 'canslim_score', 0) or 0
        
        # Determine action recommendation
        action = self._determine_action(
            volume_confirmed=volume_confirmed,
            volume_ratio=volume_ratio,
            distance_pct=distance_pct,
            grade=grade
        )
        
        return BreakoutSummary(
            symbol=symbol,
            alert_time=alert.created_at,
            alert_price=getattr(alert, 'price', 0) or final_price,
            pivot=pivot,
            final_price=final_price,
            final_volume=final_volume,
            avg_volume_50d=avg_volume,
            volume_ratio=round(volume_ratio, 2),
            distance_pct=round(distance_pct, 1),
            grade=grade,
            score=score,
            volume_confirmed=volume_confirmed,
            action=action
        )
    
    def _determine_action(
        self,
        volume_confirmed: bool,
        volume_ratio: float,
        distance_pct: float,
        grade: str
    ) -> str:
        """Determine action recommendation based on IBD principles."""
        
        # Check if extended (>5% above pivot)
        is_extended = distance_pct > 5.0
        
        # Grade check
        good_grade = grade in ('A', 'A-', 'B+', 'B')
        
        if volume_confirmed and not is_extended and good_grade:
            return "✅ BUY"
        elif volume_confirmed and is_extended:
            return "⏸️ WAIT (extended)"
        elif not volume_confirmed and volume_ratio >= 1.0:
            return "👀 WATCH (volume weak)"
        elif volume_ratio < 0.8:
            return "⚠️ AVOID (no volume)"
        else:
            return "👀 WATCH"
    
    def format_report_text(self, summaries: List[BreakoutSummary]) -> str:
        """Format summaries as text report."""
        if not summaries:
            return "📊 **EOD BREAKOUT SUMMARY**\n\nNo breakouts triggered today."
        
        lines = [
            "📊 **END-OF-DAY BREAKOUT SUMMARY**",
            f"Date: {date.today().strftime('%A, %B %d, %Y')}",
            f"Symbols: {len(summaries)}",
            "",
            "=" * 70,
        ]
        
        # Separate confirmed vs unconfirmed
        confirmed = [s for s in summaries if s.volume_confirmed]
        unconfirmed = [s for s in summaries if not s.volume_confirmed]
        
        if confirmed:
            lines.append("")
            lines.append("✅ **VOLUME CONFIRMED** (40%+ above average)")
            lines.append("-" * 50)
            for s in confirmed:
                lines.append(self._format_summary_line(s))
        
        if unconfirmed:
            lines.append("")
            lines.append("⚠️ **VOLUME NOT CONFIRMED**")
            lines.append("-" * 50)
            for s in unconfirmed:
                lines.append(self._format_summary_line(s))
        
        lines.append("")
        lines.append("=" * 70)
        
        # Stats
        total_confirmed = len(confirmed)
        total = len(summaries)
        lines.append(f"Summary: {total_confirmed}/{total} breakouts with volume confirmation")
        
        return "\n".join(lines)
    
    def _format_summary_line(self, s: BreakoutSummary) -> str:
        """Format a single summary line."""
        vol_icon = "🟢" if s.volume_confirmed else "🔴"
        return (
            f"{s.symbol:6} | ${s.final_price:>8.2f} | "
            f"{s.distance_pct:>+5.1f}% | "
            f"{vol_icon} {s.volume_ratio:.1f}x | "
            f"Grade: {s.grade:2} | "
            f"{s.action}"
        )
    
    def format_report_table(self, summaries: List[BreakoutSummary]) -> str:
        """Format summaries as Discord-friendly table."""
        if not summaries:
            return "📊 **EOD BREAKOUT SUMMARY**\n\nNo breakouts triggered today."
        
        lines = [
            "📊 **END-OF-DAY BREAKOUT SUMMARY**",
            f"*{date.today().strftime('%A, %B %d, %Y')}*",
            "",
            "```",
            f"{'Symbol':<6} {'Price':>9} {'%Chg':>6} {'Vol':>5} {'Grade':>5} {'Action':<20}",
            "-" * 60,
        ]
        
        for s in summaries:
            vol_str = f"{s.volume_ratio:.1f}x"
            lines.append(
                f"{s.symbol:<6} ${s.final_price:>7.2f} {s.distance_pct:>+5.1f}% "
                f"{vol_str:>5} {s.grade:>5} {s.action:<20}"
            )
        
        lines.append("```")
        
        # Summary stats
        confirmed = sum(1 for s in summaries if s.volume_confirmed)
        lines.append(f"\n✅ Volume confirmed: {confirmed}/{len(summaries)}")
        
        return "\n".join(lines)
    
    def send_discord_report(self, summaries: List[BreakoutSummary]) -> bool:
        """Send the EOD report to Discord."""
        if not self.discord_notifier:
            self.logger.warning("No Discord notifier configured")
            return False
        
        report = self.format_report_table(summaries)
        
        try:
            self.discord_notifier.send_message(report, channel='market')
            self.logger.info("EOD summary sent to Discord")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send Discord report: {e}")
            return False
    
    def print_report(self, summaries: List[BreakoutSummary]):
        """Print report to console."""
        print(self.format_report_text(summaries))


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """CLI entry point for EOD summary."""
    import argparse
    
    from ..utils.config import load_config
    from ..data.database import get_database
    from ..integrations.ibkr_client_threadsafe import ThreadSafeIBKRClient
    from ..integrations.discord_notifier import DiscordNotifier
    
    parser = argparse.ArgumentParser(
        description='CANSLIM EOD Summary Report',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m canslim_monitor.services.eod_summary
    python -m canslim_monitor.services.eod_summary --discord
    python -m canslim_monitor.services.eod_summary --date 2026-01-15
        """
    )
    
    parser.add_argument(
        '--discord', '-d',
        action='store_true',
        help='Send report to Discord'
    )
    parser.add_argument(
        '--date',
        help='Report date (YYYY-MM-DD), default: today'
    )
    parser.add_argument(
        '--config', '-c',
        help='Config file path'
    )
    parser.add_argument(
        '--database',
        default='C:/Trading/canslim_positions.db',
        help='Database path'
    )
    parser.add_argument(
        '--no-ibkr',
        action='store_true',
        help='Skip IBKR connection (use stored data only)'
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    logger = logging.getLogger('canslim.eod')
    
    # Load config
    config = load_config(args.config)
    
    # Initialize database
    db = get_database(db_path=args.database)
    db.initialize()
    
    # Initialize IBKR (optional)
    ibkr_client = None
    if not args.no_ibkr:
        ibkr_config = config.get('ibkr', {})
        try:
            ibkr_client = ThreadSafeIBKRClient(
                host=ibkr_config.get('host', '127.0.0.1'),
                port=ibkr_config.get('port', 4001),
                client_id=ibkr_config.get('client_id', 30)
            )
            if not ibkr_client.connect(timeout=5):
                logger.warning("Could not connect to IBKR, using stored data")
                ibkr_client = None
        except Exception as e:
            logger.warning(f"IBKR connection failed: {e}")
            ibkr_client = None
    
    # Initialize Discord (optional)
    discord_notifier = None
    if args.discord:
        discord_config = config.get('discord', {})
        webhooks = discord_config.get('webhooks', {})
        if webhooks:
            discord_notifier = DiscordNotifier(webhooks=webhooks, logger=logger)
    
    # Parse report date
    report_date = date.today()
    if args.date:
        try:
            report_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            print(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")
            sys.exit(1)
    
    # Generate report
    service = EODSummaryService(
        db_session_factory=db.get_new_session,
        ibkr_client=ibkr_client,
        discord_notifier=discord_notifier,
        logger=logger
    )
    
    print("=" * 60)
    print("CANSLIM END-OF-DAY SUMMARY")
    print("=" * 60)
    
    summaries = service.generate_report(report_date)
    
    # Print to console
    service.print_report(summaries)
    
    # Send to Discord if requested
    if args.discord and summaries:
        service.send_discord_report(summaries)
    
    # Cleanup
    if ibkr_client:
        ibkr_client.disconnect()
    
    print("\n" + "=" * 60)


if __name__ == '__main__':
    main()
