# Agentic Logistic Handler

An agent that solves logistics optimization problems described in plain language.

You describe what needs to move where: warehouses and stores, plants and distribution centers, product lines sharing trucks, or a fleet of delivery vans. A chat agent built with Google's [Agent Development Kit (ADK)](https://adk.dev/get-started/python/) works out **which kind of optimization problem it is**, writes it out as a model, and solves it exactly with [PuLP](https://coin-or.github.io/pulp/), a free linear-programming library, and its bundled CBC solver. It then explains the plan, draws it as a network diagram or on a map, and re-plans when you ask "what if?"

When the problem has no solution as stated (not enough stock, a lane that can't carry enough, too few vehicles), the agent says why and runs a **triage** step: it finds the best partial plan and tells you exactly who is left short and by how much.

### How it works

```mermaid
flowchart LR
    Q[Question in<br/>plain language] --> I[Identify<br/>problem type]
    I --> P[Locate places<br/>OpenStreetMap]
    I --> F[Formulate<br/>the model]
    P --> F
    F --> S[Exact solve<br/>PuLP / CBC]
    S -->|solvable| R[Plan + cost<br/>+ explanation]
    S -->|no solution| T[Triage:<br/>best partial plan]
    T --> R
    R --> V[Visualize]
    V --> D[Diagram<br/>Cytoscape.js]
    V --> M[Map<br/>Leaflet + OSM]
    R -->|what-if follow-up| F
```

Place lookup runs only when the problem names real places; it enables the map view.

The Gemini agent handles the conversation, picks the problem type and decides which tool to call; Python tools do all the math. Every number in an answer comes from the user or a tool.

## Quick start

Needs Python 3.10+, internet access and a free Gemini API key.

```bash
git clone https://github.com/ibipul/agentic_logistic_handler.git
cd agentic_logistic_handler
```

> [!IMPORTANT]
> **Add your Gemini API key before the first run.** The repo doesn't include one.
>
> 1. Get a free key at https://aistudio.google.com/apikey (no billing needed).
> 2. Copy the template: `cp logistics_agent/.env.example logistics_agent/.env`
> 3. Open `logistics_agent/.env` and replace `PASTE_YOUR_AI_STUDIO_KEY_HERE` with your key:
>    ```
>    GOOGLE_GENAI_USE_VERTEXAI=FALSE
>    GOOGLE_API_KEY=AIza...your-key...
>    ```
>
> `logistics_agent/.env` is listed in `.gitignore`, so git won't commit your key. Don't put the key in `.env.example` or anywhere else that's tracked.

Then start the app:

```bash
./run.sh
```

`run.sh` walks through five numbered steps and says what it's doing at each one: check Python, install packages (first run only, usually 2-5 minutes, with pip's progress shown), check the API key, find a free port, start the server. When it prints **● Ready: http://localhost:8080** (or another port, see below), it opens the page in your browser. Keep that terminal open; press Ctrl+C there to stop.

**If something goes wrong, `run.sh` says so in the terminal:**

| You see | What it means / what to do |
|---|---|
| `Port 8080 is busy (used by …); trying 8081` | Another program has 8080. The app starts on the next free port; use the URL on the **Ready** line. |
| `An earlier run of this app is already serving http://localhost:…` | You started it before and it's still running. Use that URL, or stop it (Ctrl+C in its terminal, or the `kill` command shown) and run `./run.sh` again. |
| `Package install failed` | Usually a network problem. Run `./run.sh` again; if it keeps failing, delete the `.venv` folder and retry. |
| `Google rejected the key` / `Could not reach Google` | The page still opens, but the agent can't answer. Check the internet connection; the message shows Google's reason. |
| `Python 3.10 or newer is required` | Install a newer Python, or point to one: `PYTHON=/path/to/python3.11 ./run.sh`. |

To choose the port yourself: `PORT=9000 ./run.sh`. If that port is taken, `run.sh` stops and says what is using it.

