"""
CANSLIM Monitor - Alert Descriptions
=====================================
Educational content for each alert type explaining IBD methodology.

Each alert type has:
- title: Short display title
- meaning: What this alert means (2-3 sentences)
- ibd_context: How it relates to IBD/O'Neil methodology
- recommended_action: What to do
- source_reference: MarketSurge webinar or textbook reference
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class AlertDescription:
    """Educational content for an alert type."""
    title: str
    meaning: str
    ibd_context: str
    recommended_action: str
    source_reference: str


# =============================================================================
# ALERT DESCRIPTIONS DATABASE
# Key: (alert_type, alert_subtype)
# =============================================================================

ALERT_DESCRIPTIONS: Dict[Tuple[str, str], AlertDescription] = {
    
    # =========================================================================
    # BREAKOUT ALERTS
    # =========================================================================
    
    ("BREAKOUT", "CONFIRMED"): AlertDescription(
        title="Valid Breakout",
        meaning="Price cleared the pivot point on volume 40%+ above the 50-day average. "
                "This confirms institutional buyers are accumulating shares.",
        ibd_context="IBD requires volume confirmation to validate breakouts. Without heavy "
                    "volume, the move lacks institutional sponsorship and is more likely to fail. "
                    "The 40% threshold separates real breakouts from false starts.",
        recommended_action="Enter initial 50% position if grade is A or B and market is in "
                          "confirmed uptrend. Set stop loss 7-8% below entry price.",
        source_reference="MarketSurge - Understanding Breakaway Gaps"
    ),
    
    ("BREAKOUT", "IN_BUY_ZONE"): AlertDescription(
        title="In Buy Zone",
        meaning="Price is above the pivot point but still within the 5% buy zone. "
                "Volume is present but below the 40% confirmation threshold.",
        ibd_context="The buy zone extends 5% above the pivot point. Beyond this, the stock "
                    "becomes extended and chasing increases risk. Buying within the zone "
                    "provides a reasonable risk/reward ratio.",
        recommended_action="Consider entry if volume is building. Monitor for volume surge "
                          "to confirm institutional interest. Set stop 7-8% below entry.",
        source_reference="MarketSurge - The Anatomy of a Healthy Chart Pattern"
    ),
    
    ("BREAKOUT", "APPROACHING"): AlertDescription(
        title="Approaching Pivot",
        meaning="Price is within 1% of the pivot point. The stock is setting up for "
                "a potential breakout. Watch for volume surge on the breakout day.",
        ibd_context="Stocks often consolidate near pivot points before breaking out. "
                    "The key is volume - it tells you whether institutions are buying. "
                    "Prepare your position size calculation in advance.",
        recommended_action="Add to active watchlist. Calculate position size based on "
                          "account risk rules. Be ready to act when volume confirms.",
        source_reference="MarketSurge - How to Find Alternative Buy Points"
    ),
    
    ("BREAKOUT", "EXTENDED"): AlertDescription(
        title="Extended - Avoid Chasing",
        meaning="Price is more than 5% above the pivot point. The stock has moved "
                "beyond the proper buy zone and chasing here significantly increases risk.",
        ibd_context="IBD warns against buying extended stocks. When you chase, your stop "
                    "loss becomes too wide (potentially 12-15% below entry), violating "
                    "proper risk management. Wait for a pullback or new base.",
        recommended_action="Do NOT buy at current levels. Wait for either a pullback to "
                          "the 21 EMA or 10-week line, or for a new base pattern to form.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("BREAKOUT", "SUPPRESSED"): AlertDescription(
        title="Market Suppressed Entry",
        meaning="A valid breakout was detected, but the market is currently in correction. "
                "New entries are discouraged until the market confirms a new uptrend.",
        ibd_context="'Don't fight the market' is a core IBD principle. Three out of four "
                    "stocks follow the general market direction. Even great stocks typically "
                    "fail when the market is in correction.",
        recommended_action="Hold off on new entries. Add to watchlist for when market "
                          "confirms a new uptrend via a follow-through day.",
        source_reference="MarketSurge - Understanding Follow-Through Days"
    ),
    
    # =========================================================================
    # STOP ALERTS
    # =========================================================================
    
    ("STOP", "HARD_STOP"): AlertDescription(
        title="Stop Loss Hit - SELL",
        meaning="Price has reached your stop loss level. This is a capital preservation "
                "signal requiring immediate action.",
        ibd_context="IBD's #1 rule: Always cut losses at 7-8%. The math is compelling - "
                    "a 7% loss requires only an 8% gain to recover, but a 50% loss requires "
                    "a 100% gain. Never let a small loss become a large one.",
        recommended_action="SELL IMMEDIATELY. No exceptions, no hoping, no averaging down. "
                          "Protect your capital. You can always re-enter later.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("STOP", "WARNING"): AlertDescription(
        title="Approaching Stop Level",
        meaning="Price is within 2% of your stop loss level. The position is under "
                "pressure and requires close monitoring.",
        ibd_context="This early warning gives you time to evaluate the situation. "
                    "Is the entire market weak? Is this stock-specific weakness? "
                    "Is there news? Prepare mentally for potential exit.",
        recommended_action="Review the position critically. Consider reducing size if "
                          "the stock is acting poorly. Have your sell order ready to execute.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("STOP", "TRAILING_STOP"): AlertDescription(
        title="Trailing Stop Hit",
        meaning="Price has pulled back 8% from its highest point after achieving "
                "a significant gain. Time to lock in profits.",
        ibd_context="After a stock rises 15%+, a trailing stop protects gains while "
                    "allowing room for the stock to run. When the trailing stop hits, "
                    "the easy money has been made.",
        recommended_action="SELL to lock in gains. The stock may recover and go higher, "
                          "but protecting profits is more important than maximizing them.",
        source_reference="MarketSurge - How to Hold a Stock for the Long Run"
    ),
    
    # =========================================================================
    # PROFIT ALERTS
    # =========================================================================
    
    ("PROFIT", "TP1"): AlertDescription(
        title="20% Profit Target Reached",
        meaning="Position has achieved a 20% gain from entry. This is the first "
                "profit-taking level per IBD methodology.",
        ibd_context="IBD suggests taking at least partial profits at 20-25% to lock in "
                    "gains. Most stocks will pull back after such a move. Taking profits "
                    "here ensures you keep some of what the market gives you.",
        recommended_action="Sell 1/3 to 1/2 of position to lock in gains. Let the "
                          "remainder run with a trailing stop. Consider 8-week hold rule eligibility.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("PROFIT", "TP2"): AlertDescription(
        title="25% Profit Target Reached",
        meaning="Position has achieved a 25% gain from entry. This is an excellent "
                "return and warrants serious profit-taking consideration.",
        ibd_context="25% is an excellent return. Only the strongest stocks continue "
                    "higher without a meaningful correction. Taking more profits here "
                    "is prudent risk management.",
        recommended_action="Sell another portion of remaining shares. Tighten stops on "
                          "the rest. Evaluate if stock qualifies for 8-week hold rule.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("PROFIT", "8_WEEK_HOLD"): AlertDescription(
        title="8-Week Hold Rule Active",
        meaning="Stock gained 20%+ within 3 weeks of breakout. Per IBD rules, hold "
                "for a minimum of 8 weeks from the breakout date.",
        ibd_context="The 8-week hold rule identifies potential big winners early. Stocks "
                    "that surge 20% in 1-3 weeks often become the best performers of "
                    "the cycle. Don't sell them prematurely.",
        recommended_action="HOLD for 8 weeks from breakout date. Ignore normal sell signals "
                          "during this period unless the stock closes below the 10-week MA "
                          "on heavy volume.",
        source_reference="MarketSurge - Using the 8-Week Hold Rule"
    ),
    
    # =========================================================================
    # PYRAMID ALERTS
    # =========================================================================
    
    ("PYRAMID", "P1_READY"): AlertDescription(
        title="Pyramid 1 Zone Ready",
        meaning="Stock is 0-5% above your entry price. This is the first add-on "
                "opportunity to build your position.",
        ibd_context="Pyramiding builds positions as stocks prove themselves. The key "
                    "principle: never average down, only average up. Add when the stock "
                    "is working, not when it's failing.",
        recommended_action="Add 25% more shares (bringing total to 75% of planned size). "
                          "Raise your stop to breakeven on the initial shares.",
        source_reference="MarketSurge - Position Sizing and Pyramiding"
    ),
    
    ("PYRAMID", "P1_EXTENDED"): AlertDescription(
        title="Pyramid 1 Zone Passed",
        meaning="Stock moved past the 5% P1 zone before you could add shares. "
                "The first pyramid opportunity has passed.",
        ibd_context="Missed pyramid opportunities are common, especially in fast-moving "
                    "stocks. It's better to miss an add point than to chase at "
                    "unfavorable prices.",
        recommended_action="Do not chase. Wait for either the P2 zone (5-10%) or a "
                          "pullback to the 21 EMA for your next add opportunity.",
        source_reference="MarketSurge - Position Sizing and Pyramiding"
    ),
    
    ("PYRAMID", "P2_READY"): AlertDescription(
        title="Pyramid 2 Zone Ready",
        meaning="Stock is 5-10% above your entry price. This is typically the final "
                "add-on opportunity to complete your full position.",
        ibd_context="P2 is usually the last add point. After this, the position should "
                    "be at full planned size. The 50/25/25 pyramid structure ensures "
                    "you have more shares at lower prices.",
        recommended_action="Add final 25% shares (completing the 50/25/25 pyramid). "
                          "Position is now at full size. Manage with trailing stops.",
        source_reference="MarketSurge - Position Sizing and Pyramiding"
    ),
    
    ("PYRAMID", "P2_EXTENDED"): AlertDescription(
        title="Pyramid 2 Zone Passed",
        meaning="Stock moved past 10% before you could complete P2. Your position "
                "remains at partial size.",
        ibd_context="When P2 is missed, ride what you have. Adding at 10%+ above entry "
                    "raises your average cost too much and increases risk if the stock "
                    "pulls back.",
        recommended_action="No action needed. Manage existing position with current share "
                          "count. Do not chase to complete position size.",
        source_reference="MarketSurge - Position Sizing and Pyramiding"
    ),
    
    ("PYRAMID", "PULLBACK"): AlertDescription(
        title="Pullback Add Opportunity",
        meaning="Stock has pulled back to the 21 EMA after an initial advance. "
                "This offers a lower-risk add point for pyramiding.",
        ibd_context="Pullbacks to the 21 EMA in strong uptrends offer excellent "
                    "risk/reward add points. The moving average acts as support, "
                    "giving you a logical stop level just below.",
        recommended_action="Add shares if stock bounces on volume. Place stop just "
                          "below the 21 EMA (1-2% buffer).",
        source_reference="MarketSurge - How to Enhance Trading with Moving Averages"
    ),
    
    # =========================================================================
    # TECHNICAL ALERTS
    # =========================================================================
    
    ("TECHNICAL", "50_MA_WARNING"): AlertDescription(
        title="Approaching 50-Day MA",
        meaning="Price is within 2% of the 50-day moving average. This is a key "
                "support level that institutions watch closely.",
        ibd_context="The 50-day MA is where institutional investors often add to "
                    "positions. A bounce here on volume is bullish. A break on "
                    "volume is a significant sell signal.",
        recommended_action="Watch for bounce with volume (bullish) or break with volume "
                          "(bearish). Prepare for potential sell if support fails.",
        source_reference="MarketSurge - How to Enhance Trading with Moving Averages"
    ),
    
    ("TECHNICAL", "50_MA_SELL"): AlertDescription(
        title="50-Day MA Broken - SELL",
        meaning="Price closed below the 50-day moving average on above-average volume. "
                "This is a significant technical sell signal.",
        ibd_context="A decisive break of the 50-day line on heavy volume indicates "
                    "institutions are selling. This often precedes further decline. "
                    "The volume confirms the move is significant.",
        recommended_action="SELL or significantly reduce position. The technical picture "
                          "has deteriorated. Re-evaluate the thesis before re-entering.",
        source_reference="MarketSurge - How to Enhance Trading with Moving Averages"
    ),
    
    ("TECHNICAL", "21_EMA_SELL"): AlertDescription(
        title="21 EMA Violation",
        meaning="Price has closed below the 21 EMA for 2+ consecutive days in a "
                "late-stage position. Short-term momentum has turned negative.",
        ibd_context="In later-stage stocks (Stage 3-4), the 21 EMA becomes critical "
                    "short-term support. Consecutive closes below it signals the "
                    "easy gains are over.",
        recommended_action="Consider selling, especially in Stage 3-4 stocks. The "
                          "stock may bounce, but risk/reward has deteriorated.",
        source_reference="MarketSurge - How to Enhance Trading with Moving Averages"
    ),
    
    ("TECHNICAL", "10_WEEK_SELL"): AlertDescription(
        title="10-Week Line Broken - Major Sell",
        meaning="Weekly close below the 10-week moving average on heavy volume. "
                "This is the most important support level for position traders.",
        ibd_context="The 10-week (50-day) line is the most watched support level. "
                    "A weekly close below it on volume is a major sell signal that "
                    "should not be ignored.",
        recommended_action="SELL position. This is a major violation that typically "
                          "precedes significant further decline. Preserve capital.",
        source_reference="MarketSurge - How to Enhance Trading with Moving Averages"
    ),
    
    ("TECHNICAL", "CLIMAX_TOP"): AlertDescription(
        title="Climax Top Warning",
        meaning="Stock shows signs of exhaustion: huge volume spike, wide price spread, "
                "potential blow-off top action. The advance may be ending.",
        ibd_context="Climax tops mark the end of advances. Paradoxically, the biggest "
                    "up day is often the last. When everyone is euphoric and volume "
                    "explodes, smart money is distributing.",
        recommended_action="SELL on climax action. Don't wait for 'one more high.' "
                          "The easy money has been made and risk is now elevated.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    # =========================================================================
    # HEALTH ALERTS
    # =========================================================================
    
    ("HEALTH", "WARNING"): AlertDescription(
        title="Health Warning",
        meaning="One or more health indicators are showing concern. The position may be "
                "under stress from technical deterioration or fundamental concerns.",
        ibd_context="Health warnings are early signals that a position needs attention. "
                    "Multiple warnings often precede larger problems. Don't ignore early "
                    "warning signs - they give you time to act before forced selling.",
        recommended_action="Review the position carefully. Check for: declining RS Rating, "
                          "approaching stop levels, deteriorating volume patterns, or "
                          "upcoming earnings. Consider reducing size if multiple warnings persist.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("HEALTH", "CRITICAL"): AlertDescription(
        title="Critical Health Warning",
        meaning="Multiple warning signs are present simultaneously. The position's "
                "health has deteriorated significantly.",
        ibd_context="When technical and fundamental factors align negatively, risk "
                    "increases substantially. Don't wait for all signals to turn red "
                    "before acting.",
        recommended_action="Review immediately. Consider exiting or significantly reducing "
                          "the position. The risk/reward has become unfavorable.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("HEALTH", "EXTENDED"): AlertDescription(
        title="Extended From Support",
        meaning="Stock is far above any meaningful support levels. If it corrects, "
                "there's significant downside before support.",
        ibd_context="Extended stocks have further to fall when they correct. The "
                    "further from support, the higher the risk. Taking partial "
                    "profits reduces exposure.",
        recommended_action="Tighten stops. Consider taking partial profits to reduce "
                          "exposure. Don't add to extended positions.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("HEALTH", "EARNINGS"): AlertDescription(
        title="Earnings Approaching",
        meaning="Earnings report is within 2 weeks. This creates binary event risk "
                "that requires a decision based on your P&L.",
        ibd_context="Earnings gaps can be dramatic in either direction. Your decision "
                    "should be based on cushion (P&L). With a loss, sell before. "
                    "With 20%+ gain, you have cushion to hold.",
        recommended_action="If P&L is negative or small: strongly consider selling before "
                          "earnings. If P&L is +20% or more: you have cushion to hold through.",
        source_reference="MarketSurge - Essential Selling Strategies"
    ),
    
    ("HEALTH", "LATE_STAGE"): AlertDescription(
        title="Late-Stage Base Warning",
        meaning="Stock is forming a Stage 3 or Stage 4 base. Success rates decrease "
                "significantly in later-stage patterns.",
        ibd_context="Stage 1-2 bases have ~70% success rates. Stage 3-4 bases drop "
                    "to ~30%. The stock has been public knowledge longer, reducing "
                    "the edge from early discovery.",
        recommended_action="Use smaller position size (half normal). Set tighter stops. "
                          "Have lower profit expectations. Consider passing entirely.",
        source_reference="MarketSurge - Base Stage Counting"
    ),
    
    # =========================================================================
    # ADD/REENTRY ALERTS
    # =========================================================================
    
    ("ADD", "PULLBACK"): AlertDescription(
        title="Pullback Add Point",
        meaning="Stock has pulled back to a key moving average after advancing. "
                "This offers a lower-risk entry or add point.",
        ibd_context="Pullbacks to moving averages in uptrends offer favorable "
                    "risk/reward. The MA provides a logical stop level, limiting "
                    "downside while maintaining upside potential.",
        recommended_action="Consider adding shares on a bounce from the MA. Set stop "
                          "just below the moving average support level.",
        source_reference="MarketSurge - How to Find Alternative Buy Points"
    ),
    
    ("ADD", "21_EMA"): AlertDescription(
        title="21 EMA Bounce",
        meaning="Stock is testing the 21 EMA and showing signs of support. "
                "This is a potential add point in a strong uptrend.",
        ibd_context="The 21 EMA is a key short-term support level. Stocks in "
                    "strong uptrends often bounce repeatedly from this level, "
                    "offering multiple add opportunities.",
        recommended_action="Add on bounce with volume confirmation. Stop just below "
                          "the 21 EMA (1-2% buffer).",
        source_reference="MarketSurge - How to Enhance Trading with Moving Averages"
    ),
    
    ("ALT_ENTRY", "MA_BOUNCE"): AlertDescription(
        title="Watchlist MA Pullback Entry",
        meaning="A watchlist stock that was EXTENDED from its pivot (>5% above) has now "
                "pulled back to a key moving average (21 EMA or 50 MA). This offers a "
                "lower-risk alternative entry point than chasing the extended breakout.",
        ibd_context="IBD teaches 'don't chase extended stocks.' But what if you missed the "
                    "breakout? The solution is to wait for a pullback to support. The 21 EMA "
                    "and 50 MA are institutional support levels where big money often adds. "
                    "The first or second test of these levels has the highest success rate. "
                    "Third test and beyond shows weakening support.",
        recommended_action="Enter on confirmed bounce (price closes above MA with volume). "
                          "Position size: Use normal 50% initial position. "
                          "Stop loss: Set 1-2% below the moving average. "
                          "Monitor: If stock fails to hold MA, exit immediately.",
        source_reference="MarketSurge - How to Find Alternative Buy Points; "
                        "MarketSurge - How to Enhance Trading with Moving Averages"
    ),

    ("ALT_ENTRY", "PIVOT_RETEST"): AlertDescription(
        title="Watchlist Pivot Retest Entry",
        meaning="A watchlist stock that broke out and extended has now pulled back to "
                "retest the original pivot point. The pivot that was resistance is now "
                "being tested as support - a classic second-chance entry.",
        ibd_context="Many successful breakouts pull back to 'kiss' the pivot goodbye. "
                    "This retest transforms resistance into support. If the pivot holds, "
                    "it confirms institutional commitment to the stock. This setup often "
                    "has better risk/reward than the original breakout because your stop "
                    "is tighter (just below the pivot).",
        recommended_action="Enter if pivot holds as support (price bounces on volume). "
                          "Position size: Use normal 50% initial position. "
                          "Stop loss: Set 1-2% below pivot level. "
                          "Target: Same as original breakout target.",
        source_reference="MarketSurge - How to Find Alternative Buy Points; "
                        "MarketSurge - The Anatomy of a Healthy Chart Pattern"
    ),
    
    # =========================================================================
    # MARKET ALERTS
    # =========================================================================
    
    ("MARKET", "CORRECTION"): AlertDescription(
        title="Market In Correction",
        meaning="The market has entered correction status. Distribution days have "
                "accumulated and/or key support has broken.",
        ibd_context="When the market is in correction, 3 of 4 stocks decline with it. "
                    "This is NOT the time to be aggressive. Preserve capital and wait "
                    "for a follow-through day.",
        recommended_action="Halt new purchases. Tighten stops on existing positions. "
                          "Raise cash. Watch for follow-through day to signal new uptrend.",
        source_reference="MarketSurge - How to Identify Market Tops"
    ),
    
    ("MARKET", "FTD"): AlertDescription(
        title="Follow-Through Day",
        meaning="A follow-through day has occurred, signaling a potential new uptrend. "
                "This is the green light to begin buying leading stocks.",
        ibd_context="Follow-through days occur on Day 4+ of a rally attempt when a "
                    "major index gains 1.5%+ on higher volume. Not all FTDs work, "
                    "but all bull markets start with one.",
        recommended_action="Begin buying leading stocks breaking out of sound bases. "
                          "Start with smaller positions until the rally proves itself.",
        source_reference="MarketSurge - Understanding Follow-Through Days"
    ),
    
    ("MARKET", "RALLY_ATTEMPT"): AlertDescription(
        title="Rally Attempt Underway",
        meaning="The market has begun a rally attempt from recent lows. A follow-through "
                "day is needed to confirm a new uptrend.",
        ibd_context="Rally attempts begin when an index closes higher after making "
                    "a new low. They fail more often than they succeed, so patience "
                    "is required.",
        recommended_action="Prepare watchlist of leading stocks in bases. Wait for "
                          "follow-through day before committing capital.",
        source_reference="MarketSurge - Understanding Follow-Through Days"
    ),
}


def get_alert_description(alert_type: str, alert_subtype: str) -> Optional[AlertDescription]:
    """
    Get the educational description for an alert type/subtype combination.
    
    Args:
        alert_type: Alert type (e.g., "BREAKOUT", "STOP")
        alert_subtype: Alert subtype (e.g., "CONFIRMED", "HARD_STOP")
    
    Returns:
        AlertDescription if found, None otherwise
    """
    key = (alert_type.upper(), alert_subtype.upper())
    return ALERT_DESCRIPTIONS.get(key)


def get_description_text(alert_type: str, alert_subtype: str) -> dict:
    """
    Get description as a dictionary for easy display.
    
    Returns dict with keys: title, meaning, ibd_context, recommended_action, source_reference
    Returns empty strings if not found.
    """
    desc = get_alert_description(alert_type, alert_subtype)
    if desc:
        return {
            'title': desc.title,
            'meaning': desc.meaning,
            'ibd_context': desc.ibd_context,
            'recommended_action': desc.recommended_action,
            'source_reference': desc.source_reference,
        }
    return {
        'title': f"{alert_type} - {alert_subtype}",
        'meaning': "No description available for this alert type.",
        'ibd_context': "",
        'recommended_action': "Review the alert details and act accordingly.",
        'source_reference': "",
    }


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ALERT DESCRIPTIONS TEST")
    print("=" * 60)
    
    # Test a few descriptions
    test_cases = [
        ("BREAKOUT", "CONFIRMED"),
        ("STOP", "HARD_STOP"),
        ("PROFIT", "TP1"),
        ("PYRAMID", "P1_READY"),
        ("TECHNICAL", "50_MA_SELL"),
        ("HEALTH", "EARNINGS"),
        ("UNKNOWN", "TEST"),  # Should return default
    ]
    
    for alert_type, subtype in test_cases:
        print(f"\n--- {alert_type} / {subtype} ---")
        desc = get_description_text(alert_type, subtype)
        print(f"Title: {desc['title']}")
        print(f"Meaning: {desc['meaning'][:80]}...")
        print(f"Action: {desc['recommended_action'][:60]}...")
    
    print(f"\n\nTotal descriptions defined: {len(ALERT_DESCRIPTIONS)}")
