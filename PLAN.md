# Build Plan: Agentic Logistics Handler (Google ADK + PuLP)

This is the build plan for the project described in [README.md](README.md). The README explains how to run and use it; this file explains how it's put together, what each piece must do, and how to check it works.

## 1. Goal

Build an agent, using Google's Agent Development Kit (ADK) in Python, that:

1. Talks with a user about a logistics problem described in plain language.
2. **Identifies which kind of optimization problem it is:** transportation, minimum-cost flow (transshipment), multi-product flow, or vehicle routing, and says why.
3. Writes the problem out as a model (variables, objective, constraints) so the user can check it.
4. Solves it exactly by calling Python tools built on **PuLP** (free linear-programming library, ships with the CBC solver).
5. When the problem has no solution as stated, says why and runs a **triage** step: the best partial plan, and who is left short.
6. Explains the result in plain language and shows it as a **network diagram** or on a **map**.
7. Handles "what-if" follow-ups (close a lane, change a cost, capacity, supply, demand or fleet) by re-solving and comparing.

The main interface is a small web page (FastAPI + one HTML file) that streams the agent's reasoning and tool calls. The agent also runs in ADK's own Dev UI (`adk web`) and terminal (`adk run`).

**Repository:** https://github.com/ibipul/agentic_logistic_handler

**Constraint:** every model must be solvable with PuLP and its bundled CBC solver. No commercial solvers, no other optimization libraries.

## 2. Background: the four problem types

Notation used below: `s` = supply, `d` = demand, `c` = cost per unit, `cap` = capacity, `x` = decision variable.

### 2a. Transportation

One product goes straight from sources `i` (warehouses) to destinations `j` (stores).

```
minimize    Σ_i Σ_j  c_ij · x_ij
subject to  Σ_j x_ij ≤ s_i      for every source i      (can't ship more than you have)
            Σ_i x_ij ≥ d_j      for every destination j (every store gets what it needs)
            x_ij ≥ 0
```

A route that doesn't exist (closed road, no carrier) is left out of the cost table, so no variable is created for it. No solution when total supply < total demand.

### 2b. Minimum-cost flow (transshipment)

One product moves over a network of places joined by lanes `a = (from, to)`. Places that appear only in lanes are **hubs** (distribution centers, cross-docks).

```
minimize    Σ_a  c_a · x_a
subject to  out(n) − in(n) ≤ s_n − d_n     for every supply or demand place n
            out(n) − in(n) = 0             for every hub n (what comes in goes out)
            0 ≤ x_a ≤ cap_a                (cap_a only if the lane has a limit)
```

This covers the transportation problem as a special case. No solution when supply is short (`shortage`), or when there's enough supply but capacities or missing links stop it reaching a destination (`network`).

### 2c. Multi-product flow

Several products `k` share the lanes. Each has its own supplies, demands and (optionally) cost per lane; a lane's capacity limits all products together; a lane may be restricted to some products.

```
minimize    Σ_k Σ_a  c_ka · x_ka
subject to  out_k(n) − in_k(n) ≤ s_kn − d_kn   for every product k and supply/demand place n
            out_k(n) − in_k(n) = 0             for every product k at places where it passes through
            Σ_k x_ka ≤ cap_a                   for every lane with a limit (shared)
            x_ka ≥ 0, only for products lane a may carry
```

### 2d. Capacitated vehicle routing

Identical vehicles (number `K`, capacity `Q`) leave depot `0`, visit customers once each, and return. `dist_ij` comes from coordinates (straight-line) or a distance table.

```
minimize    cost_per_km · Σ dist_ij · x_ij  +  cost_per_vehicle · Σ_j x_0j
subject to  Σ_i x_ij = 1 and Σ_k x_jk = 1     for every customer j (arrive once, leave once)
            Σ_j x_0j ≤ K                       (vehicles leaving the depot)
            Σ_i x_i0 = Σ_j x_0j                (every vehicle comes back)
            load_j ≥ load_i + d_j − Q·(1 − x_ij)   for every pair of customers i ≠ j
            d_i ≤ load_i ≤ Q
            x_ij ∈ {0, 1}
```

The load constraint does two jobs: it enforces vehicle capacity, and it rules out loops that never return to the depot. This is a mixed-integer model, so solve time grows fast with size: limit to 15 customers and give CBC a 30-second time limit, reporting whether the plan is proven optimal. Customer demands must be positive (a zero-demand customer would break the loop-prevention constraint).

### 2e. Triage (when there's no full solution)

