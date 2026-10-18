"""Network flow problems on a graph of places joined by lanes.

- Minimum-cost flow: one product moves from supply points, possibly through hubs (transshipment), to demand
  points, over lanes with a cost per unit and an optional capacity. Covers the transportation problem too.
- Multi-product flow: several products share the same lanes; a lane's capacity limits all products together,
  and a lane can be restricted to some products (e.g. refrigerated lanes for frozen goods).

Both use one engine: minimum-cost flow is multi-product flow with a single product.
"""

from collections import deque

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
    not_called,
    num,
    parse_arcs,
    quantities,
    run_solver,
    stat,
    table,
)

MCF = "min_cost_flow"
MULTI = "multi_commodity_flow"
_SINGLE = "units"  # internal product name for the one-product case


# ---------------------------------------------------------------- shared engine


class _Net:
    """Checked data: products, supplies/demands per product and node, lanes, node roles."""

    def __init__(self, supplies: dict, demands: dict, arcs: list, single: bool):
        self.single = single
        if single:
            supplies, demands = {_SINGLE: supplies}, {_SINGLE: demands}
        if not isinstance(supplies, dict) or not isinstance(demands, dict):
            raise InputError("supplies and demands must be mappings product → {place: units}.")
        self.products = list(dict.fromkeys([str(k) for k in supplies] + [str(k) for k in demands]))
        self.s = {str(k): quantities(v, "Supply" if single else f"Supply of {k}") for k, v in supplies.items()}
        self.d = {str(k): quantities(v, "Demand" if single else f"Demand for {k}") for k, v in demands.items()}
        for k in self.products:
            self.s.setdefault(k, {})
            self.d.setdefault(k, {})
        if not any(self.s[k] for k in self.products):
            raise InputError("No supplies were given.")
        if not any(self.d[k] for k in self.products):
            raise InputError("No demands were given.")
        self.arcs = parse_arcs(arcs)
        for a in self.arcs:
            for p in a.get("products", []):
                if p not in self.products:
                    raise InputError(f"Lane {a['from']}→{a['to']} allows product {p}, which has no supply or demand.")
            for p in a.get("product_costs", {}):
                if p not in self.products:
                    raise InputError(f"Lane {a['from']}→{a['to']} has a cost for product {p}, which has no supply or demand.")

        ordered = []
        for k in self.products:
            ordered += list(self.s[k])
        for a in self.arcs:
            ordered += [a["from"], a["to"]]
        for k in self.products:
            ordered += list(self.d[k])
        nodes = list(dict.fromkeys(ordered))
        supply_nodes = {n for k in self.products for n, v in self.s[k].items()}
        demand_nodes = {n for k in self.products for n, v in self.d[k].items()}
        self.roles = {}
        for n in nodes:
            if n in supply_nodes and n in demand_nodes:
                self.roles[n] = "supply & demand"
            elif n in supply_nodes:
                self.roles[n] = "supply"
            elif n in demand_nodes:
                self.roles[n] = "demand"
            else:
                self.roles[n] = "hub"
        # Order for display: sources, then hubs, then destinations.
        rank = {"supply": 0, "supply & demand": 0, "hub": 1, "demand": 2}
        self.nodes = sorted(nodes, key=lambda n: rank[self.roles[n]])

        for k in self.products:
            for n, need in self.d[k].items():
                if need > EPS and not any(a["to"] == n and self.allows(a, k) for a in self.arcs):
                    what = n if single else f"{n} (for {k})"
                    raise InputError(f"{what} has no incoming lane, so it cannot be supplied.")

    def allows(self, arc: dict, k: str) -> bool:
        return "products" not in arc or k in arc["products"]

    def cost(self, arc: dict, k: str) -> float:
        return arc.get("product_costs", {}).get(k, arc["cost"])

    def pairs(self):
        """(product, lane index) for every product a lane may carry."""
        return [(k, n) for n, a in enumerate(self.arcs) for k in self.products if self.allows(a, k)]

    def unreachable(self) -> list[str]:
        """Demand points that no supply point can reach over lanes open to that product."""
        out = []
        for k in self.products:
            seen = set(self.s[k])
            queue = deque(seen)
            while queue:
                n = queue.popleft()
                for a in self.arcs:
                    if a["from"] == n and self.allows(a, k) and a["to"] not in seen:
                        seen.add(a["to"])
                        queue.append(a["to"])
            out += [n if self.single else f"{n} ({k})" for n, v in self.d[k].items() if v > EPS and n not in seen]
        return out

    def shortages(self) -> list[dict]:
        out = []
        for k in self.products:
            supply, demand = sum(self.s[k].values()), sum(self.d[k].values())
            if supply < demand - EPS:
                out.append({"product": k, "supply": num(supply), "demand": num(demand), "short": num(demand - supply)})
        return out


