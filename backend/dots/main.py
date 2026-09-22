import os
from typing import Annotated, Any

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
from .project_dossier import DossierRequest, ProjectDossier, assemble_dossier
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
from .founder_graph_mcp import McpReadError, McpReadSurface
from .founder_graph_mcp_write import McpWriteError, McpWriteSurface
from .founder_graph_read import GraphReadPort, GraphReadService
from .founder_graph_runtime import create_neo4j_driver_from_env, create_neo4j_graph_composition, resolve_graph_backend
from .founder_graph_write import GraphWritePort, InMemoryGraphWriteService


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
    founder_graph_write_service: GraphWritePort | None = None,
    founder_graph_read_service: GraphReadPort | None = None,
    founder_graph_owner_id: str = "local-owner",
) -> FastAPI:
    app = FastAPI(title="Dots. API", version="0.1.0")
    decision_repository = repository or InMemoryDecisionRepository()
    report_repository = market_report_repository or InMemoryMarketReportRepository()
    privacy_repository = account_privacy_repository or InMemoryAccountPrivacyRepository.seeded()
    knowledge_repository = project_knowledge_repository or InMemoryProjectKnowledgeRepository()
    runtime_adapter = runtime or create_runtime()
    graph_writes = founder_graph_write_service or InMemoryGraphWriteService(founder_graph_owner_id)
    if graph_writes.owner_id != founder_graph_owner_id:
        raise ValueError("founder_graph_write_service owner must match founder_graph_owner_id")
    if founder_graph_read_service is None:
        if not isinstance(graph_writes, InMemoryGraphWriteService):
            raise ValueError("a persistent founder_graph_write_service requires an explicit founder_graph_read_service")
        graph_reads = GraphReadService(graph_writes)
    else:
        graph_reads = founder_graph_read_service
    try:
        read_owner_id = graph_reads.owner_id
    except AttributeError as error:
        raise ValueError("founder_graph_read_service must expose owner_id") from error
    if read_owner_id != graph_writes.owner_id:
        raise ValueError("founder_graph_read_service owner must match founder_graph_owner_id")
    graph_read_mcp = McpReadSurface(graph_reads)
    graph_write_mcp = McpWriteSurface(graph_writes)

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
        return {"status": "ok", "service": "dots-api"}

    @app.get("/v1/runtime/status")
    def runtime_status() -> dict[str, object]:
        return {"profile": runtime_adapter.profile, "services": runtime_adapter.service_status()}

    def mcp_error(error: McpReadError | McpWriteError) -> HTTPException:
        status_by_code = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "owner_mismatch": status.HTTP_403_FORBIDDEN,
            "idempotency_conflict": status.HTTP_409_CONFLICT,
            "revision_conflict": status.HTTP_409_CONFLICT,
            "read_timeout": status.HTTP_504_GATEWAY_TIMEOUT,
            "unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
            "unknown_tool": status.HTTP_404_NOT_FOUND,
        }
        return HTTPException(
            status_code=status_by_code.get(error.code, status.HTTP_422_UNPROCESSABLE_ENTITY),
            detail={"code": error.code, "message": error.message},
        )

    @app.get("/v1/founder-graph/mcp/tools")
    def founder_graph_mcp_tools(owner_id: Annotated[str, Depends(local_owner_context)]) -> dict[str, object]:
        if owner_id != graph_writes.owner_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "owner_mismatch"})
        return {"read": graph_read_mcp.tool_definitions(), "write": graph_write_mcp.tool_definitions()}

    @app.post("/v1/founder-graph/mcp/read/{tool_name}")
    def founder_graph_mcp_read(
        tool_name: str,
        request: dict[str, Any],
        owner_id: Annotated[str, Depends(local_owner_context)],
    ) -> dict[str, Any]:
        try:
            return graph_read_mcp.call(tool_name, request, owner_id=owner_id)
        except McpReadError as error:
            raise mcp_error(error) from error

    @app.post("/v1/founder-graph/mcp/write/{tool_name}")
    def founder_graph_mcp_write(
        tool_name: str,
        request: dict[str, Any],
        owner_id: Annotated[str, Depends(local_owner_context)],
    ) -> dict[str, Any]:
        try:
            receipt = graph_write_mcp.call(tool_name, request, owner_id=owner_id)
            return {
                "operation": receipt.operation,
                "target_id": receipt.target_id,
                "target_type": receipt.target_type,
                "revision": receipt.revision,
                "idempotency_key": receipt.idempotency_key,
                "replayed": receipt.replayed,
            }
        except McpWriteError as error:
            raise mcp_error(error) from error

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

    @app.post("/v1/projects/{project_id}/dossier", response_model=ProjectDossier)
    def project_dossier(
        project_id: str, request: DossierRequest, owner_id: Annotated[str, Depends(local_owner_context)]
    ) -> ProjectDossier:
        if request.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "project_id_mismatch"})
        report = report_repository.get(owner_id, request.market_report_id) if request.market_report_id else None
        if request.market_report_id and (report is None or report.idea_id != project_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "market_report_not_found"})
        return assemble_dossier(request, report)

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


def create_neo4j_app(driver: Any, owner_id: str, *, database: str = "neo4j") -> FastAPI:
    """Build the API with one explicit, persistent Neo4j composition.

    Driver construction, authentication, migration, and lifecycle remain the
    caller's responsibility.  This helper only wires the already-created
    driver into matching owner-scoped read and write ports.
    """

    composition = create_neo4j_graph_composition(driver, owner_id, database=database)
    return create_app(
        founder_graph_write_service=composition.writes,
        founder_graph_read_service=composition.reads,
        founder_graph_owner_id=composition.gateway.owner_id,
    )


def create_configured_app() -> FastAPI:
    """Build the normal local app from the shared storage selection rule."""

    if resolve_graph_backend() == "memory":
        return create_app()
    owner_id = (os.environ.get("DOTS_LOCAL_OWNER_ID") or "local-owner").strip() or "local-owner"
    database = os.environ.get("DOTS_NEO4J_DATABASE", "neo4j").strip() or "neo4j"
    return create_neo4j_app(create_neo4j_driver_from_env(), owner_id, database=database)


app = create_configured_app()
