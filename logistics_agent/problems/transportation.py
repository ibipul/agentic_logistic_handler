"""Transportation problem: ship one product straight from sources (warehouses) to destinations (stores)."""

import pulp

from .common import (
    EPS,
    InputError,
    balance_note,
    banner,
    col,
    error,
    flows_table,
    network,
    non_negative,
    not_called,
    num,
    quantities,
    run_solver,
    stat,
    table,
)

TYPE = "transportation"


def _clean(supplies, demands, costs):
    s = quantities(supplies, "Supply")
    d = quantities(demands, "Demand")
    if not s:
        raise InputError("No warehouses (supplies) were given.")
    if not d:
        raise InputError("No stores (demands) were given.")
    if not isinstance(costs, dict):
        raise InputError("costs must be a mapping costs[warehouse][store] → cost per unit.")
    c = {}
    for i, row in costs.items():
        i = str(i)
        if i not in s:
            raise InputError(f"The cost table has a route from {i}, which is not in the list of warehouses.")
        if not isinstance(row, dict):
            raise InputError(f"costs[{i}] must map store → cost per unit.")
        c[i] = {}
        for j, value in row.items():
            j = str(j)
            if j not in d:
                raise InputError(f"The cost table has a route to {j}, which is not in the list of stores.")
            c[i][j] = non_negative(value, f"Cost from {i} to {j}")
    for j, demand in d.items():
        if demand > 0 and not any(j in row for row in c.values()):
            raise InputError(f"Store {j} has no incoming route, so it cannot be supplied.")
    return s, d, c


def _routes(costs):
    return [(i, j, cost) for i, row in costs.items() for j, cost in row.items()]


def _flows(routes, variables):
    flows = []
    for idx, (i, j, cost) in enumerate(routes):
        units = variables[idx].value() or 0.0
        if units > EPS:
            flows.append({"from": i, "to": j, "units": num(units), "unit_cost": num(cost), "cost": num(units * cost)})
    return flows


def _network(s, d, routes, flows=None):
    used = {(f["from"], f["to"]): f["units"] for f in flows or []}
    nodes = [{"id": i, "role": "supply", "label": f"{i}\nsupply {num(v):g}"} for i, v in s.items()]
    nodes += [{"id": j, "role": "demand", "label": f"{j}\nneeds {num(v):g}"} for j, v in d.items()]
    edges = []
    for i, j, cost in routes:
        units = used.get((i, j), 0.0)
        edges.append(
            {
                "from": i,
                "to": j,
                "units": units,
                "used": units > EPS,
                "label": f"{units:g} @ ${cost:g}" if units > EPS else f"${cost:g}",
            }
        )
    return network(nodes, edges)


def _unused(s, flows):
    return {i: num(s[i] - sum(f["units"] for f in flows if f["from"] == i)) for i in s}


