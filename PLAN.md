# Build Plan: Agentic Logistics Handler (Google ADK + PuLP)

## 1. Goal

Build a small demo agent, using Google's Agent Development Kit (ADK) in Python, that:

1. Talks with a user about a shipping problem (warehouses, stores, how much each has or needs, cost per unit on each route).
2. Turns that conversation into a **classical transportation problem**.
3. Solves it by calling a Python tool that uses **PuLP** (free linear-programming library, ships with the CBC solver).
4. Explains the result in plain language: what ships where, total cost, unused supply.
5. Handles "what-if" follow-ups ("Atlanta→Miami is closed", "Denver gets 100 more units") by re-solving.

The demo runs locally in the ADK Dev UI (`adk web`).

**Repository:** https://github.com/ibipul/agentic_logistic_handler — all code for this demo lives here (see Step 0).

## 2. Background: the transportation problem

- Sources `i` (warehouses) each have supply `s_i`.
- Destinations `j` (stores) each have demand `d_j`.
- Shipping one unit from `i` to `j` costs `c_ij`.
- Decision variable `x_ij ≥ 0` = units shipped from `i` to `j`.

```
minimize    Σ_i Σ_j  c_ij · x_ij
subject to  Σ_j x_ij ≤ s_i      for every source i      (can't ship more than you have)
            Σ_i x_ij ≥ d_j      for every destination j (every store gets what it needs)
            x_ij ≥ 0
```

A route that doesn't exist (closed road, no carrier) is simply left out of the cost table, so no variable is created for it.

If total supply < total demand, the problem has no solution. The tool must detect this and say so clearly (see section 6).

## 3. Prerequisites — human steps (the user does these, not the agent)

### 3a. Get a Gemini API key (Google AI Studio — free tier, no billing needed)

1. Go to https://aistudio.google.com/apikey and sign in with your **personal Gmail account** (not a company Workspace account). The key and its free-tier quota belong to that account.
2. Accept the terms if prompted.
3. Click **Create API key**. Pick an existing Google Cloud project or let it create one.
4. Copy the key (starts with `AIza...`).
5. Give the key to the project by putting it in `logistics_agent/.env` (step 5 below creates this file from a template). Never commit this file.

Free-tier keys have per-minute and per-day request limits. If the demo starts returning `429 RESOURCE_EXHAUSTED`, wait a minute or enable billing on the project.

### 3b. Local tools

- Python **3.11+** (`python3 --version`).
- macOS on Apple Silicon is fine: PuLP 3.x ships a working CBC binary (verified with PuLP 3.3.2 on this machine).

## 4. Project layout to create

All paths relative to `/Users/bipulislam/code/agentwars/logistic_handler`.

```
logistic_handler/
├── PLAN.md                     # this file
├── README.md                   # how to run the demo
├── requirements.txt
├── .gitignore                  # must include .env, .venv/, __pycache__/
├── logistics_agent/            # ADK agent package (name must be a valid Python identifier)
│   ├── __init__.py             # contains: from . import agent
│   ├── agent.py                # defines root_agent
│   ├── tools.py                # PuLP solver + sample-data tools
│   ├── scenarios.py            # sample scenario data
│   ├── .env.example            # template, committed
│   └── .env                    # real key, NOT committed
└── tests/
    └── test_tools.py
```

ADK discovers agents by folder: running `adk web` from `logistic_handler/` lists `logistics_agent` because it has `__init__.py` importing `agent.py`, which defines a variable named exactly `root_agent`.

## 5. Step-by-step implementation

### Step 0 — Connect the local folder to the GitHub repo

The local folder `/Users/bipulislam/code/agentwars/logistic_handler` is not yet a git repo. Connect it to https://github.com/ibipul/agentic_logistic_handler:

```bash
cd /Users/bipulislam/code/agentwars/logistic_handler
git init
git remote add origin https://github.com/ibipul/agentic_logistic_handler.git
git fetch origin
# If the remote already has commits (e.g. a README or LICENSE created on GitHub):
git checkout -b main --track origin/main   # use the remote's default branch name
# If the remote is empty:
git checkout -b main
```

