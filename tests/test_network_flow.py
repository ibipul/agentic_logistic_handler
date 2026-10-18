from logistics_agent.problems.network_flow import (
    formulate_min_cost_flow,
    formulate_multi_commodity_flow,
    solve_min_cost_flow,
    solve_multi_commodity_flow,
    triage_min_cost_flow,
    triage_multi_commodity_flow,
)
from logistics_agent.samples import get_sample


def data(name):
    return get_sample(name)["data"]


def net_out(flows, node, product=None):
    return sum(f["units"] for f in flows if f["from"] == node and f.get("product") == product)


def net_in(flows, node, product=None):
    return sum(f["units"] for f in flows if f["to"] == node and f.get("product") == product)


def lane_total(flows, frm, to):
    return sum(f["units"] for f in flows if f["from"] == frm and f["to"] == to)


# ---------------------------------------------------------------- minimum-cost flow


def test_transportation_problem_as_min_cost_flow_gives_same_cost():
    t = get_sample("us_retail_basic")["data"]
    arcs = [{"from": i, "to": j, "cost": c} for i, row in t["costs"].items() for j, c in row.items()]
    result = solve_min_cost_flow(t["supplies"], t["demands"], arcs)
    assert result["status"] == "optimal"
    assert result["total_cost"] == 5700


def test_crossdock_respects_hubs_and_capacities():
    d = data("ca_crossdock")
    result = solve_min_cost_flow(**d)
    assert result["status"] == "optimal"
    assert result["total_cost"] == 2800
    flows = result["flows"]
    for hub in ("Sacramento DC", "Bakersfield DC"):
        assert abs(net_in(flows, hub) - net_out(flows, hub)) < 1e-6
    for arc in d["arcs"]:
        if arc.get("capacity") is not None:
            assert lane_total(flows, arc["from"], arc["to"]) <= arc["capacity"] + 1e-6
    for city, need in d["demands"].items():
        assert net_in(flows, city) >= need - 1e-6
    assert set(result["bottlenecks"]) == {"Redding Plant → Sacramento DC", "Fresno Plant → Bakersfield DC"}
    assert result["hub_throughput"] == {"Sacramento DC": 350, "Bakersfield DC": 400}


def test_lane_bottleneck_is_infeasible_then_triaged():
    d = data("ca_bottleneck")
    solved = solve_min_cost_flow(**d)
    assert solved["status"] == "infeasible" and solved["reason"] == "network"
    triage = triage_min_cost_flow(**d)
    assert triage["status"] == "partial"
    assert triage["short"] == [
        {"destination": "San Diego", "demand": 150, "delivered": 50, "short": 100, "served_pct": 33.3333}
    ]
    assert "Bakersfield DC → San Diego" in triage["bottlenecks"]


def test_supply_shortage_detected_before_solving():
    result = solve_min_cost_flow({"A": 10}, {"B": 15}, [{"from": "A", "to": "B", "cost": 1}])
    assert result["status"] == "infeasible" and result["reason"] == "shortage"
    assert result["solver"]["called"] is False


def test_unreachable_destination_is_named():
    arcs = [{"from": "A", "to": "Hub", "cost": 1}, {"from": "C", "to": "B", "cost": 1}]
    result = solve_min_cost_flow({"A": 10}, {"B": 5}, arcs)
    assert result["status"] == "infeasible"
    assert "B" in result["unreachable"]


def test_min_cost_flow_bad_input():
    assert solve_min_cost_flow({"A": 1}, {"B": 1}, [])["status"] == "error"
    assert solve_min_cost_flow({"A": 1}, {"B": 1}, [{"from": "A", "to": "A", "cost": 1}])["status"] == "error"
    assert solve_min_cost_flow({"A": 1}, {"B": 1}, [{"from": "A", "to": "B", "cost": -2}])["status"] == "error"
    dup = [{"from": "A", "to": "B", "cost": 1}, {"from": "A", "to": "B", "cost": 2}]
    assert solve_min_cost_flow({"A": 1}, {"B": 1}, dup)["status"] == "error"


def test_min_cost_flow_formulation():
    f = formulate_min_cost_flow(**data("ca_crossdock"))
    assert f["status"] == "ok"
    assert f["hubs"] == ["Sacramento DC", "Bakersfield DC"]
    titles = [g["title"] for g in f["model"]["groups"]]
    assert titles[0].startswith("flow balance") and titles[1].startswith("lane capacity")
    assert len(f["model"]["groups"][1]["lines"]) == 2


# ---------------------------------------------------------------- multi-product flow


def test_two_lines_share_capacity_and_respect_lane_restrictions():
    d = data("midwest_two_lines")
    result = solve_multi_commodity_flow(**d)
    assert result["status"] == "optimal"
    assert result["total_cost"] == 4600
    flows = result["flows"]
    for arc in d["arcs"]:
        assert lane_total(flows, arc["from"], arc["to"]) <= arc["capacity"] + 1e-6
    assert not any(f["product"] == "Frozen" and f["from"] == "Quincy" and f["to"] == "Carbondale" for f in flows)
    for product, needs in d["demands"].items():
        for city, need in needs.items():
            assert net_in(flows, city, product) >= need - 1e-6
    assert sum(result["cost_by_product"].values()) == 4600


def test_capacity_squeeze_is_infeasible_then_triaged():
    d = data("midwest_squeeze")
    assert solve_multi_commodity_flow(**d)["status"] == "infeasible"
    triage = triage_multi_commodity_flow(**d)
    assert triage["status"] == "partial"
    assert triage["total_shortfall"] == 100
    assert {r["destination"] for r in triage["short"]} == {"Champaign"}
    assert lane_total(triage["flows"], "Springfield Hub", "Champaign") == 150


def test_product_shortage_detected_per_product():
    supplies = {"A": {"P": 10}, "B": {"P": 50}}
    demands = {"A": {"Q": 20}, "B": {"Q": 20}}
    result = solve_multi_commodity_flow(supplies, demands, [{"from": "P", "to": "Q", "cost": 1}])
    assert result["status"] == "infeasible"
    assert [s["product"] for s in result["product_shortages"]] == ["A"]


def test_multi_formulation_lists_products():
    f = formulate_multi_commodity_flow(**data("midwest_two_lines"))
    assert f["status"] == "ok"
    assert f["products"] == ["Frozen", "Dry"]
    # 7 lanes × 2 products, minus Frozen on the dry-only lane
    assert "(13 variables)" in f["model"]["variables"]
