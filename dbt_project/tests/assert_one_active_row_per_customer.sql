-- Singular business test: the customer dimension must have at most ONE active
-- row per customer.
--
-- Why this is the highest-value test in the project: fct_daily_revenue joins
-- orders to active_customers on customer_id. Two active rows for the same
-- customer fan the join out, every matching order is counted twice, and
-- revenue inflates. dbt reports SUCCESS, no SQL error, no null, no duplicate
-- order_id. The CEO dashboard is simply wrong.
--
-- not_null/unique on stg_customers.customer_id cannot express this: the
-- dimension is historised, so customer_id is legitimately non-unique. What
-- must be unique is customer_id *among currently active rows*.

select
    customer_id,
    count(*) as active_row_count
from {{ ref('stg_customers') }}
where is_active = true
group by customer_id
having count(*) > 1
