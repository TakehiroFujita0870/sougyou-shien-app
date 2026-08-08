from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .research_orchestrator import FakeSource, ResearchOrchestrator, Source

app = FastAPI(title="Kadode API", version="0.1.0")
orchestrator = ResearchOrchestrator({source: FakeSource() for source in Source})


class ResearchRunRequest(BaseModel):
    query: str
    selected_sources: list[Source]


def _owner(owner_id: str | None) -> str:
    if not owner_id:
        raise HTTPException(401, "local owner principal required")
    return owner_id

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "kadode-api"}


@app.post("/v1/research-runs")
def create_research_run(request: ResearchRunRequest, x_owner_id: str | None = Header(default=None)) -> dict[str, object]:
    if not request.selected_sources:
        raise HTTPException(422, "select at least one source")
    return orchestrator.create(_owner(x_owner_id), request.query, tuple(request.selected_sources)).payload()


@app.get("/v1/research-runs/{run_id}")
def get_research_run(run_id: str, x_owner_id: str | None = Header(default=None)) -> dict[str, object]:
    run = orchestrator.get(_owner(x_owner_id), run_id)
    if not run:
        raise HTTPException(404, "research run not found")
    return run.payload()


@app.post("/v1/research-runs/{run_id}/retry")
def retry_research_run(run_id: str, x_owner_id: str | None = Header(default=None)) -> dict[str, object]:
    run = orchestrator.retry(_owner(x_owner_id), run_id)
    if not run:
        raise HTTPException(404, "research run not found")
    return run.payload()