def _build(net: _Net, triage: bool):
    prob = pulp.LpProblem("network_flow_triage" if triage else "network_flow", pulp.LpMinimize)
    pairs = net.pairs()
    x = {}
    for idx, (k, n) in enumerate(pairs):
        cap = net.arcs[n]["capacity"]
        x[k, n] = pulp.LpVariable(f"x_{idx}", lowBound=0, upBound=cap if len(net.products) == 1 else None)
    unmet = {}
    if triage:
        for k in net.products:
            for j, need in net.d[k].items():
                if need > EPS:
                    unmet[k, j] = pulp.LpVariable(f"u_{len(unmet)}", lowBound=0, upBound=need)
    # One unit left undelivered costs more than any path a unit could take, so the solver first delivers
    # as much as possible and only then minimizes shipping cost.
    penalty = 1.0 + sum(max(net.cost(a, k) for k in net.products) for a in net.arcs)
    prob += pulp.lpSum(net.cost(net.arcs[n], k) * v for (k, n), v in x.items()) + penalty * pulp.lpSum(unmet.values())

    for k in net.products:
        for node in net.nodes:
            out_ = pulp.lpSum(v for (kk, n), v in x.items() if kk == k and net.arcs[n]["from"] == node)
            in_ = pulp.lpSum(v for (kk, n), v in x.items() if kk == k and net.arcs[n]["to"] == node)
            supply, demand = net.s[k].get(node), net.d[k].get(node)
            if supply is None and demand is None:
                prob += out_ - in_ == 0  # pass-through: what comes in goes out
            else:
                prob += out_ - in_ - unmet.get((k, node), 0) <= (supply or 0) - (demand or 0)
    if len(net.products) > 1:
        for n, a in enumerate(net.arcs):
            if a["capacity"] is not None:
                prob += pulp.lpSum(v for (k, nn), v in x.items() if nn == n) <= a["capacity"]
    return prob, x, unmet


def _flows(net: _Net, x: dict) -> list[dict]:
    totals = {n: sum((v.value() or 0.0) for (k, nn), v in x.items() if nn == n) for n in range(len(net.arcs))}
    flows = []
    for (k, n), v in x.items():
        units = v.value() or 0.0
        if units <= EPS:
            continue
        a = net.arcs[n]
        f = {"from": a["from"], "to": a["to"], "units": num(units), "unit_cost": num(net.cost(a, k)),
             "cost": num(units * net.cost(a, k)), "capacity": a["capacity"]}
        if a["capacity"]:
            f["utilization_pct"] = num(100 * totals[n] / a["capacity"])
        if not net.single:
            f = {"product": k, **f}
        flows.append(f)
    return flows


def _lane_usage(net: _Net, flows: list[dict]) -> list[dict]:
    usage = []
    for a in net.arcs:
        if a["capacity"] is None:
            continue
        used = num(sum(f["units"] for f in flows if f["from"] == a["from"] and f["to"] == a["to"]))
        usage.append({"lane": f"{a['from']} → {a['to']}", "units": used, "capacity": a["capacity"],
                      "full": a["capacity"] > 0 and used >= a["capacity"] - EPS})
    return usage


