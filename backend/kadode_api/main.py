from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from .decision_memory import (
    DecisionInput,
    DecisionNotFound,
    DecisionResponse,
    DecisionSearchResponse,
    InMemoryDecisionRepository,
)


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
