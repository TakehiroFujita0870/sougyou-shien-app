import os
from typing import Annotated, Any, Mapping

from fastapi import Depends, FastAPI, Header, HTTPException, status
from .founder_graph_mcp import McpReadError, McpReadSurface
from .founder_graph_mcp_write import McpWriteError, McpWriteSurface
from .founder_graph_read import GraphReadPort, GraphReadService
from .founder_graph_runtime import close_neo4j_driver, create_neo4j_driver_from_env, create_neo4j_graph_composition, create_relation_candidate_job_processor, resolve_graph_backend
from .founder_graph_write import GraphWritePort, InMemoryGraphWriteService
from .founder_graph_neo4j_write import Neo4jGraphWriteService, Neo4jIdeaBriefStore


def local_owner_context(local_owner_id: Annotated[str | None, Header(alias="X-Local-Owner-Id")] = None) -> str:
    if local_owner_id is None or not local_owner_id.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "local_owner_required"})
    return local_owner_id.strip()


def create_app(
    founder_graph_write_service: GraphWritePort | None = None,
    founder_graph_read_service: GraphReadPort | None = None,
    founder_graph_owner_id: str = "local-owner",
    founder_graph_candidate_processor: Any | None = None,
) -> FastAPI:
    app = FastAPI(title="Nebula API", version="0.1.0")
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
    brief_store = Neo4jIdeaBriefStore(graph_writes.gateway) if isinstance(graph_writes, Neo4jGraphWriteService) else None
    write_surface_options = {"brief_store": brief_store}
    if founder_graph_candidate_processor is not None:
        write_surface_options["candidate_processor"] = founder_graph_candidate_processor
    graph_write_mcp = McpWriteSurface(graph_writes, **write_surface_options)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "nebula-api"}

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
            response = {
                "operation": receipt.operation,
                "target_id": receipt.target_id,
                "target_type": receipt.target_type,
                "revision": receipt.revision,
                "idempotency_key": receipt.idempotency_key,
                "replayed": receipt.replayed,
                "source_revision_id": receipt.source_revision_id,
                "content_chunk_ids": receipt.content_chunk_ids,
            }
            proposal = getattr(receipt, "campaign_proposal", None)
            if isinstance(proposal, Mapping):
                proposal_fields = {
                    "purpose", "target_idea_id", "scope", "questions", "allowed_categories",
                    "external_sources", "trial_budget", "expires_at",
                    "authorization_snapshot_id", "authorization_revision",
                    "authorized", "status", "aggregate_revision",
                }
                response["campaign_proposal"] = {key: value for key, value in proposal.items() if key in proposal_fields}
            candidate_processing = getattr(receipt, "candidate_processing", None)
            if isinstance(candidate_processing, Mapping):
                response["candidate_processing"] = {
                    "state": candidate_processing.get("state"),
                    "error_code": candidate_processing.get("error_code"),
                }
            return response
        except McpWriteError as error:
            raise mcp_error(error) from error

    return app


def create_neo4j_app(
    driver: Any, owner_id: str, *, database: str = "neo4j",
    candidate_processor: Any | None = None,
) -> FastAPI:
    """Build the API with one explicit, persistent Neo4j composition.

    Driver construction, authentication, migration, and lifecycle remain the
    caller's responsibility.  This helper only wires the already-created
    driver into matching owner-scoped read and write ports.
    """

    composition = create_neo4j_graph_composition(driver, owner_id, database=database)
    processor = (
        candidate_processor if candidate_processor is not None
        else create_relation_candidate_job_processor(composition)
    )
    return create_app(
        founder_graph_write_service=composition.writes,
        founder_graph_read_service=composition.reads,
        founder_graph_owner_id=composition.gateway.owner_id,
        founder_graph_candidate_processor=processor,
    )


def create_configured_app() -> FastAPI:
    """Build the normal local app from the shared storage selection rule."""

    if resolve_graph_backend() == "memory":
        return create_app()
    owner_id = (os.environ.get("NEBULA_LOCAL_OWNER_ID") or "local-owner").strip() or "local-owner"
    database = os.environ.get("NEBULA_NEO4J_DATABASE", "neo4j").strip() or "neo4j"
    driver = create_neo4j_driver_from_env()
    try:
        app = create_neo4j_app(driver, owner_id, database=database)
    except BaseException:
        try:
            close_neo4j_driver(driver)
        except Exception:
            pass
        raise
    app.router.add_event_handler("shutdown", lambda: close_neo4j_driver(driver))
    return app


app = create_configured_app()
