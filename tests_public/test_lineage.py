from student_api import downstream_assets


def test_transitive_downstream_assets():
    graph = {
        "raw_orders": ["stg_orders"],
        "stg_orders": ["revenue"],
        "revenue": ["dashboard"],
    }
    assert downstream_assets(graph, "raw_orders") == ["stg_orders", "revenue", "dashboard"]


from student_api import column_downstream


def test_column_lineage_is_transitive():
    graph = {
        "raw_orders.amount": ["stg_orders.amount_usd"],
        "stg_orders.amount_usd": ["fct_daily_revenue.daily_revenue"],
        "fct_daily_revenue.daily_revenue": ["ceo_revenue_dashboard.revenue"],
    }
    assert column_downstream(graph, "raw_orders.amount") == [
        "stg_orders.amount_usd",
        "fct_daily_revenue.daily_revenue",
        "ceo_revenue_dashboard.revenue",
    ]


def test_unknown_node_returns_empty():
    assert downstream_assets({"a": ["b"]}, "nope") == []
    assert column_downstream({}, "nope.col") == []


def test_cycle_terminates_without_duplicates():
    graph = {"a": ["b"], "b": ["c"], "c": ["a", "d"], "d": []}
    result = downstream_assets(graph, "a")
    assert result == ["b", "c", "d"]
    assert len(result) == len(set(result))
