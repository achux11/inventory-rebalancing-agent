"""Synthetic distribution network: 4 warehouses, 30 SKUs, 26 weeks of demand history.

Demand has shifted regionally in recent weeks, but inventory is still allocated by the
older demand mix, so some warehouses are overstocked while others are close to stocking out.
That imbalance is what the rebalancing agent has to fix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42
HISTORY_WEEKS = 26
HORIZON_WEEKS = 4  # held-out future demand used only for simulation

WAREHOUSES = pd.DataFrame(
    {
        "warehouse_id": ["DAL", "ATL", "CHI", "LAX"],
        "city": ["Dallas", "Atlanta", "Chicago", "Los Angeles"],
        "lat": [32.78, 33.75, 41.88, 34.05],
        "lon": [-96.80, -84.39, -87.63, -118.24],
    }
)

CATEGORIES = ["Electronics", "Home", "Apparel", "Grocery", "Health"]

# Recent regional demand shift (multiplier applied to the last 8 weeks and the future horizon)
REGIONAL_SHIFT = {"DAL": 1.35, "ATL": 0.80, "CHI": 0.75, "LAX": 1.30}


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(a)))


def build_lanes() -> pd.DataFrame:
    """Transfer lanes between every pair of warehouses with a per-unit freight cost."""
    rows = []
    w = WAREHOUSES.set_index("warehouse_id")
    for a in w.index:
        for b in w.index:
            if a == b:
                continue
            miles = _haversine_miles(w.at[a, "lat"], w.at[a, "lon"], w.at[b, "lat"], w.at[b, "lon"])
            rows.append(
                {
                    "from_wh": a,
                    "to_wh": b,
                    "miles": round(miles),
                    "cost_per_unit": round(0.40 + 0.0012 * miles, 2),  # handling + linehaul
                    "transfer_lead_weeks": 1,
                }
            )
    return pd.DataFrame(rows)


def build_network(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    skus = pd.DataFrame(
        {
            "sku": [f"SKU-{i:03d}" for i in range(1, 31)],
            "category": [CATEGORIES[i % len(CATEGORIES)] for i in range(30)],
            "unit_cost": np.round(rng.uniform(4, 180, 30), 2),
            "supplier_lead_weeks": rng.choice([3, 4], 30),
        }
    )

    # Base weekly demand per SKU-warehouse (lognormal = a few fast movers, many slow movers)
    base = rng.lognormal(mean=3.4, sigma=0.6, size=(30, 4))
    total_weeks = HISTORY_WEEKS + HORIZON_WEEKS
    week_idx = np.arange(1, total_weeks + 1)
    season = 1 + 0.12 * np.sin(2 * np.pi * week_idx / 26)

    rows = []
    for s in range(30):
        for w_i, wh in enumerate(WAREHOUSES["warehouse_id"]):
            for t, wk in enumerate(week_idx):
                shift = REGIONAL_SHIFT[wh] if wk > HISTORY_WEEKS - 8 else 1.0
                mu = base[s, w_i] * season[t] * shift
                qty = max(0, int(round(rng.normal(mu, 0.25 * mu))))
                rows.append({"sku": skus.at[s, "sku"], "warehouse_id": wh, "week": int(wk), "units": qty})
    demand = pd.DataFrame(rows)
    history = demand[demand["week"] <= HISTORY_WEEKS].reset_index(drop=True)
    future = demand[demand["week"] > HISTORY_WEEKS].reset_index(drop=True)

    # On-hand inventory: ~6.5 weeks of network supply, allocated by the OLD demand mix (weeks 1-18)
    old_mix = (
        history[history["week"] <= HISTORY_WEEKS - 8]
        .groupby(["sku", "warehouse_id"])["units"]
        .mean()
        .rename("old_avg")
        .reset_index()
    )
    old_mix["on_hand"] = np.maximum(
        0, np.round(old_mix["old_avg"] * rng.uniform(4.0, 9.0, len(old_mix)))
    ).astype(int)
    inventory = old_mix[["sku", "warehouse_id", "on_hand"]]

    return {
        "warehouses": WAREHOUSES.copy(),
        "skus": skus,
        "lanes": build_lanes(),
        "demand_history": history,
        "future_demand": future,
        "inventory": inventory,
    }
