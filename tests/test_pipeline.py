"""Tests for the SQL metrics, inventory policy, optimizer, agent rules and simulation."""

import pandas as pd
import pytest

from rebalancer import agent, data, metrics, optimizer, simulate


@pytest.fixture(scope="module")
def net():
    return data.build_network()


@pytest.fixture(scope="module")
def positions(net):
    return metrics.network_positions(metrics.build_database(net))


def test_network_shape(net):
    assert len(net["skus"]) == 30
    assert len(net["inventory"]) == 120
    assert len(net["demand_history"]) == 120 * data.HISTORY_WEEKS
    assert len(net["lanes"]) == 12  # 4 warehouses, every ordered pair


def test_sql_stats_match_pandas(net):
    con = metrics.build_database(net)
    sql = pd.read_sql("SELECT * FROM demand_stats", con).set_index(["sku", "warehouse_id"])
    h = net["demand_history"]
    recent = h[h["week"] > h["week"].max() - 8]
    pandas_avg = recent.groupby(["sku", "warehouse_id"])["units"].mean()
    assert (sql["avg_weekly_demand"] - pandas_avg).abs().max() < 1e-9


def test_policy_ordering(positions):
    # safety stock >= 0 and reorder point < target level for every position
    assert (positions["safety_stock"] >= 0).all()
    assert (positions["reorder_point"] < positions["target_level"]).all()


def test_shifted_demand_creates_imbalance(positions):
    by_wh = positions.groupby("warehouse_id")["status"].value_counts().unstack(fill_value=0)
    # Demand moved toward DAL/LAX, so they should hold the at-risk positions
    assert by_wh.loc[["DAL", "LAX"], "AT_RISK"].sum() > by_wh.loc[["ATL", "CHI"], "AT_RISK"].sum()


def test_transfers_never_drain_a_source_below_target(net, positions):
    plan = optimizer.plan_transfers(positions, net["lanes"])
    shipped = plan.groupby(["sku", "from_wh"])["units"].sum()
    pos = positions.set_index(["sku", "warehouse_id"])
    for (sku, wh), units in shipped.items():
        assert pos.at[(sku, wh), "on_hand"] - units >= pos.at[(sku, wh), "target_level"]


def test_transfers_only_go_to_at_risk_positions(net, positions):
    plan = optimizer.plan_transfers(positions, net["lanes"])
    pos = positions.set_index(["sku", "warehouse_id"])
    assert all(pos.at[(t.sku, t.to_wh), "status"] == "AT_RISK" for t in plan.itertuples())


@pytest.mark.parametrize(
    "value,freight,miles,dos,expected",
    [
        (1000, 400, 500, 20, "REJECT"),          # freight 40% of value
        (20000, 100, 500, 20, "HUMAN_REVIEW"),   # high value
        (2000, 50, 1800, 3, "AUTO_APPROVE"),     # urgent beats long lane
        (2000, 50, 1800, 20, "HUMAN_REVIEW"),    # long lane, not urgent
        (2000, 50, 700, 20, "AUTO_APPROVE"),     # standard
    ],
)
def test_agent_decision_tree(value, freight, miles, dos, expected):
    t = pd.Series({"inventory_value": value, "freight_cost": freight, "miles": miles, "to_wh": "DAL"})
    assert agent.decide(t, dos).action == expected


def test_rebalancing_improves_service(net, positions):
    plan = agent.review_transfers(optimizer.plan_transfers(positions, net["lanes"]), positions)
    base = simulate.simulate(positions, net["future_demand"])
    best = simulate.simulate(positions, net["future_demand"], plan[plan["action"] != "REJECT"])
    assert best["fill_rate"] > base["fill_rate"]
    assert best["lost_units"] < base["lost_units"]
