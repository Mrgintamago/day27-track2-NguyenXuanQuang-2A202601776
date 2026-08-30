-- Singular business test: reconciliation between mart and source.
--
-- The mart must not invent or lose money. Total revenue in fct_daily_revenue
-- has to equal the total of completed orders in stg_orders, and the row counts
-- must agree too.
--
-- This is the backstop that catches join fan-out *by its effect* rather than
-- by its cause: whatever new way the join breaks (duplicate active customer,
-- a second dimension added later, a bad merge), the totals stop matching.
--
-- Tolerance of 0.01 is deliberate: DOUBLE summation is not associative, so the
-- two sides differ in the last bits (~1e-11 observed). A strict equality test
-- here would be a permanent false positive.

with mart as (
    select
        sum(daily_revenue) as revenue,
        sum(completed_order_rows) as order_rows
    from {{ ref('fct_daily_revenue') }}
),
source as (
    select
        sum(amount_usd) as revenue,
        count(*) as order_rows
    from {{ ref('stg_orders') }}
    where status = 'completed'
)
select
    mart.revenue as mart_revenue,
    source.revenue as source_revenue,
    mart.order_rows as mart_order_rows,
    source.order_rows as source_order_rows
from mart
cross join source
where abs(coalesce(mart.revenue, 0) - coalesce(source.revenue, 0)) > 0.01
   or coalesce(mart.order_rows, 0) <> coalesce(source.order_rows, 0)