### Problem types and samples

Each type has three tools: **formulate** (check data, write out the model), **solve** (exact, PuLP + CBC) and **triage** (best partial plan when there's no full solution). The **Sample Scenarios** pane on the right has the samples below: click one to put it in the question box, then press **Run agent**. The sample text never names the problem type, so you can watch the agent work it out in **Agent steps** (*Identify problem type*, with its reasoning).

| Type | Data | No solution when | Sample | What to expect |
|---|---|---|---|---|
| **Transportation** | Supplies, demands, cost per route | Supply < demand | **Warehouses → stores** | **$5,700**. Follow up with *"The Atlanta → Miami route is closed. Re-plan."*: **$8,700** |
| | | | **Shortage → triage** | 200 units short. Triage delivers all 1,000 for **$4,900**; Miami gets 200 of 400 |
| **Minimum-cost flow** | Supplies, demands, lanes (cost, optional capacity); places only in lanes are hubs | Supply short, or lanes can't carry it | **Plants → DCs → stores** | **$2,800**; both plant lanes full; 350 units via Sacramento DC, 400 via Bakersfield DC |
| | | | **Lane bottleneck → triage** | Enough stock, but the storm-limited lane can't carry it. Triage: San Diego gets 50 of 150, **$2,000** |
| **Multi-product flow** | Supplies and demands per product; lanes with shared capacity, optional per-product cost or product limits | A product is short, or shared lanes are full | **Frozen + dry, shared trucks** | **$4,600** ($2,400 frozen, $2,200 dry); no frozen on the dry-only lane |
| | | | **Capacity squeeze → triage** | Triage delivers 750 of 850 for **$3,800**; Indianapolis gets no frozen. Follow up with *"What if the Indianapolis lane goes back up to 250?"*: $4,600 |
| **Vehicle routing** | Depot, customer demands (≤ 15), fleet size and capacity, coordinates or distances | Fleet too small, or an order exceeds a vehicle | **Delivery vans** | 3 vans, all 8 customers: **90 km, $180**, proven optimal |
| | | | **Van out of service → triage** | 220 crates for 2 × 100. Triage serves 7 of 8 (200 crates), leaves out Pharmacy, **$178.36** |

- **Triage** puts a penalty on every undelivered unit that outweighs any rerouting saving, so the solver delivers as much as possible, then minimizes cost. Shortfalls land on whatever is most expensive to serve.
- **Vehicle routing** is a mixed-integer model with a 30-second solver limit; results say whether the plan is proven optimal.

Each result has a **Diagram / Map** toggle (see [Seeing the plan](#seeing-the-plan-diagram-and-map)). Expand **Arguments** / **Response** under any tool call to see exactly what the agent sent to the solver and what came back; each solve step shows the PuLP → CBC call, problem size and solve time.

You can also type your own problem, e.g. *"Factory A has 100 units, B has 150. Store X needs 120, Y needs 130. A→X $4, A→Y $6, B→X $5, B→Y $3."*

One question takes about 4-7 model calls. On the free Gemini tier that can hit the per-minute limit; the agent waits and retries automatically, and the page says so.

---

## Seeing the plan: diagram and map

Every solve and triage result includes a small network description (places with roles, lanes with units and capacity, or vehicle routes). The **Result** section draws it two ways, using free open-source libraries loaded from a CDN:

- **Diagram** ([Cytoscape.js](https://js.cytoscape.org/), MIT license): sources on the left, hubs in the middle (diamonds), destinations on the right. Line width = units shipped, orange = lane at full capacity, dashed = unused lane. Vehicle routes are drawn at their coordinates, one color per vehicle; customers left out by triage are red.
- **Map** ([Leaflet](https://leafletjs.com/), BSD license, with [OpenStreetMap](https://www.openstreetmap.org/copyright) tiles): the same network over a real map.

The map needs coordinates. When a problem names real places, the agent calls `locate_places`, which looks the names up with OpenStreetMap's free [Nominatim](https://nominatim.org/) service (no key; at most one request per second, as its usage policy asks; results cached). The agent maps each name used in the data to a search text, e.g. `"Sacramento DC" → "Sacramento, California"`. If the lookup fails, the page shows the diagram only. The coordinates are only for drawing, except in vehicle routing with real places and no distances given, where the agent may use them for straight-line distances and says so. They're never used to make up shipping costs.

Map lines are straight segments between places, not road routes.

---

## Project layout

```
logistic_handler/
├── README.md
├── PLAN.md                     # build plan: models, tool contracts, tests, acceptance criteria
├── requirements.txt
├── run.sh                      # one-command launcher for the web UI
├── logistics_agent/            # the ADK agent package
│   ├── agent.py                # root_agent: model, instructions, tools
│   ├── tools.py                # identify_problem_type, sample tools, the full tool list
│   ├── places.py               # locate_places: OpenStreetMap Nominatim lookup for the map
│   ├── samples.py              # sample problems (data + plain-language question)
│   ├── problems/
│   │   ├── __init__.py         # PROBLEM_TYPES registry: when to use, data, tools per type
│   │   ├── common.py           # input checks, the PuLP/CBC call, display blocks
│   │   ├── transportation.py
│   │   ├── network_flow.py     # minimum-cost flow and multi-product flow (one engine)
│   │   └── vehicle_routing.py
│   ├── .env                    # your Gemini API key (you create it; ignored by git)
│   └── .env.example            # template: copy to .env and add your key
├── web/
│   ├── server.py               # FastAPI app: runs the agent, streams its steps, serves samples
│   └── index.html              # the page: question, sample pane, formulation, steps, result, diagram/map
└── tests/
    ├── test_transportation.py
    ├── test_network_flow.py
    ├── test_vehicle_routing.py # includes a brute-force check that routes are truly optimal
    └── test_agent_tools.py     # registry, samples, ADK tool declarations, place lookup
```

**Adding a problem type:** write `formulate_*`, `solve_*` and `triage_*` functions in `problems/` that return the same `status` / `stage` / `summary` / `display` fields, add an entry to `PROBLEM_TYPES` and the functions to `SOLVER_TOOLS`, and add a sample or two to `samples.py`. The agent instructions, the page and the sample pane pick it up from the registry.

## Setup

`./run.sh` does all of this for you. To do it by hand:

1. **Python 3.10+**: check with `python3 --version`.
2. **Create a virtual environment and install dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **API key:** copy `logistics_agent/.env.example` to `logistics_agent/.env` and set `GOOGLE_API_KEY` to your key (see the box under [Quick start](#quick-start)). `run.sh` stops with a message if this file is missing.

Free-tier keys have per-minute and per-day request limits. If you see `429 RESOURCE_EXHAUSTED`, wait a minute and try again.

The model is set in `logistics_agent/agent.py` (`gemini-3.8-flash`). To try another one without editing code, set `LOGISTICS_MODEL`, e.g. `LOGISTICS_MODEL=gemini-flash-latest ./run.sh`.

## Run

**Web UI** (recommended):

```bash
./run.sh                   # http://localhost:8080 ; use PORT=9000 ./run.sh to change the port
```

**ADK's own tools**, from the repo root with the venv active:

```bash
adk web                    # ADK Dev UI at http://localhost:8000; pick "logistics_agent"
adk run logistics_agent    # chat in the terminal
```

## Tests

```bash
pytest -q
```

The tests call the tools directly, without the model. They check:

- every sample's result;
- that minimum-cost flow reproduces the transportation answer;
- hub balance, lane capacities and product restrictions;
- each kind of infeasibility and its triage;
- that vehicle routes match a brute-force search on a small case;
- bad input;
- that ADK can build a declaration for every tool.

## License

See [LICENSE](LICENSE).
