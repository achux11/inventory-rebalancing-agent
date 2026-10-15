"""Load the network into SQLite, run SQL metrics, and classify each SKU-warehouse position."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

QUERIES_PATH = Path(__file__).with_name("queries.sql")

# Inventory policy
SERVICE_Z = 1.65          # ~95% cycle service level
REVIEW_WEEKS = 1          # positions are reviewed weekly
TARGET_EXTRA_WEEKS = 1    # cycle stock kept above the reorder point
EXCESS_WEEKS = 8          # more than 8 weeks of supply on hand = excess


def load_queries() -> dict[str, str]:
    """Split queries.sql into named statements ('-- name: x')."""
    out, name, buf = {}, None, []
    for line in QUERIES_PATH.read_text().splitlines():
        if line.startswith("-- name:"):
            if name:
                out[name] = "\n".join(buf).strip()
            name, buf = line.split(":", 1)[1].strip(), []
        else:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf).strip()
    return out


def build_database(network: dict[str, pd.DataFrame]) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    for table in ["warehouses", "skus", "lanes", "demand_history", "inventory"]:
        network[table].to_sql(table, con, index=False)
    q = load_queries()
    con.execute(f"CREATE TABLE demand_stats AS {q['demand_stats'].rstrip(';')}")
    return con


def classify(pos: pd.DataFrame) -> pd.DataFrame:
    """Add safety stock, reorder point, target level, days of supply and status."""
    pos = pos.copy()
    sigma = np.sqrt(pos["var_weekly_demand"].clip(lower=0))
    avg = pos["avg_weekly_demand"].clip(lower=0.1)
    # Protection period: stock must last until a supplier order placed now would arrive.
    protection = pos["supplier_lead_weeks"] + REVIEW_WEEKS
    pos["safety_stock"] = np.ceil(SERVICE_Z * sigma * np.sqrt(protection)).astype(int)
    pos["reorder_point"] = np.ceil(avg * protection + pos["safety_stock"]).astype(int)
    pos["target_level"] = np.ceil(pos["reorder_point"] + avg * TARGET_EXTRA_WEEKS).astype(int)
    pos["days_of_supply"] = (pos["on_hand"] / avg * 7).round(1)
    pos["status"] = np.select(
        [pos["on_hand"] < pos["reorder_point"], pos["on_hand"] > avg * EXCESS_WEEKS],
        ["AT_RISK", "EXCESS"],
        default="HEALTHY",
    )
    return pos


def network_positions(con: sqlite3.Connection) -> pd.DataFrame:
    q = load_queries()
    pos = classify(pd.read_sql(q["network_position"], con))
    pos.to_sql("positions", con, index=False, if_exists="replace")
    return pos


def warehouse_status(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql(load_queries()["status_by_warehouse"], con)
