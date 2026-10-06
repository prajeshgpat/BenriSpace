"""scripts/copy_routing.py pure parts (the copy itself needs two databases)."""

from scripts import copy_routing

MB = copy_routing.MB


def test_projected_size_replaces_the_targets_routing_tables():
    # 394 MB database holding 5 MB of old routing tables, copying in 70 MB.
    assert copy_routing.projected_db_mb(394 * MB, 70 * MB, 5 * MB) == 459.0
    # An empty target gains the full size.
    assert copy_routing.projected_db_mb(300 * MB, 70 * MB, 0) == 370.0


def test_load_order_puts_hubs_before_the_rail_matrix_that_references_them():
    order = list(copy_routing.TABLES)
    assert order.index("routing_hubs") < order.index("rail_matrix")
    assert set(copy_routing.MUST_HAVE_ROWS) <= set(order)
