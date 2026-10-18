"""Problem types the agent can solve. Each has formulate / solve / triage tools built on PuLP.

PROBLEM_TYPES is the single source of truth: identify_problem_type returns an entry to the agent, and the
web UI uses the labels.
"""

from .network_flow import (
    formulate_min_cost_flow,
    formulate_multi_commodity_flow,
    solve_min_cost_flow,
    solve_multi_commodity_flow,
    triage_min_cost_flow,
    triage_multi_commodity_flow,
)
from .transportation import (
    formulate_transportation_problem,
    solve_transportation_problem,
    triage_transportation_problem,
)
from .vehicle_routing import (
    MAX_CUSTOMERS,
    formulate_vehicle_routing,
    solve_vehicle_routing,
    triage_vehicle_routing,
)

PROBLEM_TYPES = {
    "transportation": {
        "label": "Transportation",
        "short": "One product shipped straight from sources to destinations at a cost per unit.",
        "use_when": "Goods go directly from supply points (warehouses, plants) to demand points (stores, customers). "
                    "One product, cost per unit on each route, no hubs in between, no lane capacities.",
        "data_needed": ["supply at each source", "demand at each destination",
                        "cost per unit on each open source→destination route (leave closed routes out)"],
        "tools": {"formulate": "formulate_transportation_problem", "solve": "solve_transportation_problem",
                  "triage": "triage_transportation_problem"},
        "explain": "Total cost, shipment table, unused supply, and why the plan looks this way (cheapest routes).",
    },
    "min_cost_flow": {
        "label": "Minimum-cost flow (transshipment)",
        "short": "One product moving through a network with hubs and lane capacities.",
        "use_when": "One product, but goods may pass through intermediate points (distribution centers, cross-docks, "
                    "ports), and/or lanes have capacity limits. Also fine for a transportation problem with lane limits.",
        "data_needed": ["supply at each source", "demand at each destination",
                        "every lane: from, to, cost per unit, capacity if limited (hubs are places that only appear "
                        "in lanes)"],
        "tools": {"formulate": "formulate_min_cost_flow", "solve": "solve_min_cost_flow",
                  "triage": "triage_min_cost_flow"},
        "explain": "Total cost, flow table, how much passes through each hub, lanes running at full capacity "
                   "(bottlenecks), unused supply.",
    },
    "multi_commodity_flow": {
        "label": "Multi-product flow",
        "short": "Several products sharing the same lanes and lane capacities.",
        "use_when": "Two or more distinct products (e.g. frozen and dry goods, product SKUs) each with their own "
                    "supplies and demands, moving over shared lanes whose capacity limits all products together; "
                    "costs may differ by product and some lanes may carry only some products.",
        "data_needed": ["supply of each product at each source", "demand for each product at each destination",
                        "every lane: from, to, cost per unit (per product if it differs), shared capacity, which "
                        "products it may carry if restricted"],
        "tools": {"formulate": "formulate_multi_commodity_flow", "solve": "solve_multi_commodity_flow",
                  "triage": "triage_multi_commodity_flow"},
        "explain": "Total cost and cost per product, flow table by product, lanes at full capacity and which products "
                   "compete for them.",
    },
    "vehicle_routing": {
        "label": "Vehicle routing",
        "short": "Vehicles leave a depot, visit customers in order, and return, within capacity.",
        "use_when": "Deliveries (or pickups) made by a fleet of vehicles that start and end at one depot and visit "
                    "several customers each, so the order of stops matters; each vehicle has a capacity. "
                    f"Up to {MAX_CUSTOMERS} customers.",
        "data_needed": ["depot name", "demand of each customer", "number of vehicles and capacity of each",
                        "locations (x, y in km, or latitude/longitude) or a distance table",
                        "cost per km (default 1) and any fixed cost per vehicle"],
        "tools": {"formulate": "formulate_vehicle_routing", "solve": "solve_vehicle_routing",
                  "triage": "triage_vehicle_routing"},
        "explain": "Each vehicle's stops in order with load and distance, total distance and cost, vehicles used, "
                   "and whether the plan is proven optimal.",
    },
}

SOLVER_TOOLS = [
    formulate_transportation_problem, solve_transportation_problem, triage_transportation_problem,
    formulate_min_cost_flow, solve_min_cost_flow, triage_min_cost_flow,
    formulate_multi_commodity_flow, solve_multi_commodity_flow, triage_multi_commodity_flow,
    formulate_vehicle_routing, solve_vehicle_routing, triage_vehicle_routing,
]
