"""Tools the agent can call. Plain Python with no ADK imports, so they can be unit-tested directly.

ADK reads each function's name, type hints and docstring to describe the tool to the model.
"""

import pulp

from .scenarios import SCENARIOS, get_scenario

_EPS = 1e-6


def _num(value) -> float:
    return round(float(value), 4)


def _clean(supplies, demands, costs):
    """Validate input and cast numbers to float. Returns (supplies, demands, costs, None) or (.., error_dict)."""

    def error(message):
        return None, None, None, {"status": "error", "message": message}

    if not supplies:
        return error("No warehouses (supplies) were given.")
    if not demands:
        return error("No stores (demands) were given.")
    try:
        s = {str(k): float(v) for k, v in supplies.items()}
        d = {str(k): float(v) for k, v in demands.items()}
        c = {str(i): {str(j): float(v) for j, v in row.items()} for i, row in (costs or {}).items()}
    except (TypeError, ValueError, AttributeError) as exc:
        return error(f"Every supply, demand and cost must be a number ({exc}).")

    for name, value in s.items():
        if value < 0:
            return error(f"Supply at {name} is negative ({value}).")
    for name, value in d.items():
        if value < 0:
            return error(f"Demand at {name} is negative ({value}).")
    for i, row in c.items():
        if i not in s:
            return error(f"The cost table has a route from {i}, which is not in the list of warehouses.")
        for j, value in row.items():
            if j not in d:
                return error(f"The cost table has a route to {j}, which is not in the list of stores.")
            if value < 0:
                return error(f"Cost from {i} to {j} is negative ({value}).")
    for j, demand in d.items():
        if demand > 0 and not any(j in row for row in c.values()):
            return error(f"Store {j} has no incoming route, so it cannot be supplied.")
    return s, d, c, None


def _routes(costs):
    return [(i, j, cost) for i, row in costs.items() for j, cost in row.items()]


def _shipments(routes, variables):
    shipments = []
    for idx, (i, j, cost) in enumerate(routes):
        units = variables[idx].value() or 0.0
        if units > _EPS:
            shipments.append(
                {"from": i, "to": j, "units": _num(units), "unit_cost": _num(cost), "route_cost": _num(units * cost)}
            )
    return shipments


def list_sample_scenarios() -> dict:
    """List the built-in sample shipping scenarios (name and one-line description)."""
    return {"scenarios": [{"name": n, "description": s["description"]} for n, s in SCENARIOS.items()]}


def load_sample_scenario(name: str) -> dict:
    """Load one sample scenario by name. Returns its supplies, demands and per-unit route costs.

    Args:
        name: Scenario name from list_sample_scenarios, e.g. "us_retail_basic".
    """
    scenario = get_scenario(name)
    if scenario is None:
        return {"status": "error", "message": f"Unknown scenario {name!r}. Known: {', '.join(SCENARIOS)}."}
    return {"status": "ok", "name": name, **scenario}


def formulate_transportation_problem(
    supplies: dict[str, float], demands: dict[str, float], costs: dict[str, dict[str, float]]
) -> dict:
    """Check the data and write it out as a transportation problem (variables, objective, constraints).

    Call this before solving so the user can see exactly what will be optimized. It does not solve anything.

    Args:
        supplies: Units available at each warehouse, e.g. {"Dallas": 300}.
        demands: Units needed at each store, e.g. {"Miami": 400}.
        costs: Cost per unit for each open route, costs[warehouse][store]. Leave closed routes out.
    """
    s, d, c, err = _clean(supplies, demands, costs)
    if err:
        return err
    routes = _routes(c)
    total_supply, total_demand = sum(s.values()), sum(d.values())
    if total_supply > total_demand + _EPS:
        balance = "surplus"
        note = f"Supply exceeds demand by {_num(total_supply - total_demand)} units; some stock will stay in warehouses."
    elif total_supply < total_demand - _EPS:
        balance = "shortage"
        note = (
            f"Supply is {_num(total_demand - total_supply)} units short of demand; "
            "the standard problem has no solution and will need shortage triage."
        )
    else:
        balance = "balanced"
        note = "Supply equals demand."

    def var(i, j):
        return f"x[{i}→{j}]"

    return {
        "status": "ok",
        "sources": list(s),
        "destinations": list(d),
        "variables": [{"name": var(i, j), "from": i, "to": j, "unit_cost": _num(cost)} for i, j, cost in routes],
        "objective": "minimize " + " + ".join(f"{_num(cost):g}·{var(i, j)}" for i, j, cost in routes),
        "supply_constraints": [
            " + ".join(var(i, j) for (ii, j, _) in routes if ii == i) + f" ≤ {_num(s[i]):g}"
            for i in s
            if any(ii == i for ii, _, _ in routes)
        ],
        "demand_constraints": [
            " + ".join(var(i, j) for (i, jj, _) in routes if jj == j) + f" ≥ {_num(d[j]):g}"
            for j in d
            if any(jj == j for _, jj, _ in routes)
        ],
        "non_negativity": "all x ≥ 0",
        "closed_routes": [f"{i}→{j}" for i in s for j in d if j not in c.get(i, {})],
        "total_supply": _num(total_supply),
        "total_demand": _num(total_demand),
        "balance": balance,
        "note": note,
    }


