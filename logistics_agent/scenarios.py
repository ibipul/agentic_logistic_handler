"""Sample transportation problems used by the agent, the web UI and the tests."""

import copy

_BASIC_COSTS = {
    "Dallas": {"Phoenix": 8, "Houston": 3, "Miami": 9, "Chicago": 7},
    "Atlanta": {"Phoenix": 12, "Houston": 6, "Miami": 4, "Chicago": 6},
    "Denver": {"Phoenix": 5, "Houston": 7, "Miami": 13, "Chicago": 8},
}
_BASIC_DEMANDS = {"Phoenix": 250, "Houston": 350, "Miami": 400, "Chicago": 200}

SCENARIOS = {
    "us_retail_basic": {
        "description": "3 warehouses supplying 4 retail stores (balanced: supply = demand = 1200).",
        "supplies": {"Dallas": 300, "Atlanta": 400, "Denver": 500},
        "demands": _BASIC_DEMANDS,
        "costs": _BASIC_COSTS,
    },
    "us_retail_surplus": {
        "description": "Same network, but Denver has 700 units (200 more than the stores need).",
        "supplies": {"Dallas": 300, "Atlanta": 400, "Denver": 700},
        "demands": _BASIC_DEMANDS,
        "costs": _BASIC_COSTS,
    },
    "us_retail_shortage": {
        "description": "Same network, but Atlanta has only 200 units (200 short of total demand).",
        "supplies": {"Dallas": 300, "Atlanta": 200, "Denver": 500},
        "demands": _BASIC_DEMANDS,
        "costs": _BASIC_COSTS,
    },
}


def get_scenario(name: str) -> dict | None:
    """Return a deep copy of a scenario so callers can edit it freely."""
    scenario = SCENARIOS.get(name)
    return copy.deepcopy(scenario) if scenario else None
