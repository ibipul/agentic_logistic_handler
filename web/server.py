"""Small web front end for the logistics agent.

Run from the repo root:  uvicorn web.server:app --port 8080
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
# override=True: the bundled key wins over any GOOGLE_API_KEY / Vertex settings already in the judge's shell.
load_dotenv(ROOT / "logistics_agent" / ".env", override=True)

from google.adk.runners import Runner  # noqa: E402  (needs the API key loaded first)
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from logistics_agent.agent import MODEL, root_agent  # noqa: E402

APP_NAME = "logistics_web"
USER_ID = "web_user"

SAMPLE_QUESTIONS = [
    {
        "label": "Classic (balanced)",
        "text": (
            "I run 3 warehouses: Dallas has 300 units, Atlanta 400, Denver 500. "
            "My stores need: Phoenix 250, Houston 350, Miami 400, Chicago 200.\n"
            "Cost per unit:\n"
            "- Dallas → Phoenix 8, Houston 3, Miami 9, Chicago 7\n"
            "- Atlanta → Phoenix 12, Houston 6, Miami 4, Chicago 6\n"
            "- Denver → Phoenix 5, Houston 7, Miami 13, Chicago 8\n"
            "What's the cheapest way to ship?"
        ),
    },
    {
        "label": "Shortage → triage",
        "text": (
            "Atlanta only has 200 units this week. Dallas has 300 and Denver 500. "
            "Stores still need: Phoenix 250, Houston 350, Miami 400, Chicago 200.\n"
            "Cost per unit:\n"
            "- Dallas → Phoenix 8, Houston 3, Miami 9, Chicago 7\n"
            "- Atlanta → Phoenix 12, Houston 6, Miami 4, Chicago 6\n"
            "- Denver → Phoenix 5, Houston 7, Miami 13, Chicago 8\n"
            "Plan the shipments."
        ),
    },
    {
        "label": "Closed route",
        "text": (
            "Load the basic US retail sample scenario, but the Atlanta → Miami route is closed this week. "
            "Plan the cheapest shipments."
        ),
    },
]

session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)
app = FastAPI(title="Logistics agent")


class RunRequest(BaseModel):
    question: str
    session_id: str | None = None


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/samples")
async def samples():
    return JSONResponse({"samples": SAMPLE_QUESTIONS, "model": MODEL})


def _line(payload: dict) -> bytes:
    return (json.dumps(payload, default=str) + "\n").encode()


@app.post("/api/run")
async def run(req: RunRequest):
    session = None
    if req.session_id:
        session = await session_service.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=req.session_id)
    if session is None:
        session = await session_service.create_session(app_name=APP_NAME, user_id=USER_ID)

    async def stream():
        yield _line({"type": "session", "session_id": session.id, "model": MODEL})
        message = types.Content(role="user", parts=[types.Part(text=req.question)])
        try:
            async for event in runner.run_async(user_id=USER_ID, session_id=session.id, new_message=message):
                for call in event.get_function_calls():
                    yield _line({"type": "tool_call", "id": call.id, "name": call.name, "args": call.args or {}})
                for resp in event.get_function_responses():
                    yield _line({"type": "tool_result", "id": resp.id, "name": resp.name, "response": resp.response})
                if event.partial or not event.content or not event.content.parts:
                    continue
                text = "".join(p.text for p in event.content.parts if p.text and not p.thought)
                if text.strip():
                    yield _line({"type": "text", "text": text, "final": event.is_final_response()})
        except Exception as exc:  # surface model/API errors (bad key, quota) in the page instead of a dead stream
            yield _line({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        yield _line({"type": "done"})

    return StreamingResponse(stream(), media_type="application/x-ndjson")
