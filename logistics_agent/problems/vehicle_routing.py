"""Capacitated vehicle routing: a fleet of identical vehicles leaves one depot, visits every customer once,
and returns, without carrying more than a vehicle holds. Minimizes driving cost (plus an optional cost per
vehicle used).

Solved exactly as a mixed-integer model with PuLP/CBC (two-index formulation; load variables enforce the
capacity and rule out loops that skip the depot). Exact routing grows fast, so instances are capped at
MAX_CUSTOMERS customers and CBC gets a time limit.
"""

import math

import pulp

from .common import (
    EPS,
    InputError,
    banner,
    col,
    error,
    haversine_km,
    network,
    non_negative,
    not_called,
    num,
    quantities,
    run_solver,
    stat,
    table,
    to_float,
)

TYPE = "vehicle_routing"
MAX_CUSTOMERS = 15
TIME_LIMIT_SECONDS = 30


class _Data:
    def __init__(self, depot, demands, num_vehicles, vehicle_capacity, locations, distances, location_type,
                 cost_per_distance, cost_per_vehicle):
        self.depot = str(depot or "").strip()
        if not self.depot:
            raise InputError("Name the depot the vehicles start from and return to.")
        self.demand = quantities(demands, "Demand")
        self.demand.pop(self.depot, None)
        if not self.demand:
            raise InputError("No customers (demands) were given.")
        for c, v in self.demand.items():
            if v <= 0:
                raise InputError(f"Customer {c} has zero demand; leave out customers that need nothing.")
        if len(self.demand) > MAX_CUSTOMERS:
            raise InputError(
                f"{len(self.demand)} customers is more than this exact solver handles quickly (max {MAX_CUSTOMERS}). "
                "Split the area into zones or drop some customers."
            )
        self.customers = list(self.demand)
        self.nodes = [self.depot] + self.customers
        k = to_float(num_vehicles, "Number of vehicles")
        if k < 1 or k != int(k):
            raise InputError("Number of vehicles must be a whole number of at least 1.")
        self.vehicles = int(k)
        self.capacity = non_negative(vehicle_capacity, "Vehicle capacity")
        if self.capacity <= 0:
            raise InputError("Vehicle capacity must be more than zero.")
        self.cost_per_distance = non_negative(cost_per_distance, "Cost per distance")
        self.cost_per_vehicle = non_negative(cost_per_vehicle, "Cost per vehicle")
        self.location_type = location_type if location_type in ("grid", "lat_lon") else None
        if self.location_type is None:
            raise InputError('location_type must be "grid" (x, y in km) or "lat_lon" (latitude, longitude).')
        self.coords = None
        if locations:
            self.coords = {}
            for n in self.nodes:
                p = locations.get(n)
                if not isinstance(p, (list, tuple)) or len(p) != 2:
                    raise InputError(f"Location of {n} must be a pair of numbers, e.g. [3, 4].")
                self.coords[n] = (to_float(p[0], f"Location of {n}"), to_float(p[1], f"Location of {n}"))
        self.dist = self._distances(distances)

    def _distances(self, distances):
        dist = {}
        if distances:
            for i, row in distances.items():
                for j, v in (row or {}).items():
                    dist[str(i), str(j)] = non_negative(v, f"Distance {i}→{j}")
            for i in self.nodes:
                for j in self.nodes:
                    if i == j:
                        continue
                    if (i, j) not in dist:
                        if (j, i) not in dist:
                            raise InputError(f"Distance between {i} and {j} is missing.")
                        dist[i, j] = dist[j, i]  # roads assumed two-way unless both directions are given
        elif self.coords:
            for i in self.nodes:
                for j in self.nodes:
                    if i != j:
                        a, b = self.coords[i], self.coords[j]
                        d = haversine_km(a, b) if self.location_type == "lat_lon" else math.dist(a, b)
                        dist[i, j] = round(d, 2)
        else:
            raise InputError("Give either locations (coordinates) or a distances table.")
        return dist

    def arc_cost(self, i, j):
        return self.cost_per_distance * self.dist[i, j]


