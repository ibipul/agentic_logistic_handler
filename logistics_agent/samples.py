"""Sample problems used by the agent (load_sample_problem), the web UI's sample pane, and the tests.

Each sample has structured `data` (the exact tool arguments) and a plain-language `question` with the same
numbers, which the web UI drops into the question box. Questions don't name the problem type: the agent has
to work it out. Every sample's places are in one US state (named in the question), so place lookups are
unambiguous and the result fits nicely on the map.
"""

import copy

# ---------------------------------------------------------------- transportation (Texas)

_TX_COSTS = {
    "Fort Worth": {"Midland": 8, "Waco": 3, "Corpus Christi": 9, "San Antonio": 7},
    "Houston": {"Midland": 12, "Waco": 6, "Corpus Christi": 4, "San Antonio": 6},
    "El Paso": {"Midland": 5, "Waco": 7, "Corpus Christi": 13, "San Antonio": 8},
}
_TX_DEMANDS = {"Midland": 250, "Waco": 350, "Corpus Christi": 400, "San Antonio": 200}
_TX_STORES_TEXT = "My stores need: Midland 250, Waco 350, Corpus Christi 400, San Antonio 200.\n"
_TX_COST_TEXT = (
    "Cost per unit:\n"
    "- Fort Worth → Midland 8, Waco 3, Corpus Christi 9, San Antonio 7\n"
    "- Houston → Midland 12, Waco 6, Corpus Christi 4, San Antonio 6\n"
    "- El Paso → Midland 5, Waco 7, Corpus Christi 13, San Antonio 8\n"
)

# ---------------------------------------------------------------- minimum-cost flow (California)

_CA_SUPPLIES = {"Redding Plant": 400, "Fresno Plant": 300}
_CA_DEMANDS = {"San Francisco": 200, "Los Angeles": 250, "San Diego": 150}


def _ca_arcs(sd_cap=None, bak_la_cap=None):
    return [
        {"from": "Redding Plant", "to": "Sacramento DC", "cost": 2, "capacity": 350},
        {"from": "Redding Plant", "to": "Bakersfield DC", "cost": 5},
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
    "- Redding Plant → Sacramento DC $2, max 350\n"
    "- Redding Plant → Bakersfield DC $5\n"
    "- Fresno Plant → Sacramento DC $3\n"
    "- Fresno Plant → Bakersfield DC $2, max 250\n"
    "- Fresno Plant → Los Angeles $7 (direct)\n"
    "- Sacramento DC → Bakersfield DC $2\n"
    "- Sacramento DC → San Francisco $1\n"
    "- Sacramento DC → Los Angeles $6\n"
)

# ---------------------------------------------------------------- multi-product flow (Illinois)

_IL_SUPPLIES = {"Frozen": {"Rockford": 300, "Quincy": 100}, "Dry": {"Rockford": 200, "Quincy": 400}}
_IL_DEMANDS = {
    "Frozen": {"Chicago": 150, "Carbondale": 100, "Champaign": 100},
    "Dry": {"Chicago": 200, "Carbondale": 150, "Champaign": 150},
}


def _il_arcs(champaign_cap=350):
    return [
        {"from": "Rockford", "to": "Chicago", "cost": 4, "product_costs": {"Frozen": 6}, "capacity": 300},
        {"from": "Rockford", "to": "Springfield Hub", "cost": 3, "product_costs": {"Frozen": 5}, "capacity": 400},
        {"from": "Quincy", "to": "Springfield Hub", "cost": 2, "product_costs": {"Frozen": 3}, "capacity": 500},
        {"from": "Quincy", "to": "Carbondale", "cost": 5, "capacity": 200, "products": ["Dry"]},
        {"from": "Springfield Hub", "to": "Chicago", "cost": 3, "product_costs": {"Frozen": 4}, "capacity": 250},
        {"from": "Springfield Hub", "to": "Carbondale", "cost": 3, "product_costs": {"Frozen": 4}, "capacity": 300},
        {"from": "Springfield Hub", "to": "Champaign", "cost": 2, "product_costs": {"Frozen": 3},
         "capacity": champaign_cap},
    ]