Allow each demand to be partly unmet (`u ≥ 0`, or for vehicle routing make each visit optional) and add `penalty · (units unmet)` to the objective. The penalty must be larger than any possible saving from rerouting one unit:

- transportation: `1 + max_cost · (number of sources + number of destinations)`
- network flows: `1 + Σ over lanes of the highest product cost on that lane`
- vehicle routing: `1 + cost_per_km · Σ all distances + cost_per_vehicle · K`, per unit of demand

With that penalty the solver first delivers as much as possible, then finds the cheapest way to do it. The shortfall therefore lands on whatever is most expensive to serve, which may not match business priorities; the agent must say so.

## 3. Prerequisites: human steps

### 3a. Get a Gemini API key (Google AI Studio, free tier, no billing needed)

1. Go to https://aistudio.google.com/apikey and sign in with a personal Google account. The key and its free-tier quota belong to that account.
2. Click **Create API key**, pick or create a Google Cloud project, and copy the key.
3. Copy `logistics_agent/.env.example` to `logistics_agent/.env` and paste the key into `GOOGLE_API_KEY`.

`.env` files are git-ignored. **Never commit a key.** If one is ever committed, treat it as leaked: delete it in AI Studio and create a new one. Rewriting git history isn't enough once it's pushed, and deleting the key makes any copy left in history useless.

Free-tier keys have per-minute and per-day request limits. One question takes about 4-7 model calls; the agent retries rate-limited calls with backoff.

### 3b. Local tools

- Python **3.10+**.
- macOS on Apple Silicon is fine: PuLP 3.x ships a working CBC binary (verified with PuLP 3.3.2).
- Internet access: Gemini API, OpenStreetMap Nominatim (place lookup), and the CDN for the page's JavaScript libraries and map tiles.

## 4. Project layout

```
logistic_handler/
├── PLAN.md                     # this file
├── README.md                   # how to run and use it
├── requirements.txt            # pinned: google-adk, google-genai, pulp, fastapi, uvicorn, pytest
├── run.sh                      # one-command launcher for the web UI
├── .gitignore                  # .env, .env.*, .venv/, __pycache__/, .pytest_cache/ (keeps .env.example)
├── logistics_agent/            # ADK agent package (name must be a valid Python identifier)
│   ├── __init__.py             # from . import agent
│   ├── agent.py                # root_agent: model, instructions, tools
│   ├── tools.py                # identify_problem_type, sample tools, ALL_TOOLS
│   ├── places.py               # locate_places (Nominatim)
│   ├── samples.py              # sample problems: data + plain-language question
│   ├── problems/
│   │   ├── __init__.py         # PROBLEM_TYPES registry, SOLVER_TOOLS
│   │   ├── common.py           # input checks, run_solver, display-block helpers
│   │   ├── transportation.py
│   │   ├── network_flow.py     # min-cost flow + multi-product flow (one engine)
│   │   └── vehicle_routing.py
│   ├── .env.example            # template, committed
│   └── .env                    # real key, NOT committed
├── web/
│   ├── server.py               # FastAPI: runs the agent, streams events, serves samples
│   └── index.html              # the page
└── tests/
    ├── test_transportation.py
    ├── test_network_flow.py
    ├── test_vehicle_routing.py
    └── test_agent_tools.py
```

ADK discovers agents by folder: running `adk web` from the repo root lists `logistics_agent` because its `__init__.py` imports `agent.py`, which defines a variable named exactly `root_agent`.

## 5. Step-by-step implementation

### Step 1: Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Keep exact versions pinned in `requirements.txt`. `run.sh` does all of this, checks the key against Google, finds a free port and starts the server.

### Step 2: Shared pieces (`problems/common.py`)

- **Input checks** raise `InputError` with a plain-language message naming the bad item; each tool turns that into `{"status": "error", "message": ...}`. Numbers sent as strings (`"300"`) are converted; anything else non-numeric is an error. Negative supply, demand, cost or capacity is an error.
- **`parse_arcs`** checks lanes: each needs `from` and `to`; a lane can't start and end at the same place or be listed twice; `cost` ≥ 0; optional `capacity`, `product_costs`, `products`.
- **`run_solver(prob, time_limit=None)`** solves with `pulp.PULP_CBC_CMD(msg=False, timeLimit=...)` and returns a description of the call: library and solver names, the exact call, LP vs. MILP, variable and constraint counts, solver status, whether a solution exists, whether it's proven optimal (`prob.sol_status`), and solve time. The page shows this under every solve step.
- **Display helpers** (`table`, `col`, `stat`, `banner`, `network`, `flows_table`) build the `display` block described in step 4.