def _hub_throughput(net: _Net, flows: list[dict]) -> dict:
    return {n: num(sum(f["units"] for f in flows if f["to"] == n)) for n in net.nodes if net.roles[n] == "hub"}


def _unused(net: _Net, flows: list[dict]) -> dict:
    out = {}
    for k in net.products:
        for n, v in net.s[k].items():
            shipped = sum(f["units"] for f in flows if f["from"] == n and f.get("product", _SINGLE) == k)
            received = sum(f["units"] for f in flows if f["to"] == n and f.get("product", _SINGLE) == k)
            left = num(v - net.d[k].get(n, 0) - shipped + received)
            if left > EPS:
                out[n if net.single else f"{n} ({k})"] = left
    return out


def _node_label(net: _Net, n: str) -> str:
    bits = []
    for k in net.products:
        tag = "" if net.single else f" {k}"
        if n in net.s[k]:
            bits.append(f"supply{tag} {net.s[k][n]:g}")
        if n in net.d[k]:
            bits.append(f"needs{tag} {net.d[k][n]:g}")
    return "\n".join([n] + (bits or ["hub"]))


def _network(net: _Net, flows: list[dict] | None = None) -> dict:
    nodes = [{"id": n, "role": {"supply & demand": "supply"}.get(net.roles[n], net.roles[n]), "label": _node_label(net, n)}
             for n in net.nodes]
    edges = []
    for a in net.arcs:
        on_lane = [f for f in flows or [] if f["from"] == a["from"] and f["to"] == a["to"]]
        units = num(sum(f["units"] for f in on_lane))
        cap = a["capacity"]
        if net.single:
            label = f"{units:g}" if units > EPS else f"${a['cost']:g}"
        else:
            label = " · ".join(f"{f['product']} {f['units']:g}" for f in on_lane) or "unused"
        if cap is not None:
            label += f" / cap {cap:g}"
        edges.append({"from": a["from"], "to": a["to"], "units": units, "capacity": cap, "used": units > EPS,
                      "saturated": cap is not None and cap > 0 and units >= cap - EPS and units > EPS, "label": label})
    return network(nodes, edges)


