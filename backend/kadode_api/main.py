from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel

from .decision_memory import (
    DecisionInput,
    DecisionNotFound,
    DecisionResponse,
    DecisionSearchResponse,
    InMemoryDecisionRepository,
)
from .research_orchestrator import FakeSource, ResearchOrchestrator, Source


orchestrator = ResearchOrchestrator({source: FakeSource() for source in Source})


class ResearchRunRequest(BaseModel):
    query: str
    selected_sources: list[Source]


def _owner(owner_id: str | None) -> str:
    if not owner_id:
        raise HTTPException(401, "local owner principal required")
    return owner_id


def local_owner_context(local_owner_id: Annotated[str | None, Header(alias="X-Local-Owner-Id")] = None) -> str:
    if local_owner_id is None or not local_owner_id.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "local_owner_required"})
    return local_owner_id.strip()


def create_app(repository: InMemoryDecisionRepository | None = None) -> FastAPI:
    app = FastAPI(title="Kadode API", version="0.1.0")
    decision_repository = repository or InMemoryDecisionRepository()

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

    @app.post("/v1/decisions", response_model=DecisionResponse, status_code=status.HTTP_201_CREATED)
    def create_decision(command: DecisionInput, owner_id: Annotated[str, Depends(local_owner_context)]) -> DecisionResponse:
        try:
            return decision_repository.create(owner_id, command)
        except DecisionNotFound as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "decision_not_found"}) from error

    @app.get("/v1/decisions/search", response_model=DecisionSearchResponse)
    def search_decisions(
        owner_id: Annotated[str, Depends(local_owner_context)],
        idea_id: Annotated[str, Query(min_length=1, max_length=200)],
        query: Annotated[str, Query(min_length=1, max_length=2000)],
    ) -> DecisionSearchResponse:
        return DecisionSearchResponse(decisions=decision_repository.search(owner_id, idea_id, query))

    return app


app = create_app()