def solve_transportation_problem(
    supplies: dict[str, float], demands: dict[str, float], costs: dict[str, dict[str, float]]
) -> dict:
    """Find the least-cost shipping plan that meets every store's demand, using an exact LP solver.

    If total supply is less than total demand this returns status "infeasible" with the shortfall;
    in that case call solve_with_shortage_triage with the same data.

    Args:
        supplies: Units available at each warehouse, e.g. {"Dallas": 300}.
        demands: Units needed at each store, e.g. {"Miami": 400}.
        costs: Cost per unit for each open route, costs[warehouse][store]. Leave closed routes out.
    """
    s, d, c, err = _clean(supplies, demands, costs)
    if err:
        return err
    total_supply, total_demand = sum(s.values()), sum(d.values())
    if total_supply < total_demand - _EPS:
        short = total_demand - total_supply
        return {
            "status": "infeasible",
            "message": (
                f"Total supply {_num(total_supply):g} is less than total demand {_num(total_demand):g}; "
                f"short by {_num(short):g} units."
            ),
            "total_supply": _num(total_supply),
            "total_demand": _num(total_demand),
            "shortfall": _num(short),
        }

    routes = _routes(c)
    prob = pulp.LpProblem("transportation", pulp.LpMinimize)
    x = [pulp.LpVariable(f"x_{n}", lowBound=0) for n in range(len(routes))]
    prob += pulp.lpSum(cost * x[n] for n, (_, _, cost) in enumerate(routes))
    for i, supply in s.items():
        prob += pulp.lpSum(x[n] for n, (ii, _, _) in enumerate(routes) if ii == i) <= supply
    for j, demand in d.items():
        prob += pulp.lpSum(x[n] for n, (_, jj, _) in enumerate(routes) if jj == j) >= demand
    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        return {
            "status": status.lower(),
            "message": (
                f"The solver could not find a plan (status: {status}). Usually this means some store can only "
                "be reached from warehouses that don't have enough stock for it."
            ),
        }

    shipments = _shipments(routes, x)
    shipped = {i: sum(sh["units"] for sh in shipments if sh["from"] == i) for i in s}
    return {
        "status": "optimal",
        "total_cost": _num(pulp.value(prob.objective) or 0.0),
        "shipments": shipments,
        "unused_supply": {i: _num(s[i] - shipped[i]) for i in s},
        "total_supply": _num(total_supply),
        "total_demand": _num(total_demand),
    }


def solve_with_shortage_triage(
    supplies: dict[str, float], demands: dict[str, float], costs: dict[str, dict[str, float]]
) -> dict:
    """Best possible plan when there isn't enough stock: deliver as many units as possible, at least cost,
    and report which stores will be left short and by how much.

    Use this after solve_transportation_problem returns "infeasible".

    Args:
        supplies: Units available at each warehouse, e.g. {"Dallas": 300}.
        demands: Units needed at each store, e.g. {"Miami": 400}.
        costs: Cost per unit for each open route, costs[warehouse][store]. Leave closed routes out.
    """
    s, d, c, err = _clean(supplies, demands, costs)
    if err:
        return err
    routes = _routes(c)
    # Each unit left undelivered costs more than any possible rerouting of a unit, so the solver
    # first delivers as much as it can, and only then minimizes shipping cost.
    max_cost = max((cost for _, _, cost in routes), default=0.0)
    penalty = 1.0 + max_cost * (len(s) + len(d))

    prob = pulp.LpProblem("transportation_triage", pulp.LpMinimize)
    x = [pulp.LpVariable(f"x_{n}", lowBound=0) for n in range(len(routes))]
    stores = list(d)
    unmet = [pulp.LpVariable(f"u_{k}", lowBound=0) for k in range(len(stores))]
    prob += pulp.lpSum(cost * x[n] for n, (_, _, cost) in enumerate(routes)) + penalty * pulp.lpSum(unmet)
    for i, supply in s.items():
        prob += pulp.lpSum(x[n] for n, (ii, _, _) in enumerate(routes) if ii == i) <= supply
    for k, j in enumerate(stores):
        prob += pulp.lpSum(x[n] for n, (_, jj, _) in enumerate(routes) if jj == j) + unmet[k] == d[j]
    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        return {"status": status.lower(), "message": f"The triage solver could not find a plan (status: {status})."}

    shipments = _shipments(routes, x)
    stores_short = []
    fully_served = []
    for k, j in enumerate(stores):
        short = unmet[k].value() or 0.0
        if short > _EPS:
            delivered = d[j] - short
            stores_short.append(
                {
                    "store": j,
                    "demand": _num(d[j]),
                    "delivered": _num(delivered),
                    "short": _num(short),
                    "served_pct": _num(100 * delivered / d[j]) if d[j] else 0.0,
                }
            )
        else:
            fully_served.append(j)
    shipped = {i: sum(sh["units"] for sh in shipments if sh["from"] == i) for i in s}
    delivered_total = sum(sh["units"] for sh in shipments)
    total_demand = sum(d.values())
    unserved = [st["store"] for st in stores_short if st["delivered"] <= _EPS]
    return {
        "status": "partial" if stores_short else "optimal",
        "total_cost": _num(sum(sh["route_cost"] for sh in shipments)),
        "shipments": shipments,
        "units_delivered": _num(delivered_total),
        "total_demand": _num(total_demand),
        "total_shortfall": _num(total_demand - delivered_total),
        "stores_fully_served": fully_served,
        "stores_short": stores_short,
        "stores_not_served_at_all": unserved,
        "unused_supply": {i: _num(s[i] - shipped[i]) for i in s},
        "message": (
            f"{len(stores_short)} of {len(stores)} stores cannot be fully served; "
            f"{_num(delivered_total):g} of {_num(total_demand):g} units will be delivered."
            if stores_short
            else "All demand can be met; no triage needed."
        ),
    }