Rules:
- Create `.gitignore` (with `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`) **before** the first `git add`.
- Before every commit, run `git status` and confirm no `.env` file is staged. If a key is ever committed, treat it as leaked: delete it in AI Studio and create a new one (rewriting git history is not enough once pushed).
- Commit in small steps (scaffold → tools + tests → agent → README). Ask the user before pushing.
- Pushing needs the user's GitHub credentials (HTTPS with a personal access token, SSH key, or `gh auth login`). If a push fails on auth, stop and ask the user to set that up.

### Step 1 — Environment

```bash
cd /Users/bipulislam/code/agentwars/logistic_handler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt`:
```
google-adk
pulp>=3.0
pytest
```

Pin exact versions after the first successful install (`pip freeze | grep -iE "google-adk|pulp"`).

### Step 2 — `.env.example` and `.env`

`logistics_agent/.env.example`:
```
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=PASTE_YOUR_AI_STUDIO_KEY_HERE
```

Copy it to `logistics_agent/.env` and ask the user to paste their key in. Do not print the key in logs or commit it.

### Step 3 — Sample data: `scenarios.py`

Provide a dict of named scenarios. The main one (balanced: total supply = total demand = 1200):

| Cost $/unit | Phoenix | Houston | Miami | Chicago | **Supply** |
|---|---|---|---|---|---|
| Dallas  | 8  | 3 | 9  | 7 | 300 |
| Atlanta | 12 | 6 | 4  | 6 | 400 |
| Denver  | 5  | 7 | 13 | 8 | 500 |
| **Demand** | 250 | 350 | 400 | 200 | |

```python
SCENARIOS = {
    "us_retail_basic": {
        "description": "3 warehouses supplying 4 retail stores (balanced).",
        "supplies": {"Dallas": 300, "Atlanta": 400, "Denver": 500},
        "demands": {"Phoenix": 250, "Houston": 350, "Miami": 400, "Chicago": 200},
        "costs": {
            "Dallas":  {"Phoenix": 8,  "Houston": 3, "Miami": 9,  "Chicago": 7},
            "Atlanta": {"Phoenix": 12, "Houston": 6, "Miami": 4,  "Chicago": 6},
            "Denver":  {"Phoenix": 5,  "Houston": 7, "Miami": 13, "Chicago": 8},
        },
    },
}
```

Also add:
- `us_retail_surplus`: same, but Denver supply = 700 (supply > demand; tool should report 200 unused units).
- `us_retail_shortage`: same, but Atlanta supply = 200 (supply < demand; tool should return `infeasible`).

### Step 4 — Tools: `tools.py`

ADK turns plain Python functions into tools. It reads the **function name, type hints, and docstring** to tell the model what the tool does, so write clear docstrings. Arguments and return values must be JSON-friendly (dicts, lists, str, float, int, bool). Return a `dict`.

Implement three functions:

**`list_sample_scenarios() -> dict`**
Returns `{"scenarios": [{"name": ..., "description": ...}, ...]}`.

**`load_sample_scenario(name: str) -> dict`**
Returns the full scenario (`supplies`, `demands`, `costs`) or `{"status": "error", "message": "unknown scenario ..."}`.

**`solve_transportation_problem(supplies: dict[str, float], demands: dict[str, float], costs: dict[str, dict[str, float]]) -> dict`**

Behavior:
1. **Validate input**, return `{"status": "error", "message": ...}` on any of:
   - empty supplies or demands
   - negative supply, demand, or cost
   - a source in `costs` that isn't in `supplies`, or a destination that isn't in `demands`
   - a destination with no incoming route at all
2. **Check totals.** If `sum(supplies) < sum(demands)`, return:
   ```python
   {"status": "infeasible",
    "message": "Total supply X is less than total demand Y; short by Z units.",
    "total_supply": X, "total_demand": Y}
   ```
