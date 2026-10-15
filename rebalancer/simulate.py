"""Replay the next 4 weeks of (held-out) demand to measure what rebalancing actually changes.

Both scenarios use the same supplier policy: any position below its reorder point at week 0
orders up to its target level, arriving after the SKU's supplier lead time (3-4 weeks).
Approved transfers leave the source immediately and arrive at the destination after 1 week.
"""

from __future__ import annotations

import pandas as pd

from rebalancer.data import HISTORY_WEEKS, HORIZON_WEEKS


def simulate(positions: pd.DataFrame, future: pd.DataFrame, transfers: pd.DataFrame | None = None) -> dict:
    pos = positions.set_index(["sku", "warehouse_id"])
    stock = pos["on_hand"].astype(float).to_dict()
    inbound: dict[tuple[str, str, int], float] = {}

    # Supplier replenishment (identical in every scenario)
    for key, row in pos.iterrows():
        if row["on_hand"] < row["reorder_point"]:
            arrive = int(row["supplier_lead_weeks"])
            if arrive < HORIZON_WEEKS:
                inbound[(*key, arrive)] = inbound.get((*key, arrive), 0) + (row["target_level"] - row["on_hand"])

    freight = 0.0
    if transfers is not None and not transfers.empty:
        for t in transfers.itertuples():
            stock[(t.sku, t.from_wh)] -= t.units
            inbound[(t.sku, t.to_wh, 1)] = inbound.get((t.sku, t.to_wh, 1), 0) + t.units
            freight += t.freight_cost

    demand = future.assign(w=future["week"] - HISTORY_WEEKS - 1).set_index(["sku", "warehouse_id", "w"])["units"]
    unit_cost = pos["unit_cost"].to_dict()
    total_demand = filled = lost_value = 0.0
    stockout_weeks = 0
    lost_by_wh: dict[str, float] = {}

    for w in range(HORIZON_WEEKS):
        for key in stock:
            stock[key] += inbound.get((*key, w), 0)
            d = float(demand.get((*key, w), 0))
            sold = min(stock[key], d)
            stock[key] -= sold
            lost = d - sold
            total_demand += d
            filled += sold
            if lost > 0:
                stockout_weeks += 1
                lost_value += lost * unit_cost[key]
                lost_by_wh[key[1]] = lost_by_wh.get(key[1], 0) + lost

    return {
        "fill_rate": filled / total_demand if total_demand else 1.0,
        "lost_units": int(round(total_demand - filled)),
        "lost_sales_value": round(lost_value, 2),
        "stockout_weeks": stockout_weeks,
        "freight_cost": round(freight, 2),
        "lost_units_by_wh": {k: int(round(v)) for k, v in sorted(lost_by_wh.items())},
    }