def _formulate(net: _Net, problem_type: str) -> dict:
    pairs = net.pairs()

    def var(k, a):
        lane = f"{a['from']}→{a['to']}"
        return f"x[{lane}]" if net.single else f"x[{k}, {lane}]"

    terms = [f"{net.cost(net.arcs[n], k):g}·{var(k, net.arcs[n])}" for k, n in pairs]
    objective = "minimize " + (" + ".join(terms) if len(terms) <= 40 else "Σ cost[lane, product] · x[lane, product]")
    balance_lines = []
    for k in net.products:
        for node in net.nodes:
            outs = [var(k, net.arcs[n]) for kk, n in pairs if kk == k and net.arcs[n]["from"] == node]
            ins = [var(k, net.arcs[n]) for kk, n in pairs if kk == k and net.arcs[n]["to"] == node]
            if not outs and not ins:
                continue
            lhs = " + ".join(outs) if outs else "0"
            if ins:
                lhs += " − (" + " + ".join(ins) + ")"
            supply, demand = net.s[k].get(node), net.d[k].get(node)
            rhs = "= 0" if supply is None and demand is None else f"≤ {(supply or 0) - (demand or 0):g}"
            balance_lines.append(f"{lhs} {rhs}")
    cap_lines = []
    for n, a in enumerate(net.arcs):
        if a["capacity"] is not None:
            vs = [var(k, a) for k, nn in pairs if nn == n]
            cap_lines.append(" + ".join(vs) + f" ≤ {a['capacity']:g}")

    groups = [{"title": "flow balance (out − in ≤ supply − demand; hubs pass everything through: out − in = 0)",
               "lines": balance_lines}]
    if cap_lines:
        groups.append({"title": "lane capacity" + ("" if net.single else " (shared by all products)"), "lines": cap_lines})

    if net.single:
        node_table = table(
            "Places",
            [col("Place"), col("Role"), col("Supply", "number"), col("Demand", "number")],
            [[n, net.roles[n], net.s[_SINGLE].get(n), net.d[_SINGLE].get(n)] for n in net.nodes],
        )
        lane_table = table(
            "Lanes",
            [col("Lane"), col("$/unit", "money"), col("Capacity", "number")],
            [[f"{a['from']} → {a['to']}", a["cost"], a["capacity"]] for a in net.arcs],
            note="No capacity listed means no limit.",
        )
    else:
        def cell(n, k):
            parts = []
            if n in net.s[k]:
                parts.append(f"supplies {net.s[k][n]:g}")
            if n in net.d[k]:
                parts.append(f"needs {net.d[k][n]:g}")
            return ", ".join(parts) or None

        node_table = table(
            "Places",
            [col("Place"), col("Role")] + [col(k) for k in net.products],
            [[n, net.roles[n]] + [cell(n, k) for k in net.products] for n in net.nodes],
        )
        lane_table = table(
            "Lanes",
            [col("Lane")] + [col(f"{k} $/unit", "money") for k in net.products] + [col("Capacity (all products)", "number")],
            [[f"{a['from']} → {a['to']}"] + [net.cost(a, k) if net.allows(a, k) else None for k in net.products]
             + [a["capacity"]] for a in net.arcs],
            note="A blank cost means the lane doesn't carry that product. No capacity listed means no limit.",
        )

    shortages = net.shortages()
    unreachable = net.unreachable()
    banners = []
    if net.single:
        total_s, total_d = sum(net.s[_SINGLE].values()), sum(net.d[_SINGLE].values())
        balance, note = balance_note(total_s, total_d)
        banners.append(banner({"shortage": "warn", "surplus": "info", "balanced": "ok"}[balance],
                              f"{balance.capitalize()}. Total supply {total_s:g} · total demand {total_d:g}. {note}"))
    else:
        balance = "shortage" if shortages else "enough supply"
        for k in net.products:
            ts, td = sum(net.s[k].values()), sum(net.d[k].values())
            banners.append(banner("warn" if ts < td - EPS else "ok", f"{k}: supply {ts:g} · demand {td:g}."))
    if unreachable:
        banners.append(banner("warn", "No lane path reaches: " + ", ".join(unreachable) + "."))

    hubs = [n for n in net.nodes if net.roles[n] == "hub"]
    return {
        "status": "ok",
        "problem_type": problem_type,
        "stage": "formulate",
        "summary": f"{len(net.nodes)} places ({len(hubs)} hubs), {len(net.arcs)} lanes · {len(pairs)} variables, "
                   f"{len(balance_lines) + len(cap_lines)} constraints",
        "products": None if net.single else net.products,
        "places": {n: net.roles[n] for n in net.nodes},
        "hubs": hubs,
        "balance": balance,
        "product_shortages": shortages or None,
        "unreachable": unreachable,
        "model": {
            "objective": objective,
            "groups": groups,
            "variables": ("x[lane] ≥ 0: units moved on each lane" if net.single
                          else "x[product, lane] ≥ 0: units of each product moved on each lane it may carry")
                         + f" ({len(pairs)} variables)",
        },
        "display": {"banners": banners, "tables": [node_table, lane_table], "network": _network(net)},
    }


