"""Shared pieces for every problem type: input checks, the PuLP solver call, and display blocks for the web UI.

Every tool returns plain data for the agent plus a `display` block (banners, stats, tables, model text,
network) that the web page renders the same way for every problem type.
"""

import math
import time

import pulp

EPS = 1e-6


class InputError(Exception):
    """Raised by input checks; tools turn it into {"status": "error", ...}."""


def num(value) -> float:
    return round(float(value), 4)


def error(message: str, problem_type: str, stage: str) -> dict:
    return {"status": "error", "problem_type": problem_type, "stage": stage, "message": message, "summary": message}


def to_float(value, what: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise InputError(f"{what} must be a number (got {value!r}).") from None


def non_negative(value, what: str) -> float:
    v = to_float(value, what)
    if v < 0:
        raise InputError(f"{what} is negative ({v:g}).")
    return v


def quantities(table, what: str) -> dict[str, float]:
    """{name: number} with names as strings and numbers checked to be >= 0."""
    if table is None:
        return {}
    if not isinstance(table, dict):
        raise InputError(f"{what} must be a mapping of name → number.")
    return {str(k): non_negative(v, f"{what} at {k}") for k, v in table.items()}


def parse_arcs(arcs) -> list[dict]:
    """Lanes as [{"from", "to", "cost", "capacity"?, "product_costs"?, "products"?}] with checked numbers."""
    if not arcs:
        raise InputError("No lanes (arcs) were given.")
    out, seen = [], set()
    for n, arc in enumerate(arcs):
        if not isinstance(arc, dict) or "from" not in arc or "to" not in arc:
            raise InputError(f'Lane #{n + 1} must look like {{"from": ..., "to": ..., "cost": ..., "capacity": ...}}.')
        frm, to = str(arc["from"]), str(arc["to"])
        if frm == to:
            raise InputError(f"Lane {frm}→{to} starts and ends at the same place.")
        if (frm, to) in seen:
            raise InputError(f"Lane {frm}→{to} is listed twice; merge it into one lane.")
        seen.add((frm, to))
        cap = arc.get("capacity")
        item = {
            "from": frm,
            "to": to,
            "cost": non_negative(arc.get("cost", 0), f"Cost on {frm}→{to}"),
            "capacity": None if cap is None else non_negative(cap, f"Capacity on {frm}→{to}"),
        }
        if arc.get("product_costs"):
            item["product_costs"] = quantities(arc["product_costs"], f"Product cost on {frm}→{to}")
        if arc.get("products"):
            item["products"] = [str(p) for p in arc["products"]]
        out.append(item)
    return out


def run_solver(prob: pulp.LpProblem, time_limit: int | None = None) -> dict:
    """Solve with PuLP's bundled CBC solver and describe the call, so the agent and UI can show what ran."""
    start = time.perf_counter()
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit))
    integer = any(v.cat == pulp.LpInteger for v in prob.variables())
    call = "pulp.LpProblem.solve(pulp.PULP_CBC_CMD(msg=False" + (f", timeLimit={time_limit}" if time_limit else "") + "))"
    return {
        "called": True,
        "library": f"PuLP {pulp.__version__} (open-source LP modeling library, COIN-OR)",
        "solver": "CBC: COIN-OR Branch and Cut (open-source LP/MIP solver, bundled with PuLP)",
        "call": call,
        "model_kind": "mixed-integer (MILP)" if integer else "linear (LP)",
        "variables": len(prob.variables()),
        "constraints": len(prob.constraints),
        "solver_status": pulp.LpStatus[prob.status],
        "has_solution": prob.sol_status in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible),
        "proven_optimal": prob.sol_status == pulp.LpSolutionOptimal,
        "solve_seconds": round(time.perf_counter() - start, 3),
    }


def not_called(reason: str) -> dict:
    return {"called": False, "reason": reason}


# ---------------------------------------------------------------- display blocks for the web UI


def col(label: str, fmt: str = "text") -> dict:
    """Table column; fmt is text, number, money or pct."""
    return {"label": label, "format": fmt}


def table(title: str, columns: list[dict], rows: list[list], total: list | None = None, note: str | None = None) -> dict:
    t = {"title": title, "columns": columns, "rows": rows}
    if total:
        t["total"] = total
    if note:
        t["note"] = note
    return t


def stat(label: str, value, fmt: str = "number") -> dict:
    return {"label": label, "value": value, "format": fmt}


def banner(tone: str, text: str) -> dict:
    """tone is ok, info, warn or bad."""
    return {"tone": tone, "text": text}


def network(nodes: list[dict], edges: list[dict], kind: str = "flow") -> dict:
    """Graph for the diagram and map views.

    nodes: {"id", "role" (supply, demand, hub, depot, customer, skipped), "label"?, "x"?, "y"?, "lat"?, "lon"?}
    edges: {"from", "to", "label"?, "units"?, "capacity"?, "used": bool, "saturated"?: bool, "group"?}
    kind: "flow" (one arrow per lane) or "routes" (vehicle tours; edges share a group per vehicle).
    """
    return {"kind": kind, "nodes": nodes, "edges": edges}


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def flows_table(title: str, flows: list[dict], with_capacity: bool = False, with_product: bool = False) -> dict:
    columns = ([col("Product")] if with_product else []) + [col("Lane"), col("Units", "number"), col("$/unit", "money")]
    if with_capacity:
        columns += [col("Capacity", "number"), col("Used", "pct")]
    columns.append(col("Cost", "money"))
    rows = []
    for f in flows:
        row = ([f["product"]] if with_product else []) + [f"{f['from']} → {f['to']}", f["units"], f["unit_cost"]]
        if with_capacity:
            row += [f.get("capacity"), f.get("utilization_pct")]
        rows.append(row + [f["cost"]])
    total = (
        ["Total"]
        + ([None] if with_product else [])
        + [num(sum(f["units"] for f in flows)), None]
        + ([None, None] if with_capacity else [])
        + [num(sum(f["cost"] for f in flows))]
    )
    return table(title, columns, rows, total=total)


def balance_note(total_supply: float, total_demand: float) -> tuple[str, str]:
    if total_supply > total_demand + EPS:
        return "surplus", f"Supply exceeds demand by {num(total_supply - total_demand):g} units; some stock stays put."
    if total_supply < total_demand - EPS:
        return "shortage", (
            f"Supply is {num(total_demand - total_supply):g} units short of demand; "
            "the full problem has no solution and will need shortage triage."
        )
    return "balanced", "Supply equals demand."