PuLP dislikes spaces and symbols in variable names: always name variables by index (`x_0`, `x_3_7`) and keep a lookup back to the real place names, so names like "New York" or "St. Louis (MO)" work.

### Step 3: One module per problem type

Each type gets three tools with the same arguments:

| Tool | Does | Returns |
|---|---|---|
| `formulate_<type>` | Checks the data and writes out the model. Never solves. | `status: ok`, data facts (balance, hubs, products, shortages, unreachable places), `model` (objective, constraint groups with lines, variables), `display` |
| `solve_<type>` | Detects obvious infeasibility from totals without calling the solver, otherwise builds and solves the model | `status: optimal` with the plan, or `infeasible` with a reason and message; never a made-up plan |
| `triage_<type>` | Solves the penalty version (section 2e) | `status: partial` (or `optimal` if nothing is short), the plan, who is short and by how much |

Type names and tool names:

| Type key | Tools | Arguments |
|---|---|---|
| `transportation` | `formulate_transportation_problem`, `solve_transportation_problem`, `triage_transportation_problem` | `supplies`, `demands`, `costs[source][destination]` |
| `min_cost_flow` | `formulate_min_cost_flow`, `solve_min_cost_flow`, `triage_min_cost_flow` | `supplies`, `demands`, `arcs` |
| `multi_commodity_flow` | `formulate_multi_commodity_flow`, `solve_multi_commodity_flow`, `triage_multi_commodity_flow` | `supplies[product][place]`, `demands[product][place]`, `arcs` |
| `vehicle_routing` | `formulate_vehicle_routing`, `solve_vehicle_routing`, `triage_vehicle_routing` | `depot`, `demands`, `num_vehicles`, `vehicle_capacity`, `locations` or `distances`, `location_type` (`grid` or `lat_lon`), `cost_per_distance`, `cost_per_vehicle` |

Type-specific requirements:

- **Transportation:** results list shipments and unused supply per warehouse; triage lists stores short (needs, gets, short, % served) and stores that get nothing.
- **Network flows:** one engine for both types (min-cost flow is multi-product flow with one product). Results add hub throughput, lane capacity use, and bottlenecks (lanes at capacity). When the solver reports infeasible, name any destination that no lane path can reach at all. Multi-product results add cost per product.
- **Vehicle routing:** results list each vehicle's stops in order, load, % of capacity, distance and cost. Distances come from coordinates (straight-line km on a grid, or great-circle km for latitude/longitude, rounded to 2 decimals and used as-is in the model) or from a distance table (one direction is enough; the other is mirrored). Infeasible before solving if an order is bigger than a vehicle or total demand exceeds the fleet. Triage excludes orders bigger than a vehicle up front and reports them separately.

Keep these modules free of ADK imports so they can be unit-tested directly. ADK reads each function's **name, type hints and docstring** to describe it to the model, so docstrings must explain every argument with an example.

### Step 4: The `display` block (one renderer for every type)

Every formulate, solve and triage result carries `problem_type`, `stage` (`formulate`, `solve`, `triage`), a one-line `summary`, and a `display` block the page renders without knowing the type:

```python
"display": {
    "banners": [{"tone": "ok|info|warn|bad", "text": "..."}],
    "stats":   [{"label": "Minimum total cost", "value": 2800, "format": "money"}],
    "tables":  [{"title": "Flow plan", "columns": [{"label": "Lane", "format": "text"}, ...],
                 "rows": [[...]], "total": [...], "note": "..."}],
    "network": {"kind": "flow" | "routes",
                "nodes": [{"id", "role", "label", "x"?, "y"?, "lat"?, "lon"?}],
                "edges": [{"from", "to", "label", "units", "capacity", "used", "saturated", "group"?}]},
}
```

Formats are `text`, `number`, `money` and `pct`; a `null` cell shows as "—". Node roles: `supply`, `hub`, `demand`, `depot`, `customer`, `skipped`.

### Step 5: Registry, samples and agent-level tools

- **`problems/__init__.py`**: `PROBLEM_TYPES` maps each type key to its label, a one-line description, when to use it, the data it needs, its three tool names, and what the answer should cover. `SOLVER_TOOLS` lists the twelve solver tools.
- **`tools.py`**:
  - `identify_problem_type(problem_type, reasoning)` returns the registry entry (data checklist, tools, what to explain), or `status: unsupported` with the supported types.
  - `list_sample_problems()` and `load_sample_problem(name)`: `load_sample_problem` returns the problem type and the exact tool arguments.
  - `ALL_TOOLS` is the agent's tool list.