def _result_tables(net: _Net, flows: list[dict], usage: list[dict], unused: dict) -> list[dict]:
    tables = [flows_table("Flow plan", flows, with_capacity=any(a["capacity"] for a in net.arcs),
                          with_product=not net.single)]
    if unused:
        tables[0]["note"] = "Unused supply: " + ", ".join(f"{k} {v:g}" for k, v in unused.items())
    hubs = _hub_throughput(net, flows)
    if hubs:
        tables.append(table("Hub throughput", [col("Hub"), col("Units through", "number")], [[h, v] for h, v in hubs.items()]))
    if usage:
        tables.append(table("Lane capacity use",
                            [col("Lane"), col("Units", "number"), col("Capacity", "number"), col("Full?")],
                            [[u["lane"], u["units"], u["capacity"], "yes, bottleneck" if u["full"] else ""] for u in usage]))
    return tables


def _solve(net: _Net, problem_type: str) -> dict:
    base = {"problem_type": problem_type, "stage": "solve"}
    shortages = net.shortages()
    if shortages:
        if net.single:
            sh = shortages[0]
            message = f"Total supply {sh['supply']:g} is less than total demand {sh['demand']:g}; short by {sh['short']:g} units."
        else:
            message = "Not enough supply: " + "; ".join(
                f"{sh['product']} is short by {sh['short']:g} ({sh['supply']:g} available, {sh['demand']:g} needed)"
                for sh in shortages) + "."
        return {**base, "status": "infeasible", "reason": "shortage", "summary": message, "message": message,
                "product_shortages": shortages,
                "solver": not_called("Detected from the totals before calling PuLP: no plan can meet demand."),
                "display": {"banners": [banner("bad", "The full problem has no solution. " + message)]}}

    prob, x, _ = _build(net, triage=False)
    solver = run_solver(prob)
    if solver["solver_status"] != "Optimal":
        unreachable = net.unreachable()
        message = ("There is enough supply in total, but the lanes can't carry it to every destination"
                   + (f" (no path at all to {', '.join(unreachable)})" if unreachable else " (lane capacities are too small)")
                   + ". Run triage to see who would be short.")
        return {**base, "status": "infeasible", "reason": "network", "summary": message, "message": message,
                "unreachable": unreachable, "solver": solver,
                "display": {"banners": [banner("bad", "The full problem has no solution. " + message)]}}

    flows = _flows(net, x)
    usage = _lane_usage(net, flows)
    unused = _unused(net, flows)
    total_cost = num(pulp.value(prob.objective) or 0.0)
    bottlenecks = [u["lane"] for u in usage if u["full"]]
    delivered = num(sum(sum(v.values()) for v in net.d.values()))
    result = {
        **base,
        "status": "optimal",
        "summary": f"optimal: total cost ${total_cost:,.2f}",
        "total_cost": total_cost,
        "flows": flows,
        "hub_throughput": _hub_throughput(net, flows),
        "bottlenecks": bottlenecks,
        "unused_supply": unused,
        "solver": solver,
    }
    stats = [stat("Minimum total cost", total_cost, "money"), stat("Units delivered", delivered),
             stat("Lanes used", len({(f["from"], f["to"]) for f in flows}))]
    if not net.single:
        result["cost_by_product"] = {k: num(sum(f["cost"] for f in flows if f["product"] == k)) for k in net.products}
        stats += [stat(f"{k} cost", v, "money") for k, v in result["cost_by_product"].items()]
    banners = [banner("info", "Lanes running at full capacity: " + ", ".join(bottlenecks) + ".")] if bottlenecks else []
    result["display"] = {"banners": banners, "stats": stats, "tables": _result_tables(net, flows, usage, unused),
                         "network": _network(net, flows)}
    return result


