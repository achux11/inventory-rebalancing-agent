"""Dashboard PNG, Excel report, and console summary."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
BLUE, ORANGE = "#2a78d6", "#eb6834"
SCENARIO_LABELS = {"no_action": "No action", "auto_approved_only": "Auto-approved only", "all_approved": "All approved"}


def _style(ax, title):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=10)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def days_of_supply_after(positions: pd.DataFrame, transfers: pd.DataFrame) -> pd.Series:
    pos = positions.set_index(["sku", "warehouse_id"]).copy()
    for t in transfers.itertuples():
        pos.loc[(t.sku, t.from_wh), "on_hand"] -= t.units
        pos.loc[(t.sku, t.to_wh), "on_hand"] += t.units
    pos["dos"] = pos["on_hand"] / pos["avg_weekly_demand"].clip(lower=0.1) * 7
    return pos.groupby(level="warehouse_id")["dos"].mean()


def dashboard(positions: pd.DataFrame, reviewed: pd.DataFrame, scenarios: dict, path: Path) -> None:
    approved = reviewed[reviewed["action"] != "REJECT"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), facecolor=SURFACE)
    fig.suptitle("Inventory rebalancing: 4 warehouses · 30 SKUs · next 4 weeks", x=0.06, ha="left",
                 fontsize=14, fontweight="bold", color=INK)

    # 1. Fill rate by scenario
    ax = axes[0, 0]
    names = list(scenarios)
    vals = [scenarios[n]["fill_rate"] * 100 for n in names]
    # Dots, not bars: the axis does not start at zero, and bar length would exaggerate the gap.
    labels = [SCENARIO_LABELS[n] for n in names]
    ax.plot(labels, vals, color=GRID, linewidth=2, zorder=1)
    ax.scatter(labels, vals, s=110, color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=2)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.25, f"{v:.1f}%", ha="center", fontsize=10, color=INK, fontweight="bold")
    ax.set_ylim(min(vals) - 1.5, 100.5)
    ax.set_xlim(-0.5, len(vals) - 0.5)
    _style(ax, "Fill rate (share of demand served, %)")

    # 2. Lost units by warehouse, before vs after
    ax = axes[0, 1]
    whs = sorted(positions["warehouse_id"].unique())
    before = [scenarios["no_action"]["lost_units_by_wh"].get(w, 0) for w in whs]
    after = [scenarios["all_approved"]["lost_units_by_wh"].get(w, 0) for w in whs]
    x = range(len(whs))
    ax.bar([i - 0.18 for i in x], before, width=0.34, color=ORANGE, label="No action")
    ax.bar([i + 0.18 for i in x], after, width=0.34, color=BLUE, label="All approved")
    ax.set_xticks(list(x), whs)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_2)
    _style(ax, "Units lost to stockouts, by warehouse")

    # 3. Days of supply before vs after transfers
    ax = axes[1, 0]
    dos_before = positions.groupby("warehouse_id")["days_of_supply"].mean().reindex(whs)
    dos_after = days_of_supply_after(positions, approved).reindex(whs)
    ax.bar([i - 0.18 for i in x], dos_before, width=0.34, color=ORANGE, label="Before")
    ax.bar([i + 0.18 for i in x], dos_after, width=0.34, color=BLUE, label="After transfers")
    ax.set_xticks(list(x), whs)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_2)
    _style(ax, "Average days of supply, by warehouse")

    # 4. Units moved by lane
    ax = axes[1, 1]
    lanes = approved.groupby(["from_wh", "to_wh"])["units"].sum().sort_values()
    labels = [f"{a} → {b}" for a, b in lanes.index]
    ax.barh(labels, lanes.values, color=BLUE, height=0.5)
    for i, v in enumerate(lanes.values):
        ax.text(v + 8, i, f"{int(v):,}", va="center", fontsize=9, color=INK)
    _style(ax, "Units transferred, by lane")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)

    fig.tight_layout(rect=(0.03, 0, 1, 0.95))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def excel_report(positions, wh_status, reviewed, scenarios, path: Path) -> None:
    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="1F3A5F")
    header_font = Font(color="FFFFFF", bold=True)

    def write(ws, df):
        ws.append(list(df.columns))
        for row in df.itertuples(index=False):
            ws.append(list(row))
        for c in ws[1]:
            c.fill, c.font = header_fill, header_font
        for i, col in enumerate(df.columns, 1):
            ws.column_dimensions[get_column_letter(i)].width = max(12, len(str(col)) + 2)
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "Summary"
    ws.append(["Scenario", "Fill rate", "Lost units", "Lost sales (at cost)", "Stockout weeks", "Freight cost"])
    for name, s in scenarios.items():
        ws.append([SCENARIO_LABELS[name], s["fill_rate"], s["lost_units"], s["lost_sales_value"],
                   s["stockout_weeks"], s["freight_cost"]])
    for c in ws[1]:
        c.fill, c.font = header_fill, header_font
    for r in range(2, 2 + len(scenarios)):
        ws[f"B{r}"].number_format = "0.0%"
        ws[f"D{r}"].number_format = ws[f"F{r}"].number_format = "$#,##0"
    last = 1 + len(scenarios)
    ws.append([])
    ws.append(["Lost sales avoided (all approved vs no action)", None, None, f"=D2-D{last}"])
    ws.append(["Return on freight (avoided lost sales / freight)", None, None, f"=(D2-D{last})/F{last}"])
    ws[f"D{last + 2}"].number_format = "$#,##0"
    ws[f"D{last + 3}"].number_format = '0.0"x"'
    ws.column_dimensions["A"].width = 48
    for col in "BCDEF":
        ws.column_dimensions[col].width = 18

    write(wb.create_sheet("Warehouse status"), wh_status)

    t = reviewed.copy()
    ws = wb.create_sheet("Transfer decisions")
    write(ws, t)
    # Live formula column so planners can edit units and see freight share update
    col = len(t.columns) + 1
    ws.cell(1, col, "freight_share").fill = header_fill
    ws.cell(1, col).font = header_font
    vcol = get_column_letter(list(t.columns).index("inventory_value") + 1)
    fcol = get_column_letter(list(t.columns).index("freight_cost") + 1)
    for r in range(2, len(t) + 2):
        ws.cell(r, col, f"=IFERROR({fcol}{r}/{vcol}{r},0)").number_format = "0.0%"

    write(wb.create_sheet("Network positions"), positions)
    wb.save(path)


def print_summary(results: dict, wh_status: pd.DataFrame) -> None:
    n, t, sim = results["network"], results["transfers"], results["simulation_next_4_weeks"]
    print("=" * 64)
    print(" INVENTORY REBALANCING AGENT")
    print("=" * 64)
    print(f"Network: {n['warehouses']} warehouses x {n['skus']} SKUs = {n['sku_warehouse_positions']} positions "
          f"({n['demand_rows']:,} demand rows)")
    print(f"At risk of stockout: {n['positions_at_risk']} | Excess (>8 weeks): {n['positions_excess']}\n")
    print(wh_status.to_string(index=False), "\n")
    print(f"Transfers proposed by optimizer: {t['proposed']} ({t['units_proposed']:,} units)")
    print(f"  Agent decisions -> auto-approved: {t['auto_approved']}, human review: {t['human_review']}, "
          f"rejected: {t['rejected']}")
    print(f"  Rules fired: {t['rules_fired']}\n")
    print(f"{'Scenario':<22}{'Fill rate':>10}{'Lost units':>12}{'Lost $ (cost)':>15}{'Stockout wks':>14}{'Freight $':>11}")
    for name, s in sim.items():
        print(f"{SCENARIO_LABELS[name]:<22}{s['fill_rate']:>10.1%}{s['lost_units']:>12,}"
              f"{s['lost_sales_value']:>15,.0f}{s['stockout_weeks']:>14}{s['freight_cost']:>11,.0f}")
    base, best = sim["no_action"], sim["all_approved"]
    avoided = base["lost_sales_value"] - best["lost_sales_value"]
    print(f"\nLost sales avoided: ${avoided:,.0f} for ${best['freight_cost']:,.0f} freight "
          f"({avoided / max(best['freight_cost'], 1):.1f}x return)")
    print("Outputs: outputs/dashboard.png, outputs/rebalancing_report.xlsx, outputs/transfer_decisions.csv")