def _build(data: _Data, triage: bool, served_pool: list[str]):
    """served_pool: customers the model may visit (all of them, or for triage the ones that fit a vehicle)."""
    prob = pulp.LpProblem("vehicle_routing_triage" if triage else "vehicle_routing", pulp.LpMinimize)
    nodes = [data.depot] + served_pool
    idx = {n: i for i, n in enumerate(nodes)}
    x = {(i, j): pulp.LpVariable(f"x_{idx[i]}_{idx[j]}", cat=pulp.LpBinary) for i in nodes for j in nodes if i != j}
    load = {c: pulp.LpVariable(f"load_{idx[c]}", lowBound=0, upBound=data.capacity) for c in served_pool}
    visit = {c: (pulp.LpVariable(f"y_{idx[c]}", cat=pulp.LpBinary) if triage else 1) for c in served_pool}

    driving = pulp.lpSum(data.arc_cost(i, j) * v for (i, j), v in x.items())
    vehicles_used = pulp.lpSum(x[data.depot, c] for c in served_pool)
    objective = driving + data.cost_per_vehicle * vehicles_used
    if triage:
        # Each undelivered unit costs more than all the driving there could possibly be, so the solver first
        # serves as much demand as it can, and only then minimizes driving.
        penalty = 1.0 + sum(data.arc_cost(i, j) for (i, j) in x) + data.cost_per_vehicle * data.vehicles
        objective += penalty * pulp.lpSum(data.demand[c] * (1 - visit[c]) for c in served_pool)
    prob += objective

    for c in served_pool:
        prob += pulp.lpSum(x[i, c] for i in nodes if i != c) == visit[c]  # arrive once
        prob += pulp.lpSum(x[c, j] for j in nodes if j != c) == visit[c]  # leave once
        prob += load[c] >= data.demand[c] * visit[c]
    prob += vehicles_used <= data.vehicles
    prob += pulp.lpSum(x[c, data.depot] for c in served_pool) == vehicles_used
    for i in served_pool:
        for j in served_pool:
            if i != j:
                # If a vehicle drives i → j, its load after j is at least its load after i plus j's demand.
                prob += load[j] >= load[i] + data.demand[j] - data.capacity * (1 - x[i, j])
    return prob, x, visit


def _routes(data: _Data, x: dict) -> list[dict]:
    succ = {i: j for (i, j), v in x.items() if (v.value() or 0) > 0.5}
    starts = [j for (i, j), v in x.items() if i == data.depot and (v.value() or 0) > 0.5]
    routes = []
    for n, first in enumerate(starts, 1):
        stops, node = [data.depot], first
        while node != data.depot and node not in stops:
            stops.append(node)
            node = succ.get(node, data.depot)
        stops.append(data.depot)
        distance = sum(data.dist[a, b] for a, b in zip(stops, stops[1:]))
        load = sum(data.demand[s] for s in stops[1:-1])
        routes.append({
            "vehicle": f"Vehicle {n}",
            "stops": stops,
            "load": num(load),
            "capacity": num(data.capacity),
            "utilization_pct": num(100 * load / data.capacity),
            "distance": num(distance),
            "cost": num(distance * data.cost_per_distance + data.cost_per_vehicle),
        })
    return routes


def _network(data: _Data, routes=None, skipped=()):
    nodes = []
    for n in data.nodes:
        role = "depot" if n == data.depot else ("skipped" if n in skipped else "customer")
        node = {"id": n, "role": role,
                "label": n if n == data.depot else f"{n}\n{data.demand[n]:g}" + (" (skipped)" if n in skipped else "")}
        if data.coords:
            a, b = data.coords[n]
            if data.location_type == "lat_lon":
                node["lat"], node["lon"] = a, b
            else:
                node["x"], node["y"] = a, b
        nodes.append(node)
    edges = []
    for r in routes or []:
        for a, b in zip(r["stops"], r["stops"][1:]):
            edges.append({"from": a, "to": b, "used": True, "group": r["vehicle"],
                          "label": f"{r['vehicle'].replace('Vehicle ', 'V')} · {data.dist[a, b]:g}"})
    return network(nodes, edges, kind="routes")


def _route_table(routes, unit):
    return table(
        "Routes",
        [col("Vehicle"), col("Stops"), col("Load", "number"), col("Used", "pct"), col(f"Distance ({unit})", "number"),
         col("Cost", "money")],
        [[r["vehicle"], " → ".join(r["stops"]), r["load"], r["utilization_pct"], r["distance"], r["cost"]] for r in routes],
        total=["Total", None, num(sum(r["load"] for r in routes)), None, num(sum(r["distance"] for r in routes)),
               num(sum(r["cost"] for r in routes))],
    )


