"""Decision-tree agent that reviews each proposed transfer before it ships.

Every decision is explainable: the agent records which rule fired and why, so a planner
can audit the run. High-value or non-urgent long-haul moves are routed to a human.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

MAX_FREIGHT_SHARE = 0.25     # freight above 25% of the goods' value -> reorder instead
HIGH_VALUE_USD = 15_000      # moves at or above this value need a planner's sign-off
URGENT_DAYS_OF_SUPPLY = 7    # destination has under a week of stock -> act now
LONG_LANE_MILES = 1_500


@dataclass
class Decision:
    action: str   # AUTO_APPROVE | HUMAN_REVIEW | REJECT
    rule: str
    reason: str


def decide(transfer: pd.Series, dest_days_of_supply: float) -> Decision:
    freight_share = transfer["freight_cost"] / max(transfer["inventory_value"], 0.01)

    if freight_share > MAX_FREIGHT_SHARE:
        return Decision("REJECT", "R1_FREIGHT_TOO_HIGH",
                        f"Freight is {freight_share:.0%} of goods value; a supplier reorder is cheaper.")
    if transfer["inventory_value"] >= HIGH_VALUE_USD:
        return Decision("HUMAN_REVIEW", "R2_HIGH_VALUE",
                        f"${transfer['inventory_value']:,.0f} of inventory; planner sign-off required.")
    if dest_days_of_supply < URGENT_DAYS_OF_SUPPLY:
        return Decision("AUTO_APPROVE", "R3_URGENT",
                        f"{transfer['to_wh']} has {dest_days_of_supply:.1f} days of supply; ship now.")
    if transfer["miles"] > LONG_LANE_MILES:
        return Decision("HUMAN_REVIEW", "R4_LONG_LANE_NOT_URGENT",
                        f"{transfer['miles']} mile lane and destination not urgent; confirm before shipping.")
    return Decision("AUTO_APPROVE", "R5_STANDARD",
                    "Low value, reasonable freight, destination below reorder point.")


def review_transfers(transfers: pd.DataFrame, positions: pd.DataFrame) -> pd.DataFrame:
    """Run the decision tree on every proposed transfer and return an audit log."""
    if transfers.empty:
        return transfers.assign(action=[], rule=[], reason=[])
    dos = positions.set_index(["sku", "warehouse_id"])["days_of_supply"]
    decisions = [decide(t, float(dos[(t["sku"], t["to_wh"])])) for _, t in transfers.iterrows()]
    out = transfers.copy()
    out["dest_days_of_supply"] = [float(dos[(t.sku, t.to_wh)]) for t in transfers.itertuples()]
    out["action"] = [d.action for d in decisions]
    out["rule"] = [d.rule for d in decisions]
    out["reason"] = [d.reason for d in decisions]
    return out
