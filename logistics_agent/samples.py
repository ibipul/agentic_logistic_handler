"""Sample problems used by the agent (load_sample_problem), the web UI's sample pane, and the tests.

Each sample has structured `data` (the exact tool arguments) and a plain-language `question` with the same
numbers, which the web UI drops into the question box. Questions don't name the problem type: the agent has
to work it out.
"""

import copy

# ---------------------------------------------------------------- transportation

_RETAIL_COSTS = {
    "Dallas": {"Phoenix": 8, "Houston": 3, "Miami": 9, "Chicago": 7},
    "Atlanta": {"Phoenix": 12, "Houston": 6, "Miami": 4, "Chicago": 6},
    "Denver": {"Phoenix": 5, "Houston": 7, "Miami": 13, "Chicago": 8},
}
_RETAIL_DEMANDS = {"Phoenix": 250, "Houston": 350, "Miami": 400, "Chicago": 200}
_RETAIL_COST_TEXT = (
    "Cost per unit:\n"
    "- Dallas → Phoenix 8, Houston 3, Miami 9, Chicago 7\n"
    "- Atlanta → Phoenix 12, Houston 6, Miami 4, Chicago 6\n"
    "- Denver → Phoenix 5, Houston 7, Miami 13, Chicago 8\n"
)

# ---------------------------------------------------------------- minimum-cost flow (transshipment)

_CA_SUPPLIES = {"Reno Plant": 400, "Fresno Plant": 300}
_CA_DEMANDS = {"San Francisco": 200, "Los Angeles": 250, "San Diego": 150}


def _ca_arcs(sd_cap=None, bak_la_cap=None):
    return [
        {"from": "Reno Plant", "to": "Sacramento DC", "cost": 2, "capacity": 350},
        {"from": "Reno Plant", "to": "Bakersfield DC", "cost": 5},
        {"from": "Fresno Plant", "to": "Sacramento DC", "cost": 3},
        {"from": "Fresno Plant", "to": "Bakersfield DC", "cost": 2, "capacity": 250},
        {"from": "Fresno Plant", "to": "Los Angeles", "cost": 7},
        {"from": "Sacramento DC", "to": "Bakersfield DC", "cost": 2},
        {"from": "Sacramento DC", "to": "San Francisco", "cost": 1},
        {"from": "Sacramento DC", "to": "Los Angeles", "cost": 6},
        {"from": "Bakersfield DC", "to": "Los Angeles", "cost": 2, **({"capacity": bak_la_cap} if bak_la_cap else {})},
        {"from": "Bakersfield DC", "to": "San Diego", "cost": 4, **({"capacity": sd_cap} if sd_cap else {})},
    ]


_CA_LANES_TEXT = (
    "Lanes (cost per unit, capacity if limited):\n"
    "- Reno Plant → Sacramento DC $2, max 350\n"
    "- Reno Plant → Bakersfield DC $5\n"
    "- Fresno Plant → Sacramento DC $3\n"
    "- Fresno Plant → Bakersfield DC $2, max 250\n"
    "- Fresno Plant → Los Angeles $7 (direct)\n"
    "- Sacramento DC → Bakersfield DC $2\n"
    "- Sacramento DC → San Francisco $1\n"
    "- Sacramento DC → Los Angeles $6\n"
)

# ---------------------------------------------------------------- multi-product flow

_MW_SUPPLIES = {"Frozen": {"Omaha": 300, "Kansas City": 100}, "Dry": {"Omaha": 200, "Kansas City": 400}}
_MW_DEMANDS = {
    "Frozen": {"Chicago": 150, "Memphis": 100, "Indianapolis": 100},
    "Dry": {"Chicago": 200, "Memphis": 150, "Indianapolis": 150},
}


def _mw_arcs(indy_cap=350):
    return [
        {"from": "Omaha", "to": "Chicago", "cost": 4, "product_costs": {"Frozen": 6}, "capacity": 300},
        {"from": "Omaha", "to": "St. Louis Hub", "cost": 3, "product_costs": {"Frozen": 5}, "capacity": 400},
        {"from": "Kansas City", "to": "St. Louis Hub", "cost": 2, "product_costs": {"Frozen": 3}, "capacity": 500},
        {"from": "Kansas City", "to": "Memphis", "cost": 5, "capacity": 200, "products": ["Dry"]},
        {"from": "St. Louis Hub", "to": "Chicago", "cost": 3, "product_costs": {"Frozen": 4}, "capacity": 250},
        {"from": "St. Louis Hub", "to": "Memphis", "cost": 3, "product_costs": {"Frozen": 4}, "capacity": 300},
        {"from": "St. Louis Hub", "to": "Indianapolis", "cost": 2, "product_costs": {"Frozen": 3}, "capacity": indy_cap},
    ]