def _unit(data):
    return "km" if data.coords else "distance units"


def _load(depot, demands, num_vehicles, vehicle_capacity, locations, distances, location_type, cost_per_distance,
          cost_per_vehicle, stage):
    try:
        return _Data(depot, demands, num_vehicles, vehicle_capacity, locations, distances, location_type,
                     cost_per_distance, cost_per_vehicle), None
    except InputError as exc:
        return None, error(str(exc), TYPE, stage)


_ARGS = """
    Args:
        depot: Name of the place every vehicle starts from and returns to, e.g. "Warehouse".
        demands: Units each customer needs, e.g. {"Bakery": 30, "Cafe": 25}. At most 15 customers.
        num_vehicles: How many vehicles are available (all identical).
        vehicle_capacity: Units one vehicle can carry.
        locations: Coordinates of the depot and every customer, e.g. {"Warehouse": [0, 0], "Bakery": [4, 9]}.
            Give either locations or distances.
        distances: Distance table distances[from][to]. One direction is enough if roads are two-way.
        location_type: "grid" if locations are x, y in km (default), or "lat_lon" for latitude, longitude.
        cost_per_distance: Driving cost per km (or per distance unit). Default 1.
        cost_per_vehicle: Fixed cost for each vehicle that goes out. Default 0.
"""


def formulate_vehicle_routing(
    depot: str,
    demands: dict[str, float],
    num_vehicles: int,
    vehicle_capacity: float,
    locations: dict[str, list[float]] | None = None,
    distances: dict[str, dict[str, float]] | None = None,
    location_type: str = "grid",
    cost_per_distance: float = 1.0,
    cost_per_vehicle: float = 0.0,
) -> dict:
    data, err = _load(depot, demands, num_vehicles, vehicle_capacity, locations, distances, location_type,
                      cost_per_distance, cost_per_vehicle, "formulate")
    if err:
        return err
    n, total = len(data.customers), sum(data.demand.values())
    fleet = data.vehicles * data.capacity
    too_big = [c for c, v in data.demand.items() if v > data.capacity + EPS]
    banners = [banner("ok" if total <= fleet + EPS else "warn",
                      f"Total demand {total:g} · fleet capacity {data.vehicles} × {data.capacity:g} = {fleet:g}.")]
    if too_big:
        banners.append(banner("warn", "Too big for any single vehicle: " + ", ".join(too_big) + "."))
    unit = _unit(data)
    tables = [table(
        "Customers",
        [col("Customer"), col("Demand", "number")] + ([col("Location")] if data.coords else []),
        [[c, data.demand[c]] + ([f"({data.coords[c][0]:g}, {data.coords[c][1]:g})"] if data.coords else [])
         for c in data.customers],
        total=["Total", num(total)] + ([None] if data.coords else []),
    )]
    if len(data.nodes) <= 12:
        tables.append(table(
            f"Distances ({unit})",
            [col("From \\ to")] + [col(j, "number") for j in data.nodes],
            [[i] + [None if i == j else data.dist[i, j] for j in data.nodes] for i in data.nodes],
        ))
    cpd, cpv = data.cost_per_distance, data.cost_per_vehicle
    objective = f"minimize {cpd:g}·Σ distance[i→j]·x[i→j]" + (f" + {cpv:g}·(vehicles used)" if cpv else "")
    binaries = (n + 1) * n
    return {
        "status": "ok",
        "problem_type": TYPE,
        "stage": "formulate",
        "summary": f"{n} customers, {data.vehicles} vehicles × {data.capacity:g} · {binaries} yes/no route variables",
        "customers": n,
        "total_demand": num(total),
        "fleet_capacity": num(fleet),
        "too_big_for_a_vehicle": too_big,
        "model": {
            "objective": objective,
            "groups": [
                {"title": "every customer is visited exactly once",
                 "lines": [f"Σ_i x[i→{c}] = 1 and Σ_j x[{c}→j] = 1" for c in data.customers]},
                {"title": "fleet size",
                 "lines": [f"Σ_j x[{data.depot}→j] ≤ {data.vehicles}   (vehicles leaving the depot)",
                           f"Σ_i x[i→{data.depot}] = Σ_j x[{data.depot}→j]   (every vehicle comes back)"]},
                {"title": "vehicle capacity, and no loops that skip the depot",
                 "lines": [f"load[j] ≥ load[i] + demand[j] − {data.capacity:g}·(1 − x[i→j])   for every pair of customers "
                           f"({n * (n - 1)} constraints)",
                           f"demand[i] ≤ load[i] ≤ {data.capacity:g}   (load on board after visiting i)"]},
            ],
            "variables": f"x[i→j] ∈ {{0, 1}}: 1 if a vehicle drives straight from i to j ({binaries} variables); "
                         f"load[i] ≥ 0 ({n} variables)",
        },
        "display": {"banners": banners, "tables": tables, "network": _network(data)},
    }


