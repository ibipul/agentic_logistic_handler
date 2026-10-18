import itertools
import math

from logistics_agent.problems.vehicle_routing import (
    formulate_vehicle_routing,
    solve_vehicle_routing,
    triage_vehicle_routing,
)
from logistics_agent.samples import get_sample


def data(name):
    return get_sample(name)["data"]


def check_routes(result, d):
    visited = [s for r in result["routes"] for s in r["stops"][1:-1]]
    assert len(visited) == len(set(visited))
    for r in result["routes"]:
        assert r["stops"][0] == r["stops"][-1] == d["depot"]
        assert r["load"] <= d["vehicle_capacity"] + 1e-6
    assert len(result["routes"]) <= d["num_vehicles"]
    return set(visited)


def brute_force(depot, demands, coords, vehicles, capacity):
    """Cheapest total distance over every way to split customers into routes and order each route."""
    customers = list(demands)

    def tour(stops):
        best = math.inf
        for perm in itertools.permutations(stops):
            path = [depot, *perm, depot]
            best = min(best, sum(math.dist(coords[a], coords[b]) for a, b in zip(path, path[1:])))
        return best

    best = math.inf
    for labels in itertools.product(range(vehicles), repeat=len(customers)):
        groups = [[c for c, g in zip(customers, labels) if g == v] for v in range(vehicles)]
        if any(sum(demands[c] for c in g) > capacity for g in groups):
            continue
        best = min(best, sum(tour(g) for g in groups if g))
    return best


def test_sample_serves_everyone_within_capacity():
    d = data("city_vans")
    result = solve_vehicle_routing(**d)
    assert result["status"] == "optimal"
    assert check_routes(result, d) == set(d["demands"])
    assert abs(result["total_cost"] - d["cost_per_distance"] * result["total_distance"]) < 0.05
    assert result["proven_optimal"] is True


def test_matches_brute_force_on_small_instance():
    coords = {"D": (0, 0), "A": (2, 6), "B": (5, 1), "C": (-4, 3), "E": (-1, -5), "F": (4, -3)}
    demands = {"A": 4, "B": 3, "C": 5, "E": 4, "F": 2}
    result = solve_vehicle_routing("D", demands, 2, 10, locations={k: list(v) for k, v in coords.items()})
    assert result["status"] == "optimal"
    expected = brute_force("D", demands, coords, 2, 10)
    # The model uses distances rounded to 2 decimals, so allow a small gap.
    assert abs(result["total_distance"] - expected) < 0.05


def test_fleet_too_small_is_infeasible_then_triaged():
    d = data("city_vans_short")
    solved = solve_vehicle_routing(**d)
    assert solved["status"] == "infeasible"
    assert solved["solver"]["called"] is False
    triage = triage_vehicle_routing(**d)
    assert triage["status"] == "partial"
    served = check_routes(triage, d)
    assert served == set(triage["customers_served"])
    # 275 crates for 2 × 130 = 260 of trucks; the smallest order is 20, so the best possible is 275 − 20 = 255.
    assert triage["units_delivered"] == 255


def test_order_bigger_than_a_vehicle():
    demands = {"A": 5, "Big": 50}
    locs = {"D": [0, 0], "A": [1, 0], "Big": [0, 1]}
    solved = solve_vehicle_routing("D", demands, 2, 10, locations=locs)
    assert solved["status"] == "infeasible" and "Big" in solved["message"]
    triage = triage_vehicle_routing("D", demands, 2, 10, locations=locs)
    assert triage["customers_served"] == ["A"]
    assert triage["customers_skipped"][0]["too_big_for_a_vehicle"] is True


def test_distance_table_is_mirrored():
    dist = {"D": {"A": 3, "B": 4}, "A": {"B": 5}}
    result = solve_vehicle_routing("D", {"A": 1, "B": 1}, 1, 10, distances=dist)
    assert result["status"] == "optimal"
    assert result["total_distance"] == 12


def test_lat_lon_uses_straight_line_km():
    locs = {"Depot": [37.77, -122.42], "Oakland": [37.80, -122.27]}
    f = formulate_vehicle_routing("Depot", {"Oakland": 1}, 1, 5, locations=locs, location_type="lat_lon")
    dist = f["display"]["tables"][1]["rows"][0][2]
    assert 12 < dist < 15
    nodes = {n["id"]: n for n in f["display"]["network"]["nodes"]}
    assert nodes["Oakland"]["lat"] == 37.80


def test_vehicle_routing_bad_input():
    locs = {"D": [0, 0], "A": [1, 1]}
    assert solve_vehicle_routing("D", {"A": 1}, 0, 10, locations=locs)["status"] == "error"
    assert solve_vehicle_routing("D", {"A": 0}, 1, 10, locations=locs)["status"] == "error"
    assert solve_vehicle_routing("D", {"A": 1}, 1, 10)["status"] == "error"
    many = {f"C{i}": 1 for i in range(16)}
    assert "max 15" in solve_vehicle_routing("D", many, 1, 100, distances={})["message"]
