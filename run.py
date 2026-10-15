"""End-to-end run: build network -> SQL metrics -> LP rebalancing -> agent review -> simulation -> reports."""

from __future__ import annotations

import json
from pathlib import Path

from rebalancer import agent, data, metrics, optimizer, report, simulate

OUT = Path("outputs")


def main() -> dict:
    OUT.mkdir(exist_ok=True)
    net = data.build_network()
    con = metrics.build_database(net)
    positions = metrics.network_positions(con)
    wh_status = metrics.warehouse_status(con)

    proposed = optimizer.plan_transfers(positions, net["lanes"])
    reviewed = agent.review_transfers(proposed, positions)
    auto = reviewed[reviewed["action"] == "AUTO_APPROVE"]
    approved = reviewed[reviewed["action"] != "REJECT"]  # auto + planner-approved

    scenarios = {
        "no_action": simulate.simulate(positions, net["future_demand"]),
        "auto_approved_only": simulate.simulate(positions, net["future_demand"], auto),
        "all_approved": simulate.simulate(positions, net["future_demand"], approved),
    }

    status_counts = positions["status"].value_counts().to_dict()
    results = {
        "network": {
            "warehouses": len(net["warehouses"]),
            "skus": len(net["skus"]),
            "sku_warehouse_positions": len(positions),
            "demand_rows": len(net["demand_history"]),
            "positions_at_risk": int(status_counts.get("AT_RISK", 0)),
            "positions_excess": int(status_counts.get("EXCESS", 0)),
        },
        "transfers": {
            "proposed": len(reviewed),
            "units_proposed": int(reviewed["units"].sum()) if len(reviewed) else 0,
            "auto_approved": int((reviewed["action"] == "AUTO_APPROVE").sum()),
            "human_review": int((reviewed["action"] == "HUMAN_REVIEW").sum()),
            "rejected": int((reviewed["action"] == "REJECT").sum()),
            "rules_fired": reviewed["rule"].value_counts().to_dict(),
        },
        "simulation_next_4_weeks": scenarios,
    }

    positions.to_csv(OUT / "network_positions.csv", index=False)
    reviewed.to_csv(OUT / "transfer_decisions.csv", index=False)
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    report.dashboard(positions, reviewed, scenarios, OUT / "dashboard.png")
    report.excel_report(positions, wh_status, reviewed, scenarios, OUT / "rebalancing_report.xlsx")
    report.print_summary(results, wh_status)
    return results


if __name__ == "__main__":
    main()