def solve_vehicle_routing(
    depot: str,
    demands: dict[str, float],
    num_vehicles: int,
    vehicle_capacity: float,
    locations: dict[str, list[float]] | None = None,
    distances: dict[str, dict[str, float]] | None = None,
    location_type: str = "grid",
    cost_per_distance: float = 1.0,
    cost_per_vehicle: float = 0.0,
) -> dict:
    data, err = _load(depot, demands, num_vehicles, vehicle_capacity, locations, distances, location_type,
                      cost_per_distance, cost_per_vehicle, "solve")
    if err:
        return err
    base = {"problem_type": TYPE, "stage": "solve"}
    total, fleet = sum(data.demand.values()), data.vehicles * data.capacity
    too_big = [c for c, v in data.demand.items() if v > data.capacity + EPS]
    if too_big or total > fleet + EPS:
        reasons = []
        if too_big:
            reasons.append("too big for any single vehicle: " + ", ".join(f"{c} ({data.demand[c]:g})" for c in too_big))
        if total > fleet + EPS:
            reasons.append(f"total demand {total:g} is more than the fleet can carry ({fleet:g}); "
                           f"short by {num(total - fleet):g}")
        message = "Not every customer can be served: " + "; ".join(reasons) + "."
        return {**base, "status": "infeasible", "summary": message, "message": message,
                "solver": not_called("Detected from demand and fleet capacity before calling PuLP."),
                "display": {"banners": [banner("bad", "The full problem has no solution. " + message)]}}

    prob, x, _ = _build(data, triage=False, served_pool=data.customers)
    solver = run_solver(prob, time_limit=TIME_LIMIT_SECONDS)
    if not solver["has_solution"]:
        message = ("No set of routes fits: the orders can't be packed into the vehicles (or no plan was found "
                   f"within {TIME_LIMIT_SECONDS} s). Run triage to see which customers to drop.")
        return {**base, "status": "infeasible", "summary": message, "message": message, "solver": solver,
                "display": {"banners": [banner("bad", "The full problem has no solution. " + message)]}}

    routes = _routes(data, x)
    total_cost = num(sum(r["cost"] for r in routes))
    unit = _unit(data)
    banners = [] if solver["proven_optimal"] else [banner(
        "warn", f"Best plan found within the {TIME_LIMIT_SECONDS} s time limit; it may not be the cheapest possible.")]
    return {
        **base,
        "status": "optimal" if solver["proven_optimal"] else "feasible",
        "summary": f"{'optimal' if solver['proven_optimal'] else 'best found'}: {len(routes)} vehicles, "
                   f"total cost ${total_cost:,.2f}",
        "total_cost": total_cost,
        "total_distance": num(sum(r["distance"] for r in routes)),
        "vehicles_used": len(routes),
        "routes": routes,
        "proven_optimal": solver["proven_optimal"],
        "solver": solver,
        "display": {
            "banners": banners,
            "stats": [stat("Total cost", total_cost, "money"),
                      stat(f"Total distance ({unit})", num(sum(r["distance"] for r in routes))),
                      stat("Vehicles used", f"{len(routes)}/{data.vehicles}", "text"),
                      stat("Customers served", f"{len(data.customers)}/{len(data.customers)}", "text")],
            "tables": [_route_table(routes, unit)],
            "network": _network(data, routes),
        },
    }


