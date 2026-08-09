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
from .account_privacy import InMemoryAccountPrivacyRepository
from .market_report import InMemoryMarketReportRepository, MarketReportRequest, MarketReportResponse
from .project_knowledge import (
    InMemoryProjectKnowledgeRepository,
    KnowledgeCandidatesResponse,
    KnowledgeGrantInput,
    KnowledgeGrantResponse,
    KnowledgeReferenceResponse,
    ProjectKnowledgeInput,
    ProjectKnowledgeResponse,
)
from .research_orchestrator import FakeSource, ResearchOrchestrator, Source
from .runtime import RuntimeAdapter, RuntimeFault, create_runtime


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


def create_app(
    repository: InMemoryDecisionRepository | None = None,
    runtime: RuntimeAdapter | None = None,
    market_report_repository: InMemoryMarketReportRepository | None = None,
    account_privacy_repository: InMemoryAccountPrivacyRepository | None = None,
    project_knowledge_repository: InMemoryProjectKnowledgeRepository | None = None,
) -> FastAPI:
    app = FastAPI(title="Kadode API", version="0.1.0")
    decision_repository = repository or InMemoryDecisionRepository()
    report_repository = market_report_repository or InMemoryMarketReportRepository()
    privacy_repository = account_privacy_repository or InMemoryAccountPrivacyRepository.seeded()
    knowledge_repository = project_knowledge_repository or InMemoryProjectKnowledgeRepository()
    runtime_adapter = runtime or create_runtime()

    def runtime_owner(x_local_owner_id: str | None = Header(default=None, alias="X-Local-Owner-Id")) -> str:
        try:
            return runtime_adapter.authenticate(x_local_owner_id)
        except RuntimeFault as error:
            raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error

    def runtime_call(operation):
        try:
            return operation()
        except RuntimeFault as error:
            raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "kadode-api"}

    @app.get("/v1/runtime/status")
    def runtime_status() -> dict[str, object]:
        return {"profile": runtime_adapter.profile, "services": runtime_adapter.service_status()}

    @app.get("/v1/account/export")
    def export_account(owner_id: Annotated[str, Depends(local_owner_context)]) -> dict[str, object]:
        return privacy_repository.export(owner_id)

    @app.post("/v1/account/deletion", status_code=status.HTTP_202_ACCEPTED)
    def delete_account(owner_id: Annotated[str, Depends(local_owner_context)]) -> dict[str, object]:
        return privacy_repository.delete(owner_id)

    @app.get("/v1/runtime/objects/{object_id}")
    def get_runtime_object(object_id: str, owner_id: Annotated[str, Depends(runtime_owner)]) -> dict[str, str]:
        return runtime_call(lambda: runtime_adapter.read_object(owner_id, object_id))

    @app.delete("/v1/runtime/objects/{object_id}")
    def delete_runtime_object(object_id: str, owner_id: Annotated[str, Depends(runtime_owner)]) -> dict[str, str]:
        return runtime_call(lambda: runtime_adapter.delete_object(owner_id, object_id))

    @app.post("/v1/runtime/ai")
    def generate_runtime_ai(request: dict[str, str], owner_id: Annotated[str, Depends(runtime_owner)]) -> dict[str, str]:
        return runtime_call(lambda: runtime_adapter.generate(owner_id, request.get("prompt", "")))

    @app.post("/v1/runtime/billing/consume")
    def consume_runtime_billing(owner_id: Annotated[str, Depends(runtime_owner)]) -> dict[str, int]:
        return runtime_call(lambda: runtime_adapter.consume(owner_id))

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

    @app.post("/v1/market-reports", response_model=MarketReportResponse, status_code=status.HTTP_201_CREATED)
    def create_market_report(
        request: MarketReportRequest, owner_id: Annotated[str, Depends(local_owner_context)]
    ) -> MarketReportResponse:
        try:
            return report_repository.create(owner_id, request)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "market_report_evidence_reference_invalid"}) from error

    @app.get("/v1/market-reports/{report_id}", response_model=MarketReportResponse)
    def get_market_report(report_id: str, owner_id: Annotated[str, Depends(local_owner_context)]) -> MarketReportResponse:
        report = report_repository.get(owner_id, report_id)
        if report is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "market_report_not_found"})
        return report

    @app.post("/v1/market-reports/{report_id}/card-update/approve", response_model=MarketReportResponse)
    def approve_card_update(report_id: str, owner_id: Annotated[str, Depends(local_owner_context)]) -> MarketReportResponse:
        report = report_repository.approve(owner_id, report_id)
        if report is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "market_report_not_found"})
        return report

    @app.post("/v1/project-knowledge", response_model=ProjectKnowledgeResponse, status_code=status.HTTP_201_CREATED)
    def create_project_knowledge(
        request: ProjectKnowledgeInput, owner_id: Annotated[str, Depends(local_owner_context)]
    ) -> ProjectKnowledgeResponse:
        return knowledge_repository.create(owner_id, request)

    @app.post("/v1/project-knowledge/grants", response_model=KnowledgeGrantResponse, status_code=status.HTTP_201_CREATED)
    def grant_project_knowledge(
        request: KnowledgeGrantInput, owner_id: Annotated[str, Depends(local_owner_context)]
    ) -> KnowledgeGrantResponse:
        grant = knowledge_repository.grant(owner_id, request)
        if grant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "project_knowledge_not_found"})
        return grant

    @app.post("/v1/project-knowledge/grants/{grant_id}/revoke", response_model=KnowledgeGrantResponse)
    def revoke_project_knowledge_grant(grant_id: str, owner_id: Annotated[str, Depends(local_owner_context)]) -> KnowledgeGrantResponse:
        from uuid import UUID
        try:
            grant = knowledge_repository.revoke(owner_id, UUID(grant_id))
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "knowledge_grant_not_found"}) from error
        if grant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "knowledge_grant_not_found"})
        return grant

    @app.delete("/v1/project-knowledge/{knowledge_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_project_knowledge(knowledge_id: str, owner_id: Annotated[str, Depends(local_owner_context)]) -> None:
        from uuid import UUID
        try:
            deleted = knowledge_repository.delete(owner_id, UUID(knowledge_id))
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "project_knowledge_not_found"}) from error
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "project_knowledge_not_found"})

    @app.get("/v1/project-knowledge/candidates", response_model=KnowledgeCandidatesResponse)
    def project_knowledge_candidates(target_project_id: str, owner_id: Annotated[str, Depends(local_owner_context)]) -> KnowledgeCandidatesResponse:
        return knowledge_repository.candidates(owner_id, target_project_id)

    @app.get("/v1/project-knowledge/references/{knowledge_id}", response_model=KnowledgeReferenceResponse)
    def project_knowledge_reference(knowledge_id: str, target_project_id: str, owner_id: Annotated[str, Depends(local_owner_context)]) -> KnowledgeReferenceResponse:
        from uuid import UUID
        try:
            return knowledge_repository.reference_status(owner_id, UUID(knowledge_id), target_project_id)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "project_knowledge_not_found"}) from error

    return app


app = create_app()
