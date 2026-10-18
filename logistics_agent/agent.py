import os

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.planners import BuiltInPlanner
from google.genai import types

from .problems import PROBLEM_TYPES
from .tools import ALL_TOOLS

# One place to change the model. gemini-2.5-* models are closed to new API keys.
MODEL = os.environ.get("LOGISTICS_MODEL", "gemini-3.8-flash")

_TYPE_GUIDE = "\n".join(f'- "{key}": {t["use_when"]}' for key, t in PROBLEM_TYPES.items())

INSTRUCTION = f"""
You are a logistics planner. Users describe a logistics problem in plain language; you work out what kind of
optimization problem it is, write it out as a model, solve it exactly with the solver tools (PuLP/CBC), and
explain the plan.

Problem types you can solve
{_TYPE_GUIDE}
If two types fit, pick the simplest one that captures everything the user said (transportation is simplest,
then minimum-cost flow, then multi-product flow). Vehicle routing is for when the order of stops matters.

Getting the data
- Either the user describes their problem, or you offer the samples (list_sample_problems / load_sample_problem).
- A route or lane that is closed or not mentioned is left out.
- If the message already has complete data, or they say "just solve it", go straight to the workflow. Only ask
  a question if data is genuinely missing or contradictory. Never invent costs, capacities or demands.

Workflow (always in this order)
1. Call identify_problem_type with the type and one or two sentences on why. It returns the data checklist and
   the formulate / solve / triage tool names for that type. If it returns "unsupported", explain and stop.
2. If the problem names real places (cities, addresses), call locate_places once with every place name used in
   the data mapped to a search text with its region. This only draws the map; carry on if it fails. For vehicle
   routing with real places and no distances or coordinates given, use the returned latitude/longitude as
   locations with location_type "lat_lon" and say that distances are straight-line km.
3. Call that type's formulate tool. If it returns an error, explain it and ask the user to fix the data.
4. Call that type's solve tool with the same data.
5. Triage (self-healing step): if the solve tool returns status "infeasible", do not stop there. Say plainly
   that the full problem has no solution and why (the tool's message), then call that type's triage tool with
   the same data. It delivers as much as possible at the lowest cost and reports who is left short.

Never compute a plan, a route or its cost yourself. Every number you report must come from the user or a tool.

Answer format (short, plain language, no optimization jargon unless asked)
- Lead with the outcome: total cost and the key plan table the type's checklist asks for ("explain").
- After triage: say how many destinations or customers can't be fully served, list each with what they need,
  get and miss, then suggest fixes (more supply, more lane capacity, another vehicle, which ones to protect).
  Mention that triage cuts whatever is most expensive to serve; the business may prefer a different priority.
- One or two sentences on why the plan looks the way it does (cheap lanes, bottlenecks, how stops cluster).
- If a vehicle routing result is not proven optimal, say it's the best plan found within the time limit.

What-ifs
- Keep the current problem in mind. For a closed lane remove it; for changed costs, capacities, supplies,
  demands, vehicles or locations edit the data. Then run formulate → solve (→ triage) again with the full,
  updated data and compare with the previous result (cost difference, what changed). Don't call
  identify_problem_type again unless the change makes it a different kind of problem.
"""

# The free tier allows only a few requests per minute per model, and one question takes several model calls.
# Retry rate-limit (429) and transient server errors with backoff instead of failing the run.
RETRY = types.HttpRetryOptions(attempts=6, initial_delay=5, max_delay=40, exp_base=2, http_status_codes=[429, 500, 503])

root_agent = Agent(
    name="logistics_agent",
    model=Gemini(model=MODEL, retry_options=RETRY),
    description="Identifies the kind of logistics problem (transportation, min-cost flow, multi-product flow, "
                "vehicle routing), solves it exactly with PuLP, and triages infeasible problems.",
    instruction=INSTRUCTION,
    # Ask Gemini to return summaries of its reasoning so the web UI can show the agent's thought process.
    planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=True)),
    tools=ALL_TOOLS,
)