def triage_vehicle_routing(
    depot: str,
    demands: dict[str, float],
    num_vehicles: int,
    vehicle_capacity: float,
    locations: dict[str, list[float]] | None = None,
    distances: dict[str, dict[str, float]] | None = None,
    location_type: str = "grid",
    cost_per_distance: float = 1.0,
    cost_per_vehicle: float = 0.0,
) -> dict:
    data, err = _load(depot, demands, num_vehicles, vehicle_capacity, locations, distances, location_type,
                      cost_per_distance, cost_per_vehicle, "triage")
    if err:
        return err
    base = {"problem_type": TYPE, "stage": "triage"}
    too_big = [c for c, v in data.demand.items() if v > data.capacity + EPS]
    pool = [c for c in data.customers if c not in too_big]
    if not pool:
        message = "Every order is bigger than a vehicle can carry; nothing can be delivered as one stop."
        return {**base, "status": "infeasible", "summary": message, "message": message,
                "solver": not_called("No customer fits in a vehicle."), "display": {"banners": [banner("bad", message)]}}
    prob, x, visit = _build(data, triage=True, served_pool=pool)
    solver = run_solver(prob, time_limit=TIME_LIMIT_SECONDS)
    if not solver["has_solution"]:
        message = f"The triage solver found no plan within {TIME_LIMIT_SECONDS} s (status: {solver['solver_status']})."
        return {**base, "status": "infeasible", "summary": message, "message": message, "solver": solver,
                "display": {"banners": [banner("bad", message)]}}

    routes = _routes(data, x)
    served = [c for c in pool if (visit[c].value() or 0) > 0.5]
    skipped = [c for c in data.customers if c not in served]
    total = sum(data.demand.values())
    delivered = num(sum(data.demand[c] for c in served))
    total_cost = num(sum(r["cost"] for r in routes))
    unit = _unit(data)
    message = (f"{len(skipped)} of {len(data.customers)} customers can't be served this round; "
               f"{delivered:g} of {total:g} units delivered." if skipped else "Every customer can be served; no triage needed.")
    banners = [banner("warn", "Triage: " + message)] if skipped else []
    if too_big:
        banners.append(banner("info", "Too big for any single vehicle (needs a split delivery or a bigger vehicle): "
                                      + ", ".join(too_big) + "."))
    if not solver["proven_optimal"]:
        banners.append(banner("warn", f"Best plan found within the {TIME_LIMIT_SECONDS} s time limit."))
    tables = []
    if skipped:
        tables.append(table("Customers not served", [col("Customer"), col("Demand", "number"), col("Why")],
                            [[c, data.demand[c], "bigger than a vehicle" if c in too_big else "no room left in the fleet"]
                             for c in skipped]))
    tables.append(_route_table(routes, unit))
    return {
        **base,
        "status": "partial" if skipped else "optimal",
        "summary": f"{message} Cost ${total_cost:,.2f}",
        "message": message,
        "total_cost": total_cost,
        "total_distance": num(sum(r["distance"] for r in routes)),
        "routes": routes,
        "customers_served": served,
        "customers_skipped": [{"customer": c, "demand": num(data.demand[c]), "too_big_for_a_vehicle": c in too_big}
                              for c in skipped],
        "units_delivered": delivered,
        "total_demand": num(total),
        "proven_optimal": solver["proven_optimal"],
        "solver": solver,
        "display": {
            "banners": banners,
            "stats": [stat("Total cost", total_cost, "money"), stat("Units delivered", delivered),
                      stat("Units not delivered", num(total - delivered)),
                      stat("Customers served", f"{len(served)}/{len(data.customers)}", "text")],
            "tables": tables,
            "network": _network(data, routes, skipped),
        },
    }


formulate_vehicle_routing.__doc__ = (
    "Check the data and write out a vehicle routing model: identical vehicles leave one depot, visit every\n"
    "    customer exactly once, and return, never carrying more than a vehicle holds. Does not solve.\n" + _ARGS
)
solve_vehicle_routing.__doc__ = (
    "Find the cheapest set of vehicle routes that serves every customer, with an exact mixed-integer solver\n"
    f"    (time limit {TIME_LIMIT_SECONDS} s; the result says whether the plan is proven optimal).\n\n"
    "    Returns status \"infeasible\" if demand exceeds what the fleet can carry or an order is bigger than a\n"
    "    vehicle; then call triage_vehicle_routing with the same data.\n" + _ARGS
)
triage_vehicle_routing.__doc__ = (
    "Best possible routes when the fleet can't serve everyone: deliver as many units as possible, then\n"
    "    minimize driving, and report which customers are left out and why.\n\n"
    "    Use this after solve_vehicle_routing returns \"infeasible\".\n" + _ARGS
)