def _unused_note(unused):
    left = [f"{k} {v:g}" for k, v in unused.items() if v > EPS]
    return "Unused supply: " + ", ".join(left) if left else None


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
    try:
        s, d, c = _clean(supplies, demands, costs)
    except InputError as exc:
        return error(str(exc), TYPE, "formulate")
    routes = _routes(c)
    total_supply, total_demand = sum(s.values()), sum(d.values())
    balance, note = balance_note(total_supply, total_demand)

    def var(i, j):
        return f"x[{i}→{j}]"

    supply_lines = [
        " + ".join(var(i, j) for (ii, j, _) in routes if ii == i) + f" ≤ {s[i]:g}"
        for i in s
        if any(ii == i for ii, _, _ in routes)
    ]
    demand_lines = [
        " + ".join(var(i, j) for (i, jj, _) in routes if jj == j) + f" ≥ {d[j]:g}"
        for j in d
        if any(jj == j for _, jj, _ in routes)
    ]
    closed = [f"{i}→{j}" for i in s for j in d if j not in c.get(i, {})]
    objective = "minimize " + " + ".join(f"{cost:g}·{var(i, j)}" for i, j, cost in routes)
    matrix = table(
        "Cost per unit, supply and demand",
        [col("Cost $/unit")] + [col(j, "number") for j in d] + [col("Supply", "number")],
        [[i] + [c[i].get(j) for j in d] + [s[i]] for i in s],
        total=["Demand"] + [d[j] for j in d] + [None],
        note=f"Closed routes (no variable created): {', '.join(closed)}" if closed else None,
    )
    tone = {"shortage": "warn", "surplus": "info", "balanced": "ok"}[balance]
    return {
        "status": "ok",
        "problem_type": TYPE,
        "stage": "formulate",
        "summary": f"{balance}: {len(routes)} variables, {len(supply_lines) + len(demand_lines)} constraints",
        "sources": list(s),
        "destinations": list(d),
        "total_supply": num(total_supply),
        "total_demand": num(total_demand),
        "balance": balance,
        "note": note,
        "closed_routes": closed,
        "model": {
            "objective": objective,
            "groups": [
                {"title": "supply (each warehouse ships at most what it has)", "lines": supply_lines},
                {"title": "demand (each store gets at least what it needs)", "lines": demand_lines},
            ],
            "variables": f"x[warehouse→store] ≥ 0: units shipped on each open route ({len(routes)} variables)",
        },
        "display": {
            "banners": [banner(tone, f"{balance.capitalize()}. Total supply {total_supply:g} · total demand {total_demand:g}. {note}")],
            "tables": [matrix],
            "network": _network(s, d, routes),
        },
    }


def solve_transportation_problem(
    supplies: dict[str, float], demands: dict[str, float], costs: dict[str, dict[str, float]]
) -> dict:
    """Find the least-cost shipping plan that meets every store's demand, using an exact LP solver.

    If total supply is less than total demand this returns status "infeasible" with the shortfall;
    in that case call triage_transportation_problem with the same data.

    Args:
        supplies: Units available at each warehouse, e.g. {"Dallas": 300}.
        demands: Units needed at each store, e.g. {"Miami": 400}.
        costs: Cost per unit for each open route, costs[warehouse][store]. Leave closed routes out.
    """
    try:
        s, d, c = _clean(supplies, demands, costs)
    except InputError as exc:
        return error(str(exc), TYPE, "solve")
    total_supply, total_demand = sum(s.values()), sum(d.values())
    if total_supply < total_demand - EPS:
        short = total_demand - total_supply
        message = f"Total supply {total_supply:g} is less than total demand {total_demand:g}; short by {num(short):g} units."
        return {
            "status": "infeasible",
            "problem_type": TYPE,
            "stage": "solve",
            "summary": message,
            "message": message,
            "total_supply": num(total_supply),
            "total_demand": num(total_demand),
            "shortfall": num(short),
            "solver": not_called("Detected from the totals before calling PuLP: no plan can meet demand."),
            "display": {"banners": [banner("bad", "The full problem has no solution. " + message)]},
        }

    routes = _routes(c)
    prob = pulp.LpProblem("transportation", pulp.LpMinimize)
    x = [pulp.LpVariable(f"x_{n}", lowBound=0) for n in range(len(routes))]
    prob += pulp.lpSum(cost * x[n] for n, (_, _, cost) in enumerate(routes))
    for i, supply in s.items():
        prob += pulp.lpSum(x[n] for n, (ii, _, _) in enumerate(routes) if ii == i) <= supply
    for j, demand in d.items():
        prob += pulp.lpSum(x[n] for n, (_, jj, _) in enumerate(routes) if jj == j) >= demand
    solver = run_solver(prob)

    if solver["solver_status"] != "Optimal":
        message = (
            f"The solver could not find a plan (status: {solver['solver_status']}). Usually this means some store can "
            "only be reached from warehouses that don't have enough stock for it."
        )
        return {
            "status": solver["solver_status"].lower(),
            "problem_type": TYPE,
            "stage": "solve",
            "summary": message,
            "message": message,
            "solver": solver,
            "display": {"banners": [banner("bad", message)]},
        }

    flows = _flows(routes, x)
    unused = _unused(s, flows)
    total_cost = num(pulp.value(prob.objective) or 0.0)
    return {
        "status": "optimal",
        "problem_type": TYPE,
        "stage": "solve",
        "summary": f"optimal: total cost ${total_cost:,.2f}",
        "total_cost": total_cost,
        "shipments": flows,
        "unused_supply": unused,
        "total_supply": num(total_supply),
        "total_demand": num(total_demand),
        "solver": solver,
        "display": {
            "stats": [
                stat("Minimum total cost", total_cost, "money"),
                stat("Units delivered", num(total_demand)),
                stat("Routes used", len(flows)),
            ],
            "tables": [{**flows_table("Shipping plan", flows), "note": _unused_note(unused)}],
            "network": _network(s, d, routes, flows),
        },
    }