- **`places.py`**: `locate_places(places)` takes `{name used in the data: search text}` (e.g. `"Sacramento DC" → "Sacramento, California"`) and returns latitude/longitude per name.
  - It uses OpenStreetMap Nominatim, following its usage policy: an identifying User-Agent, at most one request per second, and results cached.
  - It looks up at most 25 places per call.
  - A failed lookup returns an error the agent can ignore; the page then shows only the diagram.
- **`samples.py`**: each sample has `problem_type`, a short `label` and `description`, a plain-language `question` that **doesn't name the problem type**, and the matching structured `data`. Keep both in step: the tests solve from `data`; the page sends `question`.

Samples (expected results verified with PuLP 3.3.2):

| Sample | Type | Expected |
|---|---|---|
| `us_retail_basic` | transportation | optimal, $5,700 |
| `us_retail_surplus` | transportation | optimal, $5,700, 200 unused at Denver |
| `us_retail_shortage` | transportation | infeasible (200 short) → triage: 1,000 of 1,200 delivered, $4,900, Miami 200 short |
| `ca_crossdock` | min-cost flow | optimal, $2,800; bottlenecks Reno Plant → Sacramento DC and Fresno Plant → Bakersfield DC; hub throughput 350 / 400 |
| `ca_bottleneck` | min-cost flow | infeasible (reason `network`) → triage: 500 of 600 delivered, $2,000, San Diego 100 short |
| `midwest_two_lines` | multi-product flow | optimal, $4,600 |
| `midwest_squeeze` | multi-product flow | infeasible → triage: 750 of 850 delivered, $3,800, Indianapolis 100 Frozen short |
| `city_vans` | vehicle routing | optimal, 3 vans, 90 km, $180 |
| `city_vans_short` | vehicle routing | infeasible (220 crates, 2 × 100) → triage: 200 delivered, Pharmacy left out, $178.36 |

### Step 6: The agent (`agent.py`)

- Model in one constant, overridable with `LOGISTICS_MODEL` (default `gemini-3.8-flash`; `gemini-2.5-*` models are closed to new API keys). Check https://ai.google.dev/gemini-api/docs/models when changing it.
- Retry 429/500/503 with backoff (`HttpRetryOptions`).
- `BuiltInPlanner` with `include_thoughts=True` so the page can show the agent's reasoning before each tool call.
- `INSTRUCTION` must cover:
  - **Role.** It's a logistics planner. The instruction includes the list of problem types and when to use each, generated from the registry. If two types fit, pick the simplest that captures everything the user said.
  - **Workflow, always in this order:**
    1. `identify_problem_type`;
    2. `locate_places` once if the problem names real places (only for the map; carry on if it fails);
    3. formulate;
    4. solve;
    5. triage if solve returns infeasible.
  - **Data.** Ask only if data is missing or contradictory. Never invent costs, capacities or demands. Leave closed lanes out.
  - **Never compute a plan, route or cost itself.** Every number must come from the user or a tool.
  - **Answer format.** Lead with the outcome and the key table, then bottlenecks or unused supply, then one or two sentences on why the plan looks this way. After triage, say who is short and suggest fixes, noting that triage cuts what's most expensive to serve. Say so if a routing plan isn't proven optimal.
  - **What-ifs.** Edit the data, re-run formulate → solve (→ triage), and compare with the previous result. Don't re-identify the type unless the change makes it a different kind of problem.
  - **Vehicle routing with real places and no distances:** use the looked-up coordinates as `lat_lon` locations and say that distances are straight-line.

### Step 7: Web UI (`web/server.py`, `web/index.html`)

- **Server**:
  - `GET /` serves the page, with the first sample prefilled.
  - `GET /api/samples` returns the samples (grouped in registry order), the problem types with labels and tool names, and the model name.
  - `POST /api/run` runs the agent in an in-memory ADK session and streams newline-delimited JSON events: `session`, `thought`, `tool_call`, `tool_result`, `text`, `error`, `done`.
  - The `.env` key overrides any Gemini settings already in the shell.