def _triage(net: _Net, problem_type: str) -> dict:
    prob, x, unmet = _build(net, triage=True)
    solver = run_solver(prob)
    base = {"problem_type": problem_type, "stage": "triage"}
    if solver["solver_status"] != "Optimal":
        message = f"The triage solver could not find a plan (status: {solver['solver_status']})."
        return {**base, "status": solver["solver_status"].lower(), "summary": message, "message": message,
                "solver": solver, "display": {"banners": [banner("bad", message)]}}

    flows = _flows(net, x)
    usage = _lane_usage(net, flows)
    unused = _unused(net, flows)
    short = []
    for (k, j), v in unmet.items():
        missing = v.value() or 0.0
        if missing > EPS:
            need = net.d[k][j]
            row = {"destination": j, "demand": num(need), "delivered": num(need - missing), "short": num(missing),
                   "served_pct": num(100 * (need - missing) / need)}
            short.append(row if net.single else {"product": k, **row})
    total_demand = num(sum(sum(v.values()) for v in net.d.values()))
    total_short = num(sum(r["short"] for r in short))
    delivered = num(total_demand - total_short)
    total_cost = num(sum(f["cost"] for f in flows))
    destinations = {j for k in net.products for j, v in net.d[k].items() if v > EPS}
    short_places = sorted({r["destination"] for r in short})
    bottlenecks = [u["lane"] for u in usage if u["full"]]
    message = (f"{len(short_places)} of {len(destinations)} destinations cannot be fully served; "
               f"{delivered:g} of {total_demand:g} units will be delivered." if short
               else "All demand can be met; no triage needed.")
    banners = []
    if short:
        banners.append(banner("warn", "Triage: " + message))
    if bottlenecks:
        banners.append(banner("info", "Lanes running at full capacity: " + ", ".join(bottlenecks) + "."))
    tables = []
    if short:
        cols = ([] if net.single else [col("Product")]) + [col("Destination"), col("Needs", "number"),
                                                           col("Gets", "number"), col("Short", "number"), col("Served", "pct")]
        rows = [([] if net.single else [r["product"]]) + [r["destination"], r["demand"], r["delivered"], r["short"],
                                                           r["served_pct"]] for r in short]
        tables.append(table("Destinations left short", cols, rows))
    tables += _result_tables(net, flows, usage, unused)
    return {
        **base,
        "status": "partial" if short else "optimal",
        "summary": f"{message} Cost ${total_cost:,.2f}",
        "message": message,
        "total_cost": total_cost,
        "flows": flows,
        "units_delivered": delivered,
        "total_demand": total_demand,
        "total_shortfall": total_short,
        "short": short,
        "destinations_fully_served": sorted(destinations - set(short_places)),
        "bottlenecks": bottlenecks,
        "unused_supply": unused,
        "solver": solver,
        "display": {
            "banners": banners,
            "stats": [stat("Shipping cost", total_cost, "money"), stat("Units delivered", delivered),
                      stat("Units short", total_short),
                      stat("Destinations fully served", f"{len(destinations) - len(short_places)}/{len(destinations)}", "text")],
            "tables": tables,
            "network": _network(net, flows),
        },
    }


def _run(fn, problem_type, stage, supplies, demands, arcs, single):
    try:
        net = _Net(supplies, demands, arcs, single)
    except InputError as exc:
        return error(str(exc), problem_type, stage)
    return fn(net, problem_type)


# ---------------------------------------------------------------- minimum-cost flow tools

_MCF_ARGS = """
    Args:
        supplies: Units available at each supply point, e.g. {"Reno Plant": 400}.
        demands: Units needed at each destination, e.g. {"Los Angeles": 250}.
        arcs: Every open lane, e.g. [{"from": "Reno Plant", "to": "Sacramento DC", "cost": 2, "capacity": 350}].
            cost is per unit; capacity is optional (leave it out for no limit). Places that appear only in lanes
            are hubs (distribution centers, cross-docks): whatever flows in must flow out.
"""


def formulate_min_cost_flow(supplies: dict[str, float], demands: dict[str, float], arcs: list[dict]) -> dict:
    return _run(_formulate, MCF, "formulate", supplies, demands, arcs, True)


def solve_min_cost_flow(supplies: dict[str, float], demands: dict[str, float], arcs: list[dict]) -> dict:
    return _run(_solve, MCF, "solve", supplies, demands, arcs, True)