def _mw_question(indy_cap, ask):
    return (
        "We move two product lines, Frozen and Dry, from our Omaha and Kansas City plants to Chicago, Memphis and "
        "Indianapolis. Some freight goes through our St. Louis Hub.\n"
        "Supply: Omaha has 300 Frozen and 200 Dry; Kansas City has 100 Frozen and 400 Dry.\n"
        "Needs: Chicago 150 Frozen + 200 Dry; Memphis 100 Frozen + 150 Dry; Indianapolis 100 Frozen + 150 Dry.\n"
        "Lanes (cost per unit Dry / Frozen; truck capacity is shared by both lines):\n"
        "- Omaha → Chicago $4 / $6, max 300\n"
        "- Omaha → St. Louis Hub $3 / $5, max 400\n"
        "- Kansas City → St. Louis Hub $2 / $3, max 500\n"
        "- Kansas City → Memphis $5, max 200 — dry vans only, no Frozen\n"
        "- St. Louis Hub → Chicago $3 / $4, max 250\n"
        "- St. Louis Hub → Memphis $3 / $4, max 300\n"
        f"- St. Louis Hub → Indianapolis $2 / $3, max {indy_cap}\n" + ask
    )


# ---------------------------------------------------------------- vehicle routing

_VAN_DEMANDS = {"Bakery": 30, "Cafe": 25, "Grocery": 40, "Pharmacy": 20, "Deli": 35, "Market": 30, "Kiosk": 15,
                "Bistro": 25}
_VAN_LOCATIONS = {"Warehouse": [0, 0], "Bakery": [4, 9], "Cafe": [8, 3], "Grocery": [-6, 7], "Pharmacy": [-9, -2],
                  "Deli": [3, -8], "Market": [-4, -9], "Kiosk": [10, -4], "Bistro": [7, 10]}
_VAN_TEXT = (
    "Our warehouse is at (0, 0) on a km grid. Today's orders, in crates, with each customer's location:\n"
    "- Bakery (4, 9): 30\n- Cafe (8, 3): 25\n- Grocery (-6, 7): 40\n- Pharmacy (-9, -2): 20\n"
    "- Deli (3, -8): 35\n- Market (-4, -9): 30\n- Kiosk (10, -4): 15\n- Bistro (7, 10): 25\n"
)


def _vans(n):
    return {"depot": "Warehouse", "demands": _VAN_DEMANDS, "num_vehicles": n, "vehicle_capacity": 100,
            "locations": _VAN_LOCATIONS, "location_type": "grid", "cost_per_distance": 2}


