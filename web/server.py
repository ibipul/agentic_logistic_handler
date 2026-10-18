"""Small web front end for the logistics agent.

Run from the repo root:  uvicorn web.server:app --port 8080
"""

import html
import json
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
# override=True: the key in logistics_agent/.env wins over any GOOGLE_API_KEY / Vertex settings already in the shell.
load_dotenv(ROOT / "logistics_agent" / ".env", override=True)

from google.adk.runners import Runner  # noqa: E402  (needs the API key loaded first)
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from logistics_agent.agent import MODEL, root_agent  # noqa: E402
from logistics_agent.problems import PROBLEM_TYPES  # noqa: E402
from logistics_agent.samples import SAMPLES as SAMPLES_BY_NAME  # noqa: E402

APP_NAME = "logistics_web"
USER_ID = "web_user"

# Sample problems for the page's side pane, grouped by problem type in registry order.
SAMPLES = [
    {"name": name, "problem_type": sample["problem_type"], "label": sample["label"],
     "description": sample["description"], "text": sample["question"]}
    for key in PROBLEM_TYPES
    for name, sample in SAMPLES_BY_NAME.items()
    if sample["problem_type"] == key
]
TYPES = {key: {"label": t["label"], "short": t["short"], "input": t["input"], "tools": t["tools"]}
         for key, t in PROBLEM_TYPES.items()}

session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)
app = FastAPI(title="Logistics agent")


class RunRequest(BaseModel):
    question: str
    session_id: str | None = None


@app.get("/")
async def index():
    # Prefill the question box with the first sample on first load, without waiting for JavaScript.
    page = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(page.replace("{{DEFAULT_QUESTION}}", html.escape(SAMPLES[0]["text"])))


@app.get("/api/samples")
async def samples():
    return JSONResponse({"samples": SAMPLES, "problem_types": TYPES, "model": MODEL})


# Gemini's thought summaries sometimes open with a line about the summary itself
# ("Okay, here's my interpretation of that thought process, ..."). Drop that line; keep the reasoning.
_SUMMARY_PREAMBLE = re.compile(
    r"^\s*(okay|ok|alright)?[,\s]*here'?s\b[^\n]*\b(summary|interpretation|thought process|thinking)\b[^\n]*\n+",
    re.IGNORECASE,
)


def _clean_thought(text: str) -> str:
    return _SUMMARY_PREAMBLE.sub("", text, count=1).strip()


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
                if event.partial:
                    continue
                parts = (event.content.parts if event.content else None) or []
                # Reasoning first, so the timeline reads "why" before the tool call it led to.
                thought = _clean_thought("".join(p.text for p in parts if p.text and p.thought))
                if thought.strip():
                    yield _line({"type": "thought", "text": thought})
                for call in event.get_function_calls():
                    yield _line({"type": "tool_call", "id": call.id, "name": call.name, "args": call.args or {}})
                for resp in event.get_function_responses():
                    yield _line({"type": "tool_result", "id": resp.id, "name": resp.name, "response": resp.response})
                text = "".join(p.text for p in parts if p.text and not p.thought)
                if text.strip():
                    yield _line({"type": "text", "text": text, "final": event.is_final_response()})
        except Exception as exc:  # surface model/API errors (bad key, quota) in the page instead of a dead stream
            yield _line({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        yield _line({"type": "done"})

    return StreamingResponse(stream(), media_type="application/x-ndjson")