def triage_min_cost_flow(supplies: dict[str, float], demands: dict[str, float], arcs: list[dict]) -> dict:
    return _run(_triage, MCF, "triage", supplies, demands, arcs, True)


formulate_min_cost_flow.__doc__ = (
    "Check the data and write out a minimum-cost flow (transshipment) model: one product moving from supply\n"
    "    points, possibly through hubs, to destinations over lanes with a per-unit cost and optional capacity.\n"
    "    Does not solve anything.\n" + _MCF_ARGS
)
solve_min_cost_flow.__doc__ = (
    "Find the least-cost flow that meets every destination's demand, with an exact LP solver.\n\n"
    "    Returns status \"infeasible\" if there isn't enough supply (reason \"shortage\") or the lanes can't carry it\n"
    "    (reason \"network\": capacity limits or missing links). Then call triage_min_cost_flow with the same data.\n"
    + _MCF_ARGS
)
triage_min_cost_flow.__doc__ = (
    "Best possible plan when demand can't all be met: deliver as many units as possible, at least cost, and\n"
    "    report which destinations are short, by how much, and which lanes are the bottlenecks.\n\n"
    "    Use this after solve_min_cost_flow returns \"infeasible\".\n" + _MCF_ARGS
)


# ---------------------------------------------------------------- multi-product flow tools

_MULTI_ARGS = """
    Args:
        supplies: Units of each product at each supply point: supplies[product][place],
            e.g. {"Frozen": {"Omaha": 300}, "Dry": {"Omaha": 200, "Kansas City": 400}}.
        demands: Units of each product needed at each destination: demands[product][place].
        arcs: Every open lane, e.g. [{"from": "Omaha", "to": "St. Louis Hub", "cost": 3,
            "product_costs": {"Frozen": 5}, "capacity": 400, "products": ["Frozen", "Dry"]}].
            cost is per unit for any product; product_costs overrides it per product (optional); capacity limits
            all products together (optional); products lists which products the lane may carry (optional,
            default all). Places that appear only in lanes are hubs.
"""


def formulate_multi_commodity_flow(
    supplies: dict[str, dict[str, float]], demands: dict[str, dict[str, float]], arcs: list[dict]
) -> dict:
    return _run(_formulate, MULTI, "formulate", supplies, demands, arcs, False)


def solve_multi_commodity_flow(
    supplies: dict[str, dict[str, float]], demands: dict[str, dict[str, float]], arcs: list[dict]
) -> dict:
    return _run(_solve, MULTI, "solve", supplies, demands, arcs, False)


def triage_multi_commodity_flow(
    supplies: dict[str, dict[str, float]], demands: dict[str, dict[str, float]], arcs: list[dict]
) -> dict:
    return _run(_triage, MULTI, "triage", supplies, demands, arcs, False)


formulate_multi_commodity_flow.__doc__ = (
    "Check the data and write out a multi-product flow model: several products share the same lanes, a lane's\n"
    "    capacity limits all products together, and some lanes may carry only some products. Does not solve.\n"
    + _MULTI_ARGS
)
solve_multi_commodity_flow.__doc__ = (
    "Find the least-cost flow of every product that meets all demand, with an exact LP solver.\n\n"
    "    Returns status \"infeasible\" if some product is short (reason \"shortage\") or the shared lanes can't carry\n"
    "    everything (reason \"network\"). Then call triage_multi_commodity_flow with the same data.\n" + _MULTI_ARGS
)
triage_multi_commodity_flow.__doc__ = (
    "Best possible plan when demand can't all be met: deliver as many units as possible across all products,\n"
    "    at least cost, and report which destination/product pairs are short and which lanes are full.\n\n"
    "    Use this after solve_multi_commodity_flow returns \"infeasible\".\n" + _MULTI_ARGS
)