def triage_transportation_problem(
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
    try:
        s, d, c = _clean(supplies, demands, costs)
    except InputError as exc:
        return error(str(exc), TYPE, "triage")
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
    solver = run_solver(prob)

    if solver["solver_status"] != "Optimal":
        message = f"The triage solver could not find a plan (status: {solver['solver_status']})."
        return {"status": solver["solver_status"].lower(), "problem_type": TYPE, "stage": "triage",
                "summary": message, "message": message, "solver": solver,
                "display": {"banners": [banner("bad", message)]}}

    flows = _flows(routes, x)
    stores_short, fully_served = [], []
    for k, j in enumerate(stores):
        short = unmet[k].value() or 0.0
        if short > EPS:
            delivered = d[j] - short
            stores_short.append(
                {
                    "store": j,
                    "demand": num(d[j]),
                    "delivered": num(delivered),
                    "short": num(short),
                    "served_pct": num(100 * delivered / d[j]) if d[j] else 0.0,
                }
            )
        else:
            fully_served.append(j)
    unused = _unused(s, flows)
    delivered_total = num(sum(f["units"] for f in flows))
    total_demand = num(sum(d.values()))
    unserved = [st["store"] for st in stores_short if st["delivered"] <= EPS]
    total_cost = num(sum(f["cost"] for f in flows))
    message = (
        f"{len(stores_short)} of {len(stores)} stores cannot be fully served; "
        f"{delivered_total:g} of {total_demand:g} units will be delivered."
        if stores_short
        else "All demand can be met; no triage needed."
    )
    banners = []
    if stores_short:
        banners.append(
            banner(
                "warn",
                "Triage: " + message + (f" {', '.join(unserved)} gets nothing." if unserved else ""),
            )
        )
    tables = []
    if stores_short:
        tables.append(
            table(
                "Stores left short",
                [col("Store"), col("Needs", "number"), col("Gets", "number"), col("Short", "number"), col("Served", "pct")],
                [[r["store"], r["demand"], r["delivered"], r["short"], r["served_pct"]] for r in stores_short],
            )
        )
    tables.append({**flows_table("Shipping plan", flows), "note": _unused_note(unused)})
    return {
        "status": "partial" if stores_short else "optimal",
        "problem_type": TYPE,
        "stage": "triage",
        "summary": f"{message} Cost ${total_cost:,.2f}",
        "total_cost": total_cost,
        "shipments": flows,
        "units_delivered": delivered_total,
        "total_demand": total_demand,
        "total_shortfall": num(total_demand - delivered_total),
        "stores_fully_served": fully_served,
        "stores_short": stores_short,
        "stores_not_served_at_all": unserved,
        "unused_supply": unused,
        "message": message,
        "solver": solver,
        "display": {
            "banners": banners,
            "stats": [
                stat("Shipping cost", total_cost, "money"),
                stat("Units delivered", delivered_total),
                stat("Units short", num(total_demand - delivered_total)),
                stat("Stores fully served", f"{len(fully_served)}/{len(stores)}", "text"),
            ],
            "tables": tables,
            "network": _network(s, d, routes, flows),
        },
    }