def _il_question(champaign_cap, ask):
    return (
        "We move two product lines, Frozen and Dry, from our Rockford and Quincy plants to Chicago, Carbondale and "
        "Champaign, all in Illinois. Some freight goes through our Springfield Hub.\n"
        "Supply: Rockford has 300 Frozen and 200 Dry; Quincy has 100 Frozen and 400 Dry.\n"
        "Needs: Chicago 150 Frozen + 200 Dry; Carbondale 100 Frozen + 150 Dry; Champaign 100 Frozen + 150 Dry.\n"
        "Lanes (cost per unit Dry / Frozen; truck capacity is shared by both lines):\n"
        "- Rockford → Chicago $4 / $6, max 300\n"
        "- Rockford → Springfield Hub $3 / $5, max 400\n"
        "- Quincy → Springfield Hub $2 / $3, max 500\n"
        "- Quincy → Carbondale $5, max 200 — dry vans only, no Frozen\n"
        "- Springfield Hub → Chicago $3 / $4, max 250\n"
        "- Springfield Hub → Carbondale $3 / $4, max 300\n"
        f"- Springfield Hub → Champaign $2 / $3, max {champaign_cap}\n" + ask
    )


# ---------------------------------------------------------------- vehicle routing (California, East Bay)

# Coordinates from OpenStreetMap Nominatim (rounded); the agent looks them up itself from the place names.
_EB_LOCATIONS = {
    "Port of Oakland": [37.7958, -122.2788], "Berkeley": [37.8708, -122.2729], "Albany": [37.8872, -122.2984],
    "Richmond": [37.9358, -122.3477], "Emeryville": [37.8314, -122.2865], "San Leandro": [37.7249, -122.1561],
    "Castro Valley": [37.7136, -122.0716], "Hayward": [37.6688, -122.0808], "Lafayette": [37.8858, -122.1180],
    "Walnut Creek": [37.9021, -122.0619],
}
_EB_DEMANDS = {"Berkeley": 45, "Albany": 20, "Richmond": 40, "Emeryville": 30, "San Leandro": 30, "Castro Valley": 20,
               "Hayward": 45, "Lafayette": 25, "Walnut Creek": 50}
_EB_SMALL_DEMANDS = {k: v for k, v in _EB_DEMANDS.items() if k != "Emeryville"}


def _eb_data(demands, trucks):
    return {"depot": "Port of Oakland", "demands": demands, "num_vehicles": trucks, "vehicle_capacity": 130,
            "locations": {n: _EB_LOCATIONS[n] for n in ["Port of Oakland", *demands]}, "location_type": "lat_lon",
            "cost_per_distance": 1.8}


def _eb_question(demands, trucks, intro):
    orders = "".join(f"- {name}, California: {crates}\n" for name, crates in demands.items())
    return (
        "We run a wholesale bakery out of a warehouse at the Port of Oakland in Oakland, California. Our refrigerated "
        "trucks deliver bread and pastry crates to café and grocery customers across the East Bay, then come back "
        f"to the port.\n{intro}\nOrders, in crates:\n{orders}"
        f"We have {trucks} refrigerated trucks, and each holds 130 crates. Driving costs about $1.80 per km. Each "
        "customer gets one delivery, and no truck can carry more than 130 crates. Plan the delivery routes at the "
        "lowest driving cost: which stops each truck makes and in what order, how full it is, and each route's "
        "distance and cost."
    )


