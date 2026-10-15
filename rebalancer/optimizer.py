"""Minimum-cost inventory rebalancing as a transportation linear program (one per SKU).

Sources = warehouses holding stock above their target level.
Sinks   = warehouses below their reorder point (AT_RISK), each needing stock up to target.
Any need that transfers cannot cover falls to a 'supplier reorder' with a high penalty cost,
so the LP always has a solution and only moves stock when a transfer is the cheaper fix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linprog

REORDER_PENALTY_PER_UNIT = 25.0  # proxy cost of an expedited supplier order / lost sale risk
MIN_TRANSFER_UNITS = 5           # ignore tiny moves that are not worth a pick-pack-ship


def plan_transfers(positions: pd.DataFrame, lanes: pd.DataFrame) -> pd.DataFrame:
    lane_cost = {(r.from_wh, r.to_wh): r.cost_per_unit for r in lanes.itertuples()}
    lane_miles = {(r.from_wh, r.to_wh): r.miles for r in lanes.itertuples()}
    plans = []

    for sku, grp in positions.groupby("sku"):
        sinks = grp[grp["status"] == "AT_RISK"]
        sources = grp[grp["on_hand"] > grp["target_level"]]
        if sinks.empty or sources.empty:
            continue

        need = (sinks["target_level"] - sinks["on_hand"]).clip(lower=0).to_numpy(float)
        supply = (sources["on_hand"] - sources["target_level"]).to_numpy(float)
        src_ids, snk_ids = list(sources["warehouse_id"]), list(sinks["warehouse_id"])
        n_s, n_k = len(src_ids), len(snk_ids)

        # Variables: x[i,j] transfers (n_s*n_k) + reorder[j] (n_k)
        c = [lane_cost[(src_ids[i], snk_ids[j])] for i in range(n_s) for j in range(n_k)]
        c += [REORDER_PENALTY_PER_UNIT] * n_k

        a_ub, b_ub = [], []
        for i in range(n_s):  # cannot ship more than the source's surplus
            row = np.zeros(n_s * n_k + n_k)
            row[i * n_k:(i + 1) * n_k] = 1
            a_ub.append(row)
            b_ub.append(supply[i])
        a_eq, b_eq = [], []
        for j in range(n_k):  # every unit of need is covered by transfers or a reorder
            row = np.zeros(n_s * n_k + n_k)
            row[[i * n_k + j for i in range(n_s)]] = 1
            row[n_s * n_k + j] = 1
            a_eq.append(row)
            b_eq.append(need[j])

        res = linprog(c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=(0, None), method="highs")
        if not res.success:
            continue

        unit_cost = float(grp["unit_cost"].iloc[0])
        for i in range(n_s):
            for j in range(n_k):
                qty = int(np.floor(res.x[i * n_k + j]))
                if qty < MIN_TRANSFER_UNITS:
                    continue
                src, dst = src_ids[i], snk_ids[j]
                plans.append(
                    {
                        "sku": sku,
                        "category": grp["category"].iloc[0],
                        "from_wh": src,
                        "to_wh": dst,
                        "units": qty,
                        "unit_cost": unit_cost,
                        "inventory_value": round(qty * unit_cost, 2),
                        "miles": lane_miles[(src, dst)],
                        "freight_cost": round(qty * lane_cost[(src, dst)], 2),
                    }
                )

    return pd.DataFrame(plans)
