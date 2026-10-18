from google.adk.tools import FunctionTool

from logistics_agent import places
from logistics_agent.problems import PROBLEM_TYPES, SOLVER_TOOLS
from logistics_agent.samples import SAMPLES
from logistics_agent.tools import ALL_TOOLS, identify_problem_type, list_sample_problems, load_sample_problem


def test_every_tool_has_a_declaration_adk_can_build():
    for fn in ALL_TOOLS:
        decl = FunctionTool(fn)._get_declaration()
        assert decl.name == fn.__name__
        assert decl.description, fn.__name__


def test_registry_points_at_real_tools():
    names = {fn.__name__ for fn in SOLVER_TOOLS}
    for entry in PROBLEM_TYPES.values():
        assert set(entry["tools"].values()) <= names


def test_every_sample_solves_or_triages():
    tools = {fn.__name__: fn for fn in SOLVER_TOOLS}
    for name, sample in SAMPLES.items():
        t = PROBLEM_TYPES[sample["problem_type"]]["tools"]
        result = tools[t["solve"]](**sample["data"])
        if result["status"] == "infeasible":
            result = tools[t["triage"]](**sample["data"])
        assert result["status"] in ("optimal", "partial"), name
        assert result["display"]["network"]["nodes"], name


def test_identify_problem_type():
    r = identify_problem_type("min_cost_flow", "goods pass through DCs")
    assert r["status"] == "ok" and r["tools"]["triage"] == "triage_min_cost_flow"
    r = identify_problem_type("job_shop_scheduling", "machines and jobs")
    assert r["status"] == "unsupported" and "vehicle_routing" in r["supported_types"]


def test_sample_tools():
    names = {s["name"] for s in list_sample_problems()["samples"]}
    assert {"us_retail_basic", "ca_crossdock", "midwest_two_lines", "city_vans"} <= names
    loaded = load_sample_problem("us_retail_basic")
    assert loaded["problem_type"] == "transportation" and loaded["data"]["supplies"]["El Paso"] == 500
    assert load_sample_problem("nope")["status"] == "error"


def test_locate_places_maps_names_and_survives_failures(monkeypatch):
    def fake_lookup(query):
        if query == "boom":
            raise OSError("offline")
        return {"lat": 1.0, "lon": 2.0, "matched": query} if query != "Nowhere" else None

    monkeypatch.setattr(places, "_lookup", fake_lookup)
    r = places.locate_places({"Sacramento DC": "Sacramento, California", "X": "Nowhere"})
    assert r["status"] == "partial" and set(r["places"]) == {"Sacramento DC"} and r["not_found"] == ["X"]
    r = places.locate_places({"A": "boom"})
    assert r["status"] == "error" and "offline" in r["message"]