SAMPLES = {
    # transportation
    "us_retail_basic": {
        "problem_type": "transportation",
        "label": "Warehouses → stores",
        "description": "3 Texas warehouses supply 4 stores; supply equals demand.",
        "question": (
            "I run 3 warehouses in Texas: Fort Worth has 300 units, Houston 400, El Paso 500. "
            + _TX_STORES_TEXT + _TX_COST_TEXT + "What's the cheapest way to ship?"
        ),
        "data": {"supplies": {"Fort Worth": 300, "Houston": 400, "El Paso": 500}, "demands": _TX_DEMANDS,
                 "costs": _TX_COSTS},
    },
    "us_retail_surplus": {
        "problem_type": "transportation",
        "label": "Surplus stock",
        "description": "El Paso holds 200 more units than the stores need.",
        "question": (
            "My Texas warehouses: Fort Worth has 300 units, Houston 400 and El Paso 700. "
            + _TX_STORES_TEXT + _TX_COST_TEXT + "Plan the shipments and tell me what's left over."
        ),
        "data": {"supplies": {"Fort Worth": 300, "Houston": 400, "El Paso": 700}, "demands": _TX_DEMANDS,
                 "costs": _TX_COSTS},
    },
    "us_retail_shortage": {
        "problem_type": "transportation",
        "label": "Shortage → triage",
        "description": "Houston has only 200 units: 200 short overall.",
        "question": (
            "Our Houston warehouse only has 200 units this week. Fort Worth has 300 and El Paso 500, all in Texas. "
            + _TX_STORES_TEXT + _TX_COST_TEXT + "Plan the shipments."
        ),
        "data": {"supplies": {"Fort Worth": 300, "Houston": 200, "El Paso": 500}, "demands": _TX_DEMANDS,
                 "costs": _TX_COSTS},
    },
    # minimum-cost flow
    "ca_crossdock": {
        "problem_type": "min_cost_flow",
        "label": "Plants → DCs → stores",
        "description": "2 plants, 2 distribution centers, 3 cities; some lanes have limits.",
        "question": (
            "Our Redding Plant makes 400 units and our Fresno Plant 300. San Francisco needs 200, Los Angeles 250 "
            "and San Diego 150. Most freight goes through our Sacramento DC and Bakersfield DC. Everything is in "
            "California.\n" + _CA_LANES_TEXT
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
            "A storm limits the Bakersfield DC → San Diego lane to 50 units this week. Everything else is the same "
            "(all in California): Redding Plant has 400 units, Fresno Plant 300; San Francisco needs 200, "
            "Los Angeles 250, San Diego 150.\n" + _CA_LANES_TEXT
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
        "question": _il_question(350, "What's the cheapest plan for both lines?"),
        "data": {"supplies": _IL_SUPPLIES, "demands": _IL_DEMANDS, "arcs": _il_arcs()},
    },
    "midwest_squeeze": {
        "problem_type": "multi_commodity_flow",
        "label": "Capacity squeeze → triage",
        "description": "The only lane into Champaign drops to 150 for both lines.",
        "question": _il_question(150, "The Champaign lane is down to 150 because of a bridge closure. Plan both lines."),
        "data": {"supplies": _IL_SUPPLIES, "demands": _IL_DEMANDS, "arcs": _il_arcs(champaign_cap=150)},
    },
    # vehicle routing
    "city_vans": {
        "problem_type": "vehicle_routing",
        "label": "Bakery delivery trucks",
        "description": "3 trucks, 9 East Bay customers.",
        "question": _eb_question(_EB_DEMANDS, 3, "Tomorrow's run:"),
        "data": _eb_data(_EB_DEMANDS, 3),
    },
    "city_vans_short": {
        "problem_type": "vehicle_routing",
        "label": "Truck in the shop → triage",
        "description": "Only 2 trucks for 275 crates of orders.",
        "question": _eb_question(_EB_SMALL_DEMANDS, 2, "Saturday's run is smaller, but one truck is in the shop:"),
        "data": _eb_data(_EB_SMALL_DEMANDS, 2),
    },
}


def get_sample(name: str) -> dict | None:
    """Return a deep copy of a sample so callers can edit it freely."""
    sample = SAMPLES.get(name)
    return copy.deepcopy(sample) if sample else None
