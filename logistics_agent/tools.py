"""Tools the agent can call. Plain Python with no ADK imports, so they can be unit-tested directly.

ADK reads each function's name, type hints and docstring to describe the tool to the model.
"""

from .places import locate_places
from .problems import PROBLEM_TYPES, SOLVER_TOOLS
from .samples import SAMPLES, get_sample


def list_sample_problems() -> dict:
    """List the built-in sample problems (name, problem type and one-line description)."""
    return {
        "stage": "samples",
        "summary": f"{len(SAMPLES)} sample problems",
        "samples": [{"name": n, "problem_type": s["problem_type"], "description": s["description"]}
                    for n, s in SAMPLES.items()],
    }


def load_sample_problem(name: str) -> dict:
    """Load one sample problem by name. Returns its problem type and the exact data to pass to that type's tools.

    Args:
        name: Sample name from list_sample_problems, e.g. "us_retail_basic".
    """
    sample = get_sample(name)
    if sample is None:
        message = f"Unknown sample {name!r}. Known: {', '.join(SAMPLES)}."
        return {"status": "error", "stage": "samples", "message": message, "summary": message}
    return {"status": "ok", "stage": "samples", "summary": f"{name} ({sample['problem_type']})", "name": name,
            "problem_type": sample["problem_type"], "description": sample["description"], "data": sample["data"]}


def identify_problem_type(problem_type: str, reasoning: str) -> dict:
    """Record which kind of logistics problem the user described, before formulating it. Returns the data
    checklist and the formulate / solve / triage tools to use for that type.

    Args:
        problem_type: One of "transportation", "min_cost_flow", "multi_commodity_flow", "vehicle_routing",
            or "unsupported" if none fits.
        reasoning: One or two sentences on which features of the problem decided the type
            (e.g. "goods pass through two distribution centers and some lanes have limits").
    """
    key = (problem_type or "").strip().lower()
    if key not in PROBLEM_TYPES:
        return {
            "status": "unsupported",
            "stage": "identify",
            "problem_type": key or "unsupported",
            "reasoning": reasoning,
            "summary": "not a supported problem type",
            "supported_types": {k: v["short"] for k, v in PROBLEM_TYPES.items()},
            "message": "Tell the user this kind of problem isn't supported yet, name the closest supported type, "
                       "and what data would let you solve it that way.",
        }
    entry = PROBLEM_TYPES[key]
    return {
        "status": "ok",
        "stage": "identify",
        "problem_type": key,
        "label": entry["label"],
        "reasoning": reasoning,
        "summary": entry["label"],
        "use_when": entry["use_when"],
        "data_needed": entry["data_needed"],
        "tools": entry["tools"],
        "explain": entry["explain"],
    }


ALL_TOOLS = [list_sample_problems, load_sample_problem, identify_problem_type, locate_places, *SOLVER_TOOLS]
