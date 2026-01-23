"""
Generate Test Alerts
====================
Creates sample alerts in the database for GUI testing.
Includes full message content like the real checkers produce.

Run: python -m canslim_monitor.tests.generate_test_alerts
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from canslim_monitor.data.database import DatabaseManager
from canslim_monitor.data.models import Alert, Position


def generate_test_alerts(db_path: str = None):
    """Generate test alerts for GUI testing."""
    
    if db_path is None:
        db_path = Path(__file__).parent.parent / "canslim_monitor.db"
    
    db = DatabaseManager(str(db_path))
    session = db.get_new_session()
    
    try:
        # Get some existing positions to link alerts to
        positions = session.query(Position).filter(Position.state >= 0).limit(10).all()
        
        if not positions:
            print("No positions found. Creating alerts without position links.")
            position_map = {}
        else:
            position_map = {p.symbol: p for p in positions}
            print(f"Found {len(positions)} positions: {list(position_map.keys())}")
        
        # Define test alerts with full messages
        test_alerts = [
            # STOP alerts
            {
                'symbol': 'NVDA',
                'alert_type': 'STOP',
                'alert_subtype': 'HARD_STOP',
                'price': 131.50,
                'message': """🛑 HARD STOP TRIGGERED

Price: $131.50 (down -7.2% from entry)
Entry: $141.75 | Stop: $131.82
Position: 150 shares ($19,725)

▶ ACTION: SELL FULL POSITION
   Estimated Loss: -$1,537 (-7.2%)

