-- name: demand_stats
-- Recent weekly demand per SKU and warehouse (last 8 weeks = current demand signal).
WITH recent AS (
    SELECT sku, warehouse_id, units
    FROM demand_history
    WHERE week > (SELECT MAX(week) FROM demand_history) - 8
)
SELECT
    sku,
    warehouse_id,
    AVG(units)                                   AS avg_weekly_demand,
    AVG(units * units) - AVG(units) * AVG(units) AS var_weekly_demand,
    COUNT(*)                                     AS weeks_observed
FROM recent
GROUP BY sku, warehouse_id;

-- name: network_position
-- Joins demand stats with on-hand stock and SKU attributes; Python adds safety stock and status.
SELECT
    i.sku,
    s.category,
    s.unit_cost,
    s.supplier_lead_weeks,
    i.warehouse_id,
    i.on_hand,
    d.avg_weekly_demand,
    d.var_weekly_demand
FROM inventory i
JOIN skus s          ON s.sku = i.sku
JOIN demand_stats d  ON d.sku = i.sku AND d.warehouse_id = i.warehouse_id;

-- name: status_by_warehouse
-- Rolls positions up to a warehouse view for the dashboard.
SELECT
    warehouse_id,
    SUM(CASE WHEN status = 'AT_RISK' THEN 1 ELSE 0 END) AS skus_at_risk,
    SUM(CASE WHEN status = 'EXCESS'  THEN 1 ELSE 0 END) AS skus_excess,
    ROUND(SUM(on_hand * unit_cost), 0)                  AS inventory_value,
    ROUND(AVG(days_of_supply), 1)                       AS avg_days_of_supply
FROM positions
GROUP BY warehouse_id
ORDER BY warehouse_id;
