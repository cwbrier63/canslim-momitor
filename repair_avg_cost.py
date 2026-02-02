"""
Repair Script: Fix avg_cost calculation for pyramided positions.

The bug: avg_cost was calculated incorrectly due to operator precedence:
    total_cost / (e1_shares or 0 + e2_shares or 0 + e3_shares or 0)

This evaluated as: e1_shares or (0 + e2_shares or (0 + e3_shares or 0))
So if e1_shares was truthy, it just divided by e1_shares, ignoring e2/e3.

This script recalculates avg_cost for all positions with multiple entries.
"""

import sys
import os
import importlib.util

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Import directly to avoid package __init__.py issues
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Load config for database path
import yaml
config_path = os.path.join(project_root, 'user_config.yaml')
with open(config_path, 'r') as f:
    config = yaml.safe_load(f)

db_path = config.get('database', {}).get('path', 'canslim_positions.db')
engine = create_engine(f'sqlite:///{db_path}')
Session = sessionmaker(bind=engine)

# Import Position model directly (bypass data/__init__.py)
models_path = os.path.join(project_root, 'data', 'models.py')
spec = importlib.util.spec_from_file_location("models", models_path)
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)
Position = models.Position


def repair_avg_cost():
    """Fix avg_cost for all positions with pyramided entries."""

    session = Session()

    try:
        # Get all positions (including closed ones, as they may have historical data)
        positions = session.query(Position).all()

        print(f"Checking {len(positions)} positions for avg_cost errors...")
        print("-" * 80)

        fixed_count = 0

        for pos in positions:
            # Calculate correct values
            e1_shares = pos.e1_shares or 0
            e2_shares = pos.e2_shares or 0
            e3_shares = pos.e3_shares or 0

            e1_price = pos.e1_price or 0
            e2_price = pos.e2_price or 0
            e3_price = pos.e3_price or 0

            total_bought = e1_shares + e2_shares + e3_shares
            total_cost = (e1_shares * e1_price) + (e2_shares * e2_price) + (e3_shares * e3_price)

            if total_bought <= 0 or total_cost <= 0:
                continue

            correct_avg_cost = total_cost / total_bought
            current_avg_cost = pos.avg_cost or 0

            # Check if there's a significant difference (more than $0.01)
            if abs(correct_avg_cost - current_avg_cost) > 0.01:
                print(f"\n{pos.symbol} (id={pos.id}, state={pos.state}):")
                print(f"  E1: {e1_shares} shares @ ${e1_price:.2f} = ${e1_shares * e1_price:.2f}")
                if e2_shares > 0:
                    print(f"  E2: {e2_shares} shares @ ${e2_price:.2f} = ${e2_shares * e2_price:.2f}")
                if e3_shares > 0:
                    print(f"  E3: {e3_shares} shares @ ${e3_price:.2f} = ${e3_shares * e3_price:.2f}")
                print(f"  Total: {total_bought} shares, ${total_cost:.2f} cost")
                print(f"  Current avg_cost: ${current_avg_cost:.2f}")
                print(f"  Correct avg_cost: ${correct_avg_cost:.2f}")

                # Update avg_cost
                pos.avg_cost = correct_avg_cost

                # Recalculate P&L if we have a current price
                if pos.last_price and pos.last_price > 0:
                    old_pnl = pos.current_pnl_pct
                    pos.current_pnl_pct = ((pos.last_price - correct_avg_cost) / correct_avg_cost) * 100
                    print(f"  P&L: {old_pnl:.2f}% -> {pos.current_pnl_pct:.2f}%")

                # Recalculate stop_price and targets based on new avg_cost
                # Only recalculate if they appear to be auto-calculated values
                hard_stop_pct = pos.hard_stop_pct or 7.0
                tp1_pct = pos.tp1_pct or 20.0
                tp2_pct = pos.tp2_pct or 30.0

                expected_stop = current_avg_cost * (1 - hard_stop_pct / 100)
                expected_tp1 = current_avg_cost * (1 + tp1_pct / 100)
                expected_tp2 = current_avg_cost * (1 + tp2_pct / 100)

                # If stop_price is close to the expected auto-calculated value, recalculate it
                if pos.stop_price and abs(pos.stop_price - expected_stop) < 0.10:
                    old_stop = pos.stop_price
                    pos.stop_price = correct_avg_cost * (1 - hard_stop_pct / 100)
                    print(f"  Stop: ${old_stop:.2f} -> ${pos.stop_price:.2f}")

                if pos.tp1_target and abs(pos.tp1_target - expected_tp1) < 0.10:
                    old_tp1 = pos.tp1_target
                    pos.tp1_target = correct_avg_cost * (1 + tp1_pct / 100)
                    print(f"  TP1:  ${old_tp1:.2f} -> ${pos.tp1_target:.2f}")

                if pos.tp2_target and abs(pos.tp2_target - expected_tp2) < 0.10:
                    old_tp2 = pos.tp2_target
                    pos.tp2_target = correct_avg_cost * (1 + tp2_pct / 100)
                    print(f"  TP2:  ${old_tp2:.2f} -> ${pos.tp2_target:.2f}")

                pos.needs_sheet_sync = True
                fixed_count += 1

        print("-" * 80)

        if fixed_count > 0:
            print(f"\nFound {fixed_count} positions with incorrect avg_cost.")
            confirm = input("Commit changes? (y/n): ").strip().lower()

            if confirm == 'y':
                session.commit()
                print(f"Successfully updated {fixed_count} positions.")
            else:
                session.rollback()
                print("Changes rolled back.")
        else:
            print("\nNo positions needed repair.")

    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        raise
    finally:
        session.close()


if __name__ == '__main__':
    repair_avg_cost()
