-- Daily completed-order revenue for the CEO dashboard.
--
-- REL-04 fix. The previous version joined straight onto stg_customers filtered
-- by is_active. That dimension is *historised*, so a customer can legitimately
-- hold several rows; if more than one of them is active the join fans out and
-- every matching order is counted twice. Revenue inflates with no SQL error,
-- no null and no duplicate order_id - dbt reports SUCCESS on wrong money.
--
-- The dimension is now collapsed to at most one row per customer BEFORE the
-- join, so the mart is arithmetically safe regardless of dimension quality.
--
-- Deliberately still a LEFT JOIN: orders must be counted even when the
-- customer row is missing or inactive, which is what
-- assert_revenue_reconciles_with_source pins down. The join contributes no
-- columns today; it is kept so customer attributes can be added without
-- reintroducing the fan-out.
--
-- Note this hardens the *model*, it does not hide the *data* problem:
-- assert_one_active_row_per_customer still fails when the dimension holds
-- duplicate active rows, so the upstream break is still reported.

with completed_orders as (
    select *
    from {{ ref('stg_orders') }}
    where status = 'completed'
),
active_customers as (
    select *
    from {{ ref('stg_customers') }}
    where is_active = true
),
current_customer as (
    -- One row per customer: the most recently valid active version.
    -- Ties (equal or null valid_from) resolve arbitrarily but to exactly one
    -- row, which is all the join arithmetic needs.
    select *
    from active_customers
    qualify row_number() over (
        partition by customer_id
        order by valid_from desc nulls last
    ) = 1
)
select
    o.order_date,
    count(*) as completed_order_rows,
    sum(o.amount_usd) as daily_revenue
from completed_orders o
left join current_customer c
    on o.customer_id = c.customer_id
group by 1
order by 1