3. **Build the model** with PuLP:
   - `prob = pulp.LpProblem("transportation", pulp.LpMinimize)`
   - One `pulp.LpVariable(name, lowBound=0)` per route present in `costs`. Sanitize names (PuLP dislikes spaces and some symbols in variable names): build names like `x_{idx_i}_{idx_j}` and keep a lookup back to the real city names.
   - Objective: `pulp.lpSum(cost * x)`.
   - Supply constraint `≤ s_i` for each source; demand constraint `≥ d_j` for each destination.
4. **Solve** with `prob.solve(pulp.PULP_CBC_CMD(msg=False))`.
5. **Return** (only routes with shipments > 1e-6, rounded sensibly):
   ```python
   {
     "status": "optimal",               # or pulp.LpStatus value if not optimal
     "total_cost": 5700.0,
     "shipments": [
       {"from": "Dallas", "to": "Houston", "units": 300.0,
        "unit_cost": 3.0, "route_cost": 900.0},
       ...
     ],
     "unused_supply": {"Dallas": 0.0, "Atlanta": 0.0, "Denver": 0.0},
     "total_supply": 1200.0,
     "total_demand": 1200.0,
   }
   ```
   If PuLP's status is not `Optimal` (e.g. a store is reachable only from sources that are already used up), return that status plus a plain-language message.

Keep the solver function pure (no ADK imports) so it can be unit-tested directly.

### Step 5 — The agent: `agent.py`

```python
from google.adk.agents import Agent
from .tools import list_sample_scenarios, load_sample_scenario, solve_transportation_problem

root_agent = Agent(
    name="logistics_agent",
    model="gemini-flash-latest",   # see note below
    description="Plans least-cost shipments from warehouses to stores.",
    instruction=INSTRUCTION,
    tools=[list_sample_scenarios, load_sample_scenario, solve_transportation_problem],
)
```

**Model note:** use the alias `gemini-flash-latest` unless it fails. Model IDs change often and older 2.5-series models are being retired around October 2026. Before finalizing, check the current list at https://ai.google.dev/gemini-api/docs/models and pick the current Flash model. Put the model ID in one constant so it's easy to change.

**`INSTRUCTION`** (system prompt) — write it to cover:

- Role: logistics planner for shipping goods from warehouses (sources) to stores (destinations) at least cost.
- Getting data: either the user describes their network, or the agent offers the sample scenarios (`list_sample_scenarios` / `load_sample_scenario`).
- Before solving, show the user the data as a small table (supply, demand, cost matrix) and confirm it, unless the user said "just solve it".
- Never compute the optimal plan itself. Always call `solve_transportation_problem`. Never invent numbers that didn't come from the user or a tool.
- After solving: give total cost, a shipment table (from, to, units, cost), and any unused supply. Then one or two sentences on why the plan looks the way it does (e.g. "Atlanta covers all of Miami because that's its cheapest route by far").
- What-if handling: keep the current scenario in mind; for "route X→Y closed", remove that entry from `costs`; for "route cost changes", change it; for supply/demand changes, update the numbers; then re-solve and compare with the previous result (cost difference, which routes changed).
- If the tool returns `infeasible`, explain the shortfall and suggest fixes (add supply, reduce demand, or accept unmet demand).
- Keep answers short and in plain language; no LP jargon unless the user asks.

### Step 6 — Tests: `tests/test_tools.py`

Run with `pytest -q`. These expected values were computed with PuLP 3.3.2 on the sample data above:

1. **Basic optimal solve** (`us_retail_basic`):
   - status `optimal`, `total_cost == 5700`
   - shipments: Dallas→Houston 300, Atlanta→Miami 400, Denver→Phoenix 250, Denver→Houston 50, Denver→Chicago 200
2. **Closed route** (`us_retail_basic` with Atlanta→Miami removed from `costs`):
   - status `optimal`, `total_cost == 8700`
   - shipments: Dallas→Miami 300, Atlanta→Houston 200, Atlanta→Chicago 200, Denver→Phoenix 250, Denver→Houston 150, Denver→Miami 100
