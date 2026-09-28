"""Fixed, loopback-only runtime wiring for the one-user Dots. dashboard.

Importing this module must not contact Neo4j, Docker, systemd, or Windows.
The controller is intentionally independent of the services it controls so
the browser remains available after an explicit stop or a failed startup.
"""
from __future__ import annotations

from pathlib import Path

from dots.founder_graph_runtime import create_neo4j_driver_from_env
from dots.local_api_adapter import FixedSystemdUserApiAdapter
from dots.local_control_adapters import DockerNeo4jAdapter, FixedSystemdUserServiceAdapter
from dots.local_control_runner import SubprocessCommandRunner
from dots.local_dashboard_app import create_local_dashboard_app
from dots.local_dashboard_driver import managed_neo4j_driver
from dots.local_graph_proxy import LocalGraphSearchProxy
from dots.local_overview import Neo4jOverviewStore, OverviewStore, StoredOverviewNode
from dots.local_home import Neo4jHomeStore, HomeStore, LocalAssetWriter, LocalIdeaWriter
from dots.local_record_lifecycle import LocalRecordLifecycleWriter
from dots.local_graph_view import GraphViewStore, Neo4jGraphViewStore
from dots.local_graph_provenance import Neo4jGraphProvenanceStore, read_local_graph_provenance
from dots.local_self_intro import Neo4jSelfIntroductionWriter
from dots.founder_graph_neo4j import Neo4jGraphGateway
from dots.local_stop_intent import WindowsStopIntentAdapter


LIVE_DOCKER_CLI = "/mnt/c/Users/hp/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
LIVE_OWNER_ID = "owner-mvp"
DEFAULT_DIST_DIR = Path(__file__).resolve().parents[2] / "dist"


class OnDemandNeo4jOverviewStore(OverviewStore):
    """Open a read-only overview connection only when the DB is running."""

    def read_overview(self, owner_id: str) -> tuple[StoredOverviewNode, ...]:
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            store = Neo4jOverviewStore(driver)
            return tuple(store.read_overview(owner_id))


class OnDemandNeo4jHomeStore(HomeStore):
    def read_home(self, owner_id: str):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return Neo4jHomeStore(driver).read_home(owner_id)

    def read_briefs(self, owner_id: str):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return Neo4jHomeStore(driver).read_briefs(owner_id)

    def read_citations(self, owner_id: str, evidence_ids):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return Neo4jHomeStore(driver).read_citations(owner_id, evidence_ids)


class OnDemandNeo4jGraphViewStore(GraphViewStore):
    def read_nodes(self, owner_id: str):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return Neo4jGraphViewStore(driver).read_nodes(owner_id)

    def read_edges(self, owner_id: str, ids):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return Neo4jGraphViewStore(driver).read_edges(owner_id, ids)

    def read_facet_region(self, owner_id: str, facet_id: str, depth: int):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return Neo4jGraphViewStore(driver).read_facet_region(owner_id, facet_id, depth)

    def read_provenance(self, assertion_id: str, owner_id: str):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            store = Neo4jGraphProvenanceStore(driver, owner_id=owner_id)
            return read_local_graph_provenance(store, assertion_id=assertion_id, owner_id=owner_id)


class OnDemandAssetWriter:
    def save(self, asset_id: str, *, name: str, description: str,
             expected_revision: int, idempotency_key: str):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return LocalAssetWriter(Neo4jGraphGateway(driver, LIVE_OWNER_ID)).save(
                asset_id, name=name, description=description,
                expected_revision=expected_revision, idempotency_key=idempotency_key,
            )


class OnDemandIdeaWriter:
    def save(self, idea_id: str, *, title: str, description: str,
             expected_revision: int, idempotency_key: str):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return LocalIdeaWriter(Neo4jGraphGateway(driver, LIVE_OWNER_ID)).save(
                idea_id, title=title, description=description,
                expected_revision=expected_revision, idempotency_key=idempotency_key,
            )


class OnDemandRecordLifecycleWriter:
    def transition(self, kind: str, action: str, record_id: str, *,
                   expected_revision: int, idempotency_key: str):
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            return LocalRecordLifecycleWriter(Neo4jGraphGateway(driver, LIVE_OWNER_ID)).transition(
                kind, action, record_id,
                expected_revision=expected_revision,
                idempotency_key=idempotency_key,
            )


class OnDemandSelfIntroductionWriter:
    def save(self, owner_id: str, text: str, expected_id: str | None, idempotency_key: str) -> str:
        with managed_neo4j_driver(create_neo4j_driver_from_env) as driver:
            writer = Neo4jSelfIntroductionWriter(Neo4jHomeStore(driver), Neo4jGraphGateway(driver, owner_id))
            return writer.save(owner_id, text, expected_id, idempotency_key)

def create_runtime_app(*, dist_dir: Path = DEFAULT_DIST_DIR):
    """Construct the fixed production app without starting any child service."""
    # Docker's graceful stop allowance is 60 seconds, so the command runner
    # must outlive it while still bounding a stuck CLI process.
    docker_runner = SubprocessCommandRunner((LIVE_DOCKER_CLI,), timeout_seconds=90)
    service_runner = SubprocessCommandRunner(("systemctl",), timeout_seconds=30)
    return create_local_dashboard_app(
        database_adapter=DockerNeo4jAdapter(
            docker_runner,
            docker_cli=LIVE_DOCKER_CLI,
        ),
        api_adapter=FixedSystemdUserApiAdapter(service_runner),
        tunnel_adapter=FixedSystemdUserServiceAdapter(service_runner),
        intent_adapter=WindowsStopIntentAdapter(),
        overview_store=OnDemandNeo4jOverviewStore(),
        home_store=OnDemandNeo4jHomeStore(),
        graph_view_store=OnDemandNeo4jGraphViewStore(),
        self_intro_writer=OnDemandSelfIntroductionWriter(),
        asset_writer=OnDemandAssetWriter(),
        idea_writer=OnDemandIdeaWriter(),
        record_lifecycle_writer=OnDemandRecordLifecycleWriter(),
        overview_owner_id=LIVE_OWNER_ID,
        dist_dir=dist_dir,
        graph_proxy=LocalGraphSearchProxy(),
    )


app = create_runtime_app()