- **Page layout:** the question box and three sections (problem type & formulation, agent steps & tool calls, result) on the left; a **Sample Scenarios** pane on the right, grouped by type; each sample is shown in cobalt blue. Clicking a sample fills the question box; the user presses **Run agent**. On narrow screens the pane moves above the question.
- **Agent steps:** each tool call shows its label, a status badge and summary, what ran (the PuLP/CBC call, or "no solver call"), and expandable arguments and response. Reasoning summaries appear before the call they led to.
- **Formulation section:** problem-type badge with the agent's reasoning, the formulate tool's banners and tables, the model text, and the network.
- **Result section:** banners, stats, tables and network from the latest solve or triage result (after triage, the solve's "no solution" banner stays on top), then the agent's explanation.
- **Network view:** a **Diagram / Map** toggle.
  - Diagram: [Cytoscape.js](https://js.cytoscape.org/). Flow layouts go sources → hubs → destinations, left to right. Vehicle routes are drawn at their coordinates, scaled so labels stay readable. Line width shows units; orange means a lane is at capacity; dashed means unused; each vehicle gets its own color.
  - Map: [Leaflet](https://leafletjs.com/) with OpenStreetMap tiles and attribution. It's enabled only when every place has coordinates, either from the node itself or from a `locate_places` result the page remembers. The map is resized before it's fitted to the places.
- **Libraries:** load only from cdnjs, with exact versions (marked 12.0.2, cytoscape 3.28.1, leaflet 1.9.4).
- **Follow-ups:** the session continues. The formulation stays on screen until a new one arrives, and **New problem** starts a fresh session.

### Step 8: Tests

Run with `pytest -q`. The tests call the tools directly, without the model:

1. **Transportation:**
   - `us_retail_basic`: cost $5,700, with exactly the shipments Dallas→Houston 300, Atlanta→Miami 400, Denver→Phoenix 250, Denver→Houston 50, Denver→Chicago 200.
   - Atlanta→Miami closed: $8,700.
   - Surplus: 200 units unused.
   - Shortage: infeasible, 200 short. Triage delivers 1,000.
   - Triage on the balanced problem: matches the plain solve.
   - Triage prefers delivering to saving cost.
   - Bad input, a store with no route, names with spaces and string numbers.
   - The formulation's constraint counts, and the network marking used routes.
2. **Network flows:**
   - The transportation data as min-cost flow gives $5,700.
   - Cross-dock: $2,800, hub balance, lane capacities, bottlenecks and hub throughput.
   - Bottleneck: infeasible with reason `network`, then triage leaves San Diego 100 short.
   - A supply shortage is caught without calling the solver.
   - An unreachable destination is named.
   - Bad lanes.
   - Multi-product:
     - $4,600, shared capacity respected, no frozen goods on the dry-only lane, costs per product add up;
     - the squeeze is infeasible, then triage leaves Indianapolis short by 100;
     - a shortage is reported per product;
     - the formulation has 13 variables.
3. **Vehicle routing:**
   - The sample serves everyone within capacity.
   - **Brute-force check:** on 5 customers and 2 vehicles, the solver's total distance matches an exhaustive search.
   - Fleet too small: infeasible, then triage delivers 200.
   - An order bigger than a vehicle.
   - A one-direction distance table gets mirrored.
   - Latitude/longitude gives straight-line km.
   - Bad input, including more than 15 customers.
4. **Agent-level:**
   - ADK can build a declaration for every tool.
   - Registry tool names exist.
   - Every sample solves or triages and has a network.
   - `identify_problem_type`, including the unsupported case.
   - The sample tools.
   - `locate_places` maps names and survives lookup failures (the network is mocked).

Some problems have more than one plan with the same lowest cost (e.g. Atlanta→Miami closed). For those, assert on total cost and on constraints being satisfied, not on the exact routes.

### Step 9: Run

```bash
./run.sh                   # web UI, http://localhost:8080 (PORT=9000 ./run.sh to change)
adk web                    # ADK Dev UI, pick "logistics_agent"
adk run logistics_agent    # terminal chat
```

### Step 10: Adding a problem type later

1. Write `formulate_*`, `solve_*` and `triage_*` in a new module under `problems/`, returning the same `status` / `stage` / `summary` / `display` fields.
2. Add a `PROBLEM_TYPES` entry and the three functions to `SOLVER_TOOLS`.
3. Add samples to `samples.py` and tests.

The agent instructions, `identify_problem_type`, the page's labels and the sample pane all read from the registry; no page changes are needed.

## 6. Edge cases the solution must handle

| Case | Expected behavior |
|---|---|
| Supply > demand | Solve; report unused supply per place (per product for multi-product) |
| Supply < demand (overall or for one product) | `infeasible` (reason `shortage`) without calling the solver; agent runs triage |
| Enough supply but lanes can't carry it | Solver reports infeasible (reason `network`); unreachable places named; agent runs triage, which names bottleneck lanes |
| Route or lane missing | Treated as closed (no variable created) |
| Destination with no incoming route/lane (for that product) | `error` naming it |
| Lane listed twice, or from a place to itself | `error` |
| Lane restricted to some products | No variable for other products on that lane |
| Vehicle routing: order bigger than a vehicle | `infeasible` before solving; triage reports it separately as "bigger than a vehicle" |
| Vehicle routing: demand > fleet capacity | `infeasible` before solving; triage serves the most demand possible |
| Vehicle routing: orders don't pack into vehicles | Solver reports infeasible; agent runs triage |
| Vehicle routing: more than 15 customers, zero demand, no locations or distances | `error` with what to change |
| Vehicle routing: solver hits the 30 s limit | Best plan found is returned with `proven_optimal: false`; agent and page say so |
| Place names with spaces / punctuation | Work (index-based variable names) |
| Numbers sent as strings | Converted, or a clear `error` |
| Problem fits none of the four types | `identify_problem_type` returns `unsupported`; agent names the closest supported type |
| Place lookup fails or finds nothing | Agent carries on; page shows the diagram only |
| Non-optimal solver status | Returned with a plain-language message, never a fake plan |

## 7. Demo script

1. Click **Transportation → Warehouses → stores** → Run. Expect: type *Transportation*, $5,700. Follow up: *"The Atlanta → Miami route is closed. Re-plan."* Expect $8,700 and the agent explaining the extra $3,000.
2. Click **Min-cost flow → Plants → DCs → stores** → Run. Expect: type *Minimum-cost flow*, places located on the map, $2,800, two lanes at capacity (orange in the diagram). Toggle **Map**.
3. Click **Min-cost flow → Lane bottleneck → triage** → Run. Expect: "enough supply in total, but the lanes can't carry it", then triage with San Diego 100 short.
4. Click **Multi-product flow → Capacity squeeze → triage** → Run. Expect triage with Indianapolis 100 Frozen short ($3,800). Follow up: *"What if the Indianapolis lane goes back up to 250?"* Expect $4,600 and a comparison, without re-identifying the type.
5. Click **Vehicle routing → Van out of service → triage** → Run. Expect: no full solution (220 crates for 200 of capacity), triage leaves out Pharmacy, routes drawn per van, Pharmacy in red.
6. Freeform: describe a small problem in words and watch the agent pick the type.

## 8. Acceptance criteria

- [x] `pytest -q` passes (36 tests).
- [ ] `adk web` lists `logistics_agent` and it answers (not yet re-checked since the generalization).
- [x] Each sample's data produces the expected result in section 5, step 5 (checked by the tests, without the model).
- [ ] Through the live agent, every sample is identified as the right type and solved with the tools. Checked so far: Plants → DCs → stores, Capacity squeeze (with a follow-up that re-solved without re-identifying), Delivery vans, Van out of service. The other five are still to run.
- [x] Diagram renders for every type; map renders when places are real; page works at phone width with no console errors.
- [x] `.env` is git-ignored; no API key in any committed file or in console output.
- [x] README lets a new person run it from scratch.

## 9. Optional extras

- Store the current problem in ADK session state (`tool_context.state`) so what-ifs edit it reliably instead of the model resending all the data.
- **Facility location** as a fifth type: which warehouses to open, with a fixed opening cost (yes/no variables).
- Priority weights in triage, so the business can protect certain stores, customers or products.
- Time windows for vehicle routing.
- Road routes on the map instead of straight lines (e.g. via an OSRM routing service).
- CSV upload of cost tables, lanes or customer lists.
- ADK evaluation set (`adk eval`) built from the demo script so regressions in the agent's choices are caught.

## 10. References

- ADK Python quickstart: https://adk.dev/get-started/python/
- Gemini models list: https://ai.google.dev/gemini-api/docs/models
- Get an API key: https://aistudio.google.com/apikey
- PuLP docs: https://coin-or.github.io/pulp/
- Cytoscape.js: https://js.cytoscape.org/
- Leaflet: https://leafletjs.com/
- OpenStreetMap tile usage policy: https://operations.osmfoundation.org/policies/tiles/
- Nominatim usage policy: https://operations.osmfoundation.org/policies/nominatim/