This is a capital protection stop. The 7-8% loss rule is IBD's #1 rule.""",
                'action': 'SELL FULL POSITION',
                'avg_cost': 141.75,
                'pnl_pct': -7.2,
                'pivot': 139.50,
                'ma50': 135.20,
                'ma21': 138.40,
                'grade': 'B+',
                'score': 16,
                'severity': 'critical',
                'minutes_ago': 5,
            },
            {
                'symbol': 'INCY',
                'alert_type': 'STOP',
                'alert_subtype': 'WARNING',
                'price': 106.88,
                'message': """⚠️ APPROACHING STOP LOSS

Price: $106.88 (-4.6% from entry)
Entry: $112.03 | Stop: $105.36
Distance to Stop: 1.4%

▶ ACTION: WATCH CLOSELY

Position is within 2% of stop loss level. 
Prepare for potential exit if price continues lower.""",
                'action': 'WATCH CLOSELY',
                'avg_cost': 112.03,
                'pnl_pct': -4.6,
                'pivot': 110.50,
                'ma50': 108.20,
                'ma21': 109.80,
                'grade': 'B',
                'score': 14,
                'severity': 'warning',
                'minutes_ago': 15,
            },
            
            # PROFIT alerts
            {
                'symbol': 'PLTR',
                'alert_type': 'PROFIT',
                'alert_subtype': 'TP1',
                'price': 84.50,
                'message': """💰 20% PROFIT TARGET REACHED

Price: $84.50 (+21.4% from entry)
Entry: $69.60 | Target 1: $83.52

▶ ACTION: TAKE PARTIAL PROFITS
   Sell 1/3 to 1/2 of position
   Lock in gains of +$14.90/share

Consider 8-week hold rule eligibility if gain achieved within 3 weeks of breakout.""",
                'action': 'TAKE PARTIAL PROFITS',
                'avg_cost': 69.60,
                'pnl_pct': 21.4,
                'pivot': 68.50,
                'ma50': 72.30,
                'ma21': 78.90,
                'grade': 'A',
                'score': 19,
                'severity': 'profit',
                'minutes_ago': 30,
            },
            
            # PYRAMID alerts
            {
                'symbol': 'AXON',
                'alert_type': 'PYRAMID',
                'alert_subtype': 'P1_READY',
                'price': 695.20,
                'message': """📈 PYRAMID 1 ZONE ACTIVE

Price: $695.20 (+3.2% from entry)
Entry: $673.50
PY1 Zone: 0-5% above entry ($673.50 - $707.18)

▶ ACTION: ADD 25% MORE SHARES
   Current: 50% position
   Target: 75% position
   
Stock proving itself. Add on strength per IBD pyramid rules.""",
                'action': 'ADD 25% MORE SHARES',
                'avg_cost': 673.50,
                'pnl_pct': 3.2,
                'pivot': 670.00,
                'ma50': 645.80,
                'ma21': 668.30,
                'grade': 'A-',
                'score': 17,
                'severity': 'info',
                'minutes_ago': 45,
            },
            {
                'symbol': 'REVG',
                'alert_type': 'PYRAMID',
                'alert_subtype': 'P1_EXTENDED',
                'price': 67.86,
                'message': """📈 EXTENDED BEYOND PY1 ZONE

Price: $67.86 (+11.0% from entry)
Entry: $61.14
PY1 Zone: 0-5% above entry

▶ ACTION: WAIT FOR PULLBACK

Position moved past ideal add zone.
Wait for pullback to 21 EMA or continue to PY2.""",
                'action': 'WAIT FOR PULLBACK',
                'avg_cost': 61.14,
                'pnl_pct': 11.0,
                'pivot': 60.50,
                'ma50': 58.20,
                'ma21': 63.40,
                'grade': 'B+',
                'score': 15,
                'severity': 'info',
                'minutes_ago': 60,
            },
            
            # TECHNICAL alerts
            {
                'symbol': 'AMD',
                'alert_type': 'TECHNICAL',
                'alert_subtype': '50_MA_WARNING',
                'price': 119.80,
                'message': """📉 APPROACHING 50-DAY MA

Price: $119.80
50-Day MA: $118.50
Distance: 1.1%

▶ ACTION: WATCH FOR SUPPORT

Key institutional support level approaching.
Bounce = bullish, Break on volume = bearish sell signal.""",
                'action': 'WATCH FOR SUPPORT',
                'avg_cost': 125.40,
                'pnl_pct': -4.5,
                'pivot': 128.00,
                'ma50': 118.50,
                'ma21': 122.30,
                'grade': 'B',
                'score': 13,
                'severity': 'warning',
                'minutes_ago': 90,
            },
            {
                'symbol': 'SMCI',
                'alert_type': 'TECHNICAL',
                'alert_subtype': '50_MA_SELL',
                'price': 38.50,
                'message': """📉 50-DAY MA BROKEN - SELL SIGNAL

Price: $38.50 (closed below 50-MA)
50-Day MA: $39.80
Volume: 1.8x average

▶ ACTION: SELL OR REDUCE POSITION

Decisive break of 50-day line on heavy volume.
Institutions are selling. Technical picture has deteriorated.""",
                'action': 'SELL OR REDUCE',
                'avg_cost': 45.20,
                'pnl_pct': -14.8,
                'pivot': 48.00,
                'ma50': 39.80,
                'ma21': 41.20,
                'volume_ratio': 1.8,
                'grade': 'C',
                'score': 9,
                'severity': 'critical',
                'minutes_ago': 120,
            },
            
            # HEALTH alerts
            {
                'symbol': 'MSTR',
                'alert_type': 'HEALTH',
                'alert_subtype': 'WARNING',
                'price': 395.00,
                'message': """⚠️ HEALTH WARNING

Multiple factors showing concern:
- RS Rating declined from 95 to 88
- Volume drying up (0.6x average)
- Approaching 50-day MA

▶ ACTION: REVIEW POSITION

Position health has deteriorated.
Consider reducing size if warnings persist.""",
                'action': 'REVIEW POSITION',
                'avg_cost': 380.00,
                'pnl_pct': 3.9,
                'pivot': 375.00,
                'ma50': 390.00,
                'ma21': 398.00,
                'volume_ratio': 0.6,
                'health_score': 65,
                'health_rating': 'CAUTION',
                'grade': 'B',
                'score': 14,
                'severity': 'warning',
                'minutes_ago': 180,
            },
            {
                'symbol': 'COIN',
                'alert_type': 'HEALTH',
                'alert_subtype': 'EARNINGS',
                'price': 268.50,
                'message': """📅 EARNINGS APPROACHING

Earnings Date: Jan 25, 2026
Days Until: 8 days
Current P&L: +12.5%

▶ ACTION: DECIDE HOLD OR SELL

With +12.5% cushion, you have buffer to hold through earnings.
If P&L were negative, selling before would be prudent.""",
                'action': 'DECIDE: HOLD OR SELL',
                'avg_cost': 238.70,
                'pnl_pct': 12.5,
                'pivot': 235.00,
                'ma50': 245.80,
                'ma21': 258.30,
                'grade': 'A-',
                'score': 16,
                'severity': 'warning',
                'minutes_ago': 240,
            },
            
            # BREAKOUT alerts
            {
                'symbol': 'CRWD',
                'alert_type': 'BREAKOUT',
                'alert_subtype': 'CONFIRMED',
                'price': 425.80,
                'message': """🚀 BREAKOUT CONFIRMED

Price: $425.80 (+2.3% above pivot)
Pivot: $416.25
Volume: 1.65x average (CONFIRMED)

▶ ACTION: ENTER INITIAL POSITION
   Grade: A | Score: 18
   Suggested: 50% of planned size
   Stop: $387.11 (-7%)

Valid breakout with volume confirmation.
Market: Confirmed Uptrend""",
                'action': 'ENTER 50% POSITION',
                'avg_cost': 425.80,
                'pnl_pct': 0,
                'pivot': 416.25,
                'ma50': 395.40,
                'ma21': 408.60,
                'volume_ratio': 1.65,
                'grade': 'A',
                'score': 18,
                'market_regime': 'CONFIRMED_UPTREND',
                'severity': 'info',
                'minutes_ago': 10,
            },
            {
                'symbol': 'NOW',
                'alert_type': 'BREAKOUT',
                'alert_subtype': 'IN_BUY_ZONE',
                'price': 1125.50,
                'message': """📊 IN BUY ZONE (Unconfirmed)

Price: $1,125.50 (+1.8% above pivot)
Pivot: $1,105.00
Buy Zone: $1,105 - $1,160
Volume: 1.15x average (below 1.4x threshold)

▶ ACTION: WATCH FOR VOLUME

Price is in buy zone but volume hasn't confirmed.
Monitor for volume surge to validate breakout.""",
                'action': 'WATCH FOR VOLUME',
                'avg_cost': 1125.50,
                'pnl_pct': 0,
                'pivot': 1105.00,
                'ma50': 1065.00,
                'ma21': 1092.00,
                'volume_ratio': 1.15,
                'grade': 'A-',
                'score': 17,
                'market_regime': 'CONFIRMED_UPTREND',
                'severity': 'info',
                'minutes_ago': 20,
            },
        ]
        
        # Clear existing test alerts (optional)
        # session.query(Alert).filter(Alert.symbol.in_([a['symbol'] for a in test_alerts])).delete()
        
        created = 0
        for alert_data in test_alerts:
            # Get position ID if exists
            position = position_map.get(alert_data['symbol'])
            position_id = position.id if position else None
            
            # Calculate time
            alert_time = datetime.now() - timedelta(minutes=alert_data.get('minutes_ago', 0))
            
            alert = Alert(
                symbol=alert_data['symbol'],
                position_id=position_id,
                alert_time=alert_time,
                alert_type=alert_data['alert_type'],
                alert_subtype=alert_data['alert_subtype'],
                price=alert_data['price'],
                message=alert_data['message'],
                action=alert_data['action'],
                avg_cost_at_alert=alert_data.get('avg_cost'),
                pnl_pct_at_alert=alert_data.get('pnl_pct'),
                pivot_at_alert=alert_data.get('pivot'),
                ma50=alert_data.get('ma50'),
                ma21=alert_data.get('ma21'),
                volume_ratio=alert_data.get('volume_ratio', 1.0),
                health_score=alert_data.get('health_score', 100),
                health_rating=alert_data.get('health_rating', 'HEALTHY'),
                canslim_grade=alert_data.get('grade'),
                canslim_score=alert_data.get('score'),
                market_regime=alert_data.get('market_regime', 'CONFIRMED_UPTREND'),
                acknowledged=False,
            )
            
            session.add(alert)
            created += 1
            print(f"  Created: {alert_data['symbol']} - {alert_data['alert_type']}/{alert_data['alert_subtype']}")
        
        session.commit()
        print(f"\n✅ Created {created} test alerts")
        
        # Show summary
        print("\nAlert Summary:")
        for alert_type in ['BREAKOUT', 'STOP', 'PROFIT', 'PYRAMID', 'TECHNICAL', 'HEALTH']:
            count = session.query(Alert).filter(
                Alert.alert_type == alert_type,
                Alert.alert_time >= datetime.now() - timedelta(hours=24)
            ).count()
            print(f"  {alert_type}: {count}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return False
        
    finally:
        session.close()


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = generate_test_alerts(db_path)
    sys.exit(0 if success else 1)
