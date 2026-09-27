"""Composition factory for the localhost-only Dots. dashboard application."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from dots.local_control import LocalControl, ServiceAdapter, create_local_control_app
from dots.local_dashboard_host import mount_local_dashboard
from dots.local_graph_proxy import LocalGraphSearchProxy, create_local_graph_search_router
from dots.local_overview import OverviewStore
from dots.local_home import HomeStore, LocalAssetWriter
from dots.local_record_lifecycle import LocalRecordLifecycleWriter
from dots.local_graph_view import GraphViewStore
from dots.local_self_intro import SelfIntroductionWriter


LOCAL_DASHBOARD_HOST = "localhost:8765"
LOCAL_DASHBOARD_ORIGIN = "http://localhost:8765"
LOCAL_DASHBOARD_BIND = "127.0.0.1"
LOCAL_DASHBOARD_START_ORDER = ("database", "intent", "api", "tunnel")
LOCAL_DASHBOARD_STOP_ORDER = ("intent", "tunnel", "api", "database")


def create_local_dashboard_app(
    *,
    database_adapter: ServiceAdapter,
    api_adapter: ServiceAdapter,
    tunnel_adapter: ServiceAdapter,
    intent_adapter: ServiceAdapter,
    overview_store: OverviewStore,
    home_store: HomeStore | None = None,
    graph_view_store: GraphViewStore | None = None,
    self_intro_writer: SelfIntroductionWriter | None = None,
    asset_writer: LocalAssetWriter | None = None,
    record_lifecycle_writer: LocalRecordLifecycleWriter | None = None,
    overview_owner_id: str,
    dist_dir: str | Path,
    graph_proxy: LocalGraphSearchProxy | None = None,
) -> FastAPI:
    """Compose the fixed local control API, optional Graph proxy, and built UI.

    All runtime connections are injected. This function does not open a
    database connection, spawn a command, or contact a service.
    """
    control = LocalControl(
        {
            "database": database_adapter,
            "intent": intent_adapter,
            "api": api_adapter,
            "tunnel": tunnel_adapter,
        },
        expected_host=LOCAL_DASHBOARD_HOST,
        allowed_origin=LOCAL_DASHBOARD_ORIGIN,
        start_order=LOCAL_DASHBOARD_START_ORDER,
        stop_order=LOCAL_DASHBOARD_STOP_ORDER,
    )
    app = create_local_control_app(
        control,
        bind_host=LOCAL_DASHBOARD_BIND,
        overview_store=overview_store,
        home_store=home_store,
        graph_view_store=graph_view_store,
        self_intro_writer=self_intro_writer,
        asset_writer=asset_writer,
        record_lifecycle_writer=record_lifecycle_writer,
        overview_owner_id=overview_owner_id,
    )
    if graph_proxy is not None:
        app.include_router(
            create_local_graph_search_router(
                graph_proxy,
                expected_host=LOCAL_DASHBOARD_HOST,
                allowed_origin=LOCAL_DASHBOARD_ORIGIN,
            ),
        )
    mount_local_dashboard(
        app,
        dist_dir=dist_dir,
        expected_host=LOCAL_DASHBOARD_HOST,
        allowed_origin=LOCAL_DASHBOARD_ORIGIN,
    )
    return app