SAMPLES = {
    # transportation
    "us_retail_basic": {
        "problem_type": "transportation",
        "label": "Warehouses → stores",
        "description": "3 warehouses supply 4 stores; supply equals demand.",
        "question": (
            "I run 3 warehouses: Dallas has 300 units, Atlanta 400, Denver 500. "
            "My stores need: Phoenix 250, Houston 350, Miami 400, Chicago 200.\n"
            + _RETAIL_COST_TEXT + "What's the cheapest way to ship?"
        ),
        "data": {"supplies": {"Dallas": 300, "Atlanta": 400, "Denver": 500}, "demands": _RETAIL_DEMANDS,
                 "costs": _RETAIL_COSTS},
    },
    "us_retail_surplus": {
        "problem_type": "transportation",
        "label": "Surplus stock",
        "description": "Denver holds 200 more units than the stores need.",
        "question": (
            "Dallas has 300 units, Atlanta 400 and Denver 700. "
            "Stores need: Phoenix 250, Houston 350, Miami 400, Chicago 200.\n"
            + _RETAIL_COST_TEXT + "Plan the shipments and tell me what's left over."
        ),
        "data": {"supplies": {"Dallas": 300, "Atlanta": 400, "Denver": 700}, "demands": _RETAIL_DEMANDS,
                 "costs": _RETAIL_COSTS},
    },
    "us_retail_shortage": {
        "problem_type": "transportation",
        "label": "Shortage → triage",
        "description": "Atlanta has only 200 units: 200 short overall.",
        "question": (
            "Atlanta only has 200 units this week. Dallas has 300 and Denver 500. "
            "Stores still need: Phoenix 250, Houston 350, Miami 400, Chicago 200.\n"
            + _RETAIL_COST_TEXT + "Plan the shipments."
        ),
        "data": {"supplies": {"Dallas": 300, "Atlanta": 200, "Denver": 500}, "demands": _RETAIL_DEMANDS,
                 "costs": _RETAIL_COSTS},
    },
    # minimum-cost flow
    "ca_crossdock": {
        "problem_type": "min_cost_flow",
        "label": "Plants → DCs → stores",
        "description": "2 plants, 2 distribution centers, 3 cities; some lanes have limits.",
        "question": (
            "Our Reno Plant makes 400 units and our Fresno Plant 300. San Francisco needs 200, Los Angeles 250 "
            "and San Diego 150. Most freight goes through our Sacramento DC and Bakersfield DC.\n"
            + _CA_LANES_TEXT
            + "- Bakersfield DC → Los Angeles $2\n- Bakersfield DC → San Diego $4\n"
            "Find the cheapest flow."
        ),
        "data": {"supplies": _CA_SUPPLIES, "demands": _CA_DEMANDS, "arcs": _ca_arcs()},
    },
    "ca_bottleneck": {
        "problem_type": "min_cost_flow",
        "label": "Lane bottleneck → triage",
        "description": "Enough stock, but a storm limits the only lane into San Diego.",
        "question": (
            "A storm limits the Bakersfield DC → San Diego lane to 50 units this week. Everything else is the same: "
            "Reno Plant has 400 units, Fresno Plant 300; San Francisco needs 200, Los Angeles 250, San Diego 150.\n"
            + _CA_LANES_TEXT
            + "- Bakersfield DC → Los Angeles $2\n- Bakersfield DC → San Diego $4, max 50 (storm)\n"
            "Plan the week."
        ),
        "data": {"supplies": _CA_SUPPLIES, "demands": _CA_DEMANDS, "arcs": _ca_arcs(sd_cap=50)},
    },
    # multi-product flow
    "midwest_two_lines": {
        "problem_type": "multi_commodity_flow",
        "label": "Frozen + dry, shared trucks",
        "description": "2 product lines share lane capacity; one lane can't carry frozen.",
        "question": _mw_question(350, "What's the cheapest plan for both lines?"),
        "data": {"supplies": _MW_SUPPLIES, "demands": _MW_DEMANDS, "arcs": _mw_arcs()},
    },
    "midwest_squeeze": {
        "problem_type": "multi_commodity_flow",
        "label": "Capacity squeeze → triage",
        "description": "The only lane into Indianapolis drops to 150 for both lines.",
        "question": _mw_question(150, "The Indianapolis lane is down to 150 because of a bridge closure. Plan both lines."),
        "data": {"supplies": _MW_SUPPLIES, "demands": _MW_DEMANDS, "arcs": _mw_arcs(indy_cap=150)},
    },
    # vehicle routing
    "city_vans": {
        "problem_type": "vehicle_routing",
        "label": "Delivery vans",
        "description": "3 vans, 8 customers on a km grid.",
        "question": _VAN_TEXT + "We have 3 vans that hold 100 crates each, and driving costs $2 per km. "
                                "Plan the delivery routes.",
        "data": _vans(3),
    },
    "city_vans_short": {
        "problem_type": "vehicle_routing",
        "label": "Van out of service → triage",
        "description": "Only 2 vans for 220 crates of orders.",
        "question": _VAN_TEXT + "One van is in the shop, so only 2 vans (100 crates each) are running. Driving "
                                "costs $2 per km. Plan today's routes.",
        "data": _vans(2),
    },
}


def get_sample(name: str) -> dict | None:
    """Return a deep copy of a sample so callers can edit it freely."""
    sample = SAMPLES.get(name)
    return copy.deepcopy(sample) if sample else None
