from logistics_agent.scenarios import get_scenario
from logistics_agent.tools import (
    formulate_transportation_problem,
    list_sample_scenarios,
    load_sample_scenario,
    solve_transportation_problem,
    solve_with_shortage_triage,
)


def data(name):
    sc = get_scenario(name)
    return sc["supplies"], sc["demands"], sc["costs"]


def plan(result):
    return {(sh["from"], sh["to"], sh["units"]) for sh in result["shipments"]}


def assert_feasible(result, supplies, demands):
    for i, supply in supplies.items():
        assert sum(sh["units"] for sh in result["shipments"] if sh["from"] == i) <= supply + 1e-6
    for j, demand in demands.items():
        assert sum(sh["units"] for sh in result["shipments"] if sh["to"] == j) >= demand - 1e-6


def test_basic_optimal():
    s, d, c = data("us_retail_basic")
    result = solve_transportation_problem(s, d, c)
    assert result["status"] == "optimal"
    assert result["total_cost"] == 5700
    assert plan(result) == {
        ("Dallas", "Houston", 300),
        ("Atlanta", "Miami", 400),
        ("Denver", "Phoenix", 250),
        ("Denver", "Houston", 50),
        ("Denver", "Chicago", 200),
    }


def test_closed_route():
    s, d, c = data("us_retail_basic")
    del c["Atlanta"]["Miami"]
    result = solve_transportation_problem(s, d, c)
    assert result["status"] == "optimal"
    assert result["total_cost"] == 8700
    assert_feasible(result, s, d)
    assert ("Atlanta", "Miami") not in {(f, t) for f, t, _ in plan(result)}


def test_surplus():
    s, d, c = data("us_retail_surplus")
    result = solve_transportation_problem(s, d, c)
    assert result["status"] == "optimal"
    assert sum(result["unused_supply"].values()) == 200
    assert_feasible(result, s, d)


def test_shortage_is_infeasible():
    s, d, c = data("us_retail_shortage")
    result = solve_transportation_problem(s, d, c)
    assert result["status"] == "infeasible"
    assert result["shortfall"] == 200
    assert "200" in result["message"]


def test_shortage_triage_delivers_all_supply():
    s, d, c = data("us_retail_shortage")
    result = solve_with_shortage_triage(s, d, c)
    assert result["status"] == "partial"
    assert result["units_delivered"] == 1000
    assert result["total_shortfall"] == 200
    assert sum(st["short"] for st in result["stores_short"]) == 200
    assert len(result["stores_short"]) + len(result["stores_fully_served"]) == len(d)
    for i, supply in s.items():
        assert sum(sh["units"] for sh in result["shipments"] if sh["from"] == i) <= supply + 1e-6
    for j, demand in d.items():
        assert sum(sh["units"] for sh in result["shipments"] if sh["to"] == j) <= demand + 1e-6


def test_triage_on_balanced_problem_matches_plain_solve():
    s, d, c = data("us_retail_basic")
    result = solve_with_shortage_triage(s, d, c)
    assert result["status"] == "optimal"
    assert result["total_cost"] == 5700
    assert result["stores_short"] == []


def test_triage_prefers_delivering_over_saving_cost():
    # B can only be reached by an expensive route; triage must still use it rather than leave B short.
    result = solve_with_shortage_triage({"W": 10}, {"A": 5, "B": 10}, {"W": {"A": 1, "B": 100}})
    assert result["units_delivered"] == 10
    assert result["total_shortfall"] == 5


def test_bad_input():
    s, d, c = data("us_retail_basic")
    c["Dallas"]["Phoenix"] = -1
    assert solve_transportation_problem(s, d, c)["status"] == "error"
    s, d, c = data("us_retail_basic")
    c["Dallas"]["Atlantis"] = 3
    assert solve_transportation_problem(s, d, c)["status"] == "error"
    assert solve_transportation_problem({"A": "ten"}, {"B": 1}, {"A": {"B": 1}})["status"] == "error"


def test_store_with_no_route():
    result = solve_transportation_problem({"A": 10}, {"B": 5, "C": 5}, {"A": {"B": 1}})
    assert result["status"] == "error"
    assert "C" in result["message"]


def test_names_with_spaces_and_string_numbers():
    result = solve_transportation_problem(
        {"New York": "100", "St. Louis (MO)": 50}, {"San José": 120}, {"New York": {"San José": 2}, "St. Louis (MO)": {"San José": "1"}}
    )
    assert result["status"] == "optimal"
    assert result["total_cost"] == 50 * 1 + 70 * 2


def test_formulation():
    s, d, c = data("us_retail_shortage")
    f = formulate_transportation_problem(s, d, c)
    assert f["status"] == "ok"
    assert len(f["variables"]) == 12
    assert len(f["supply_constraints"]) == 3 and len(f["demand_constraints"]) == 4
    assert f["balance"] == "shortage"


def test_scenario_tools():
    names = {sc["name"] for sc in list_sample_scenarios()["scenarios"]}
    assert {"us_retail_basic", "us_retail_surplus", "us_retail_shortage"} <= names
    assert load_sample_scenario("us_retail_basic")["supplies"]["Denver"] == 500
    assert load_sample_scenario("nope")["status"] == "error"