3. **Surplus** (`us_retail_surplus`): status `optimal`, sum of `unused_supply` == 200, all demands met.
4. **Shortage** (`us_retail_shortage`): status `infeasible`, message mentions the 200-unit shortfall.
5. **Bad input**: negative cost → `error`; cost entry for unknown city → `error`.
6. **Names with spaces** (e.g. "New York"): solves without PuLP name errors.

For the shipment checks, compare as sets of `(from, to, units)` so order doesn't matter. Note: in some problems more than one plan has the same lowest cost; for the two cases above the test values were what CBC returned. If a future PuLP version returns a different plan with the same cost, assert only on `total_cost` and on constraints being satisfied.

### Step 7 — Run the agent

From `logistic_handler/` (the **parent** of `logistics_agent/`):

```bash
source .venv/bin/activate
adk web          # opens the Dev UI, usually http://localhost:8000 ; pick "logistics_agent" from the dropdown
# or
adk run logistics_agent   # terminal chat
```

The Dev UI shows each tool call with its arguments and response — use this to confirm the model passed the right data to the solver.

### Step 8 — README.md

Short: what it is, setup (venv, install, API key steps from section 3a, `.env`), how to run, the demo script below, how to run tests.

## 6. Edge cases the solution must handle

| Case | Expected behavior |
|---|---|
| Supply > demand | Solve; report unused supply per warehouse |
| Supply < demand | Tool returns `infeasible` with shortfall; agent suggests fixes |
| Route missing from cost table | Treated as unavailable (no variable created) |
| Store with no incoming routes | Tool returns `error` naming the store |
| City names with spaces / punctuation | Works (sanitized variable names) |
| Model sends numbers as strings | Tool casts to float, or returns a clear `error` |
| Non-optimal solver status | Returned with plain-language message, never a fake plan |

## 7. Demo script (what to type during the demo)

1. "Hi, what can you do?"
2. "Show me the sample scenarios." → "Load the basic US retail one and solve it."
   - Expect: total cost $5,700 with the 5 shipments in Test 1.
3. "The Atlanta to Miami route is closed this week. Re-plan."
   - Expect: $8,700, and the agent explains the +$3,000 and which routes changed.
4. "What if Atlanta only has 200 units?" (with the route reopened)
   - Expect: infeasible, 200 units short, suggestions.
5. Freeform: describe a small custom network in words ("I have two factories, A with 100 and B with 150 ...") and let the agent build the tables, confirm, and solve.

## 8. Acceptance criteria

- [ ] `pytest -q` passes.
- [ ] `adk web` lists `logistics_agent` and it answers.
- [ ] Demo steps 2–4 produce the expected numbers, and the Dev UI shows the solver tool was called each time (the model didn't make up the answer).
- [ ] `.env` is git-ignored; no API key in any committed file or in console output.
- [ ] Code is committed and pushed to https://github.com/ibipul/agentic_logistic_handler.
- [ ] README lets a new person run it from scratch.

## 9. Optional extras (only after the above works)

- Store the current scenario in ADK session state (`tool_context.state`) so what-ifs edit it reliably instead of relying on the model to resend all the data.
- Route capacity limits (`x_ij ≤ cap_ij`) as an optional tool argument.
- Allow unmet demand at a penalty cost per unit, instead of returning `infeasible`.
- Accept a CSV upload of the cost matrix.
- ADK evaluation set (`adk eval`) built from the demo script so regressions are caught.

## 10. References

- ADK Python quickstart: https://adk.dev/get-started/python/
- ADK on Vertex AI (alternative to AI Studio key): https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-development-kit/quickstart
- Gemini models list: https://ai.google.dev/gemini-api/docs/models
- Gemini API changelog: https://ai.google.dev/gemini-api/docs/changelog
- Get an API key: https://aistudio.google.com/apikey
- PuLP docs: https://coin-or.github.io/pulp/
