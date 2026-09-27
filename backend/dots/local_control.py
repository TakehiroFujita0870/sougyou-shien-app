"""Loopback-restricted, fixed-action local lifecycle control API.

This module deliberately contains no process, Docker, or systemd integration.
Callers must inject trusted adapters and bind the server to a loopback address.
Without ``local_secret``, Host/Origin/CSRF checks protect browser requests but do
not authenticate local processes or distinguish Windows user accounts.
"""
from __future__ import annotations

import hmac
import ipaddress
import secrets
import threading
from collections.abc import Mapping, Sequence
from typing import Protocol

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from dots.local_overview import COUNT_BASIS, OverviewResult, OverviewStore, read_local_overview
from dots.local_home import HomeStore, LocalAssetWriter, read_local_home
from dots.founder_graph_write import GraphWriteNotFoundError, IdempotencyConflictError, RevisionConflictError
from dots.local_graph_view import GraphViewStore, read_local_facet_region, read_local_graph
from dots.local_graph_provenance import GraphProvenanceNotFound
from dots.local_self_intro import SelfIntroductionConflict, SelfIntroductionWriter


class ServiceAdapter(Protocol):
    """Read status and perform one fixed lifecycle operation."""

    def status(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class ControlAction(BaseModel):
    action: str


class SelfIntroductionEdit(BaseModel):
    text: str
    expected_id: str | None = None


class AssetEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=4000)
    expected_revision: StrictInt = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)


class LocalControl:
    """Small control plane; an optional secret and fixed target order are host supplied."""

    def __init__(
        self,
        adapters: Mapping[str, ServiceAdapter],
        *,
        local_secret: str | None = None,
        expected_host: str,
        allowed_origin: str,
        start_order: Sequence[str],
        stop_order: Sequence[str],
    ) -> None:
        if local_secret == "":
            raise ValueError("local_secret cannot be empty")
        if not expected_host or not allowed_origin:
            raise ValueError("expected_host and allowed_origin are required")
        if set(start_order) != set(adapters) or set(stop_order) != set(adapters):
            raise ValueError("lifecycle orders must include each fixed adapter exactly once")
        if len(start_order) != len(set(start_order)) or len(stop_order) != len(set(stop_order)):
            raise ValueError("lifecycle orders cannot contain duplicates")
        self.adapters = dict(adapters)
        self.local_secret = local_secret
        self.expected_host = expected_host
        self.allowed_origin = allowed_origin
        self.start_order = tuple(start_order)
        self.stop_order = tuple(stop_order)
        self.csrf_token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._idempotency: dict[str, tuple[str, dict[str, object]]] = {}

    def status(self) -> dict[str, object]:
        result: dict[str, object] = {"controller": "running", "csrf_token": self.csrf_token}
        states: dict[str, str] = {}
        for name, adapter in self.adapters.items():
            try:
                states[name] = adapter.status()
            except Exception:
                states[name] = "unavailable"
        result["services"] = states
        return result

    def operate(self, action: str, key: str) -> dict[str, object]:
        if action not in {"start", "stop"}:
            raise HTTPException(status_code=404, detail="Unknown action")
        with self._lock:
            if key in self._idempotency:
                original_action, cached = self._idempotency[key]
                if original_action != action:
                    raise HTTPException(status_code=409, detail="Idempotency-Key was used for a different action")
                return {**cached, "replayed": True}
            order = self.start_order if action == "start" else self.stop_order
            stages: list[dict[str, str]] = []
            method = action
            failed = False
            for name in order:
                try:
                    getattr(self.adapters[name], method)()
                    stages.append({"service": name, "status": "completed"})
                except Exception:
                    stages.append({"service": name, "status": "failed"})
                    failed = True
                    break
            result: dict[str, object] = {
                "action": action,
                "status": "partial_failure" if failed else "completed",
                "stages": stages,
                "services": {name: self._safe_status(adapter) for name, adapter in self.adapters.items()},
                "replayed": False,
            }
            # Cache even partial failures: retries with the same key must not
            # repeat side effects. A new explicit attempt must use a new key.
            self._idempotency[key] = (action, result)
            return result

    @staticmethod
    def _safe_status(adapter: ServiceAdapter) -> str:
        try:
            return adapter.status()
        except Exception:
            return "unavailable"


def create_local_control_app(
    control: LocalControl,
    *,
    bind_host: str = "127.0.0.1",
    overview_store: OverviewStore | None = None,
    overview_owner_id: str | None = None,
    home_store: HomeStore | None = None,
    graph_view_store: GraphViewStore | None = None,
    self_intro_writer: SelfIntroductionWriter | None = None,
    asset_writer: LocalAssetWriter | None = None,
) -> FastAPI:
    """Create the API and reject non-loopback deployment configurations."""
    try:
        if not ipaddress.ip_address(bind_host).is_loopback:
            raise ValueError("control service must bind to a loopback address")
    except ValueError as error:
        if str(error) == "control service must bind to a loopback address":
            raise
        raise ValueError("bind_host must be a loopback IP address") from error

    app = FastAPI(title="Dots. Local Control", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def prevent_sensitive_response_caching(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    async def authorize(
        request: Request,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> None:
        peer = request.client.host if request.client else ""
        try:
            if not ipaddress.ip_address(peer).is_loopback:
                raise HTTPException(status_code=403, detail="Loopback clients only")
        except ValueError as error:
            raise HTTPException(status_code=403, detail="Loopback clients only") from error
        if request.headers.get("host") != control.expected_host:
            raise HTTPException(status_code=403, detail="Invalid host")
        origin = request.headers.get("origin")
        if origin is not None and origin != control.allowed_origin:
            raise HTTPException(status_code=403, detail="Invalid origin")
        if control.local_secret is not None:
            expected_auth = f"Bearer {control.local_secret}"
            if not authorization or not hmac.compare_digest(authorization, expected_auth):
                raise HTTPException(status_code=401, detail="Local authentication required")
        if request.method != "GET":
            if origin != control.allowed_origin:
                raise HTTPException(status_code=403, detail="Invalid origin")
            if not x_csrf_token or not hmac.compare_digest(x_csrf_token, control.csrf_token):
                raise HTTPException(status_code=403, detail="Invalid CSRF token")

    @app.get("/api/status")
    async def get_status(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
        await authorize(request, authorization)
        return control.status()

    @app.get("/api/overview")
    async def get_overview(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await authorize(request, authorization)
        database = control.adapters.get("database")
        if (
            overview_store is None
            or not isinstance(overview_owner_id, str)
            or not overview_owner_id.strip()
            or database is None
        ):
            result = _failed_overview_result()
        else:
            try:
                storage_status = database.status()
            except Exception:
                storage_status = "unavailable"
            try:
                result = read_local_overview(
                    overview_store,
                    owner_id=overview_owner_id,
                    storage_status=storage_status,
                )
            except Exception:
                result = _failed_overview_result()
        return JSONResponse(
            status_code=503 if result.status == "failed" else 200,
            content=jsonable_encoder(result),
        )

    @app.get("/api/home")
    async def get_home(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        await authorize(request, authorization)
        database = control.adapters.get("database")
        if home_store is None or not overview_owner_id or database is None:
            result = {"status": "failed", "ideas": [], "assets": [], "profile": None}
        else:
            try:
                storage_status = database.status()
            except Exception:
                storage_status = "unavailable"
            result = read_local_home(home_store, owner_id=overview_owner_id, storage_status=storage_status)
        return JSONResponse(status_code=503 if result["status"] == "failed" else 200, content=result)

    @app.get("/api/graph")
    async def get_graph(request: Request, authorization: str | None = Header(default=None)) -> JSONResponse:
        await authorize(request, authorization)
        database = control.adapters.get("database")
        if graph_view_store is None or not overview_owner_id or database is None:
            result = {"status": "failed", "nodes": [], "edges": [], "truncated": False}
        else:
            try:
                storage_status = database.status()
            except Exception:
                storage_status = "unavailable"
            result = read_local_graph(graph_view_store, owner_id=overview_owner_id, storage_status=storage_status)
        return JSONResponse(status_code=503 if result["status"] == "failed" else 200, content=result)

    @app.get("/api/graph/facet-region")
    async def get_facet_region(
        request: Request,
        facet_id: str,
        depth: int = 0,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await authorize(request, authorization)
        database = control.adapters.get("database")
        if graph_view_store is None or not overview_owner_id or database is None:
            result = {"status": "failed", "facet_id": facet_id, "depth": depth, "hits": []}
        else:
            try:
                storage_status = database.status()
            except Exception:
                storage_status = "unavailable"
            result = read_local_facet_region(
                graph_view_store,
                owner_id=overview_owner_id,
                facet_id=facet_id,
                depth=depth,
                storage_status=storage_status,
            )
        return JSONResponse(status_code=503 if result["status"] == "failed" else 200, content=result)

    @app.get("/api/graph/semantic-edges/{assertion_id}/provenance")
    async def get_semantic_edge_provenance(
        assertion_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        await authorize(request, authorization)
        database = control.adapters.get("database")
        read = getattr(graph_view_store, "read_provenance", None) if graph_view_store is not None else None
        if not overview_owner_id or database is None:
            return JSONResponse(status_code=503, content={"status": "failed"})
        try:
            storage_status = database.status()
        except Exception:
            storage_status = "unavailable"
        try:
            if storage_status == "stopped":
                result = {"status": "stopped", "assertion_id": assertion_id, "section": None, "evidence": []}
            elif storage_status != "running":
                return JSONResponse(status_code=503, content={"status": "failed"})
            elif not callable(read):
                return JSONResponse(status_code=503, content={"status": "failed"})
            else:
                result = read(assertion_id, owner_id=overview_owner_id)
        except GraphProvenanceNotFound:
            raise HTTPException(status_code=404, detail="Provenance was not found") from None
        except ValueError:
            raise HTTPException(status_code=404, detail="Provenance was not found") from None
        except Exception:
            return JSONResponse(status_code=503, content={"status": "failed"})
        return JSONResponse(content=result)

    @app.put("/api/assets/{asset_id}")
    async def save_asset(
        asset_id: str, request: Request, payload: AssetEdit,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> JSONResponse:
        await authorize(request, authorization, x_csrf_token)
        if asset_writer is None or not overview_owner_id:
            raise HTTPException(status_code=503, detail="Asset editing is unavailable")
        try:
            receipt = asset_writer.save(asset_id, name=payload.name, description=payload.description,
                                        expected_revision=payload.expected_revision,
                                        idempotency_key=payload.idempotency_key)
        except GraphWriteNotFoundError:
            raise HTTPException(status_code=404, detail="Asset was not found") from None
        except (RevisionConflictError, IdempotencyConflictError):
            raise HTTPException(status_code=409, detail="Asset changed; reload before saving") from None
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid asset edit") from None
        except Exception:
            raise HTTPException(status_code=503, detail="Could not save asset") from None
        return JSONResponse(content={"id": receipt.target_id, "revision": receipt.revision, "replayed": receipt.replayed})

    @app.post("/api/self-introduction")
    async def save_self_introduction(
        request: Request,
        payload: SelfIntroductionEdit,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None),
    ) -> JSONResponse:
        await authorize(request, authorization, x_csrf_token)
        if not idempotency_key or len(idempotency_key) > 128 or self_intro_writer is None or not overview_owner_id:
            raise HTTPException(status_code=400, detail="Invalid local edit")
        if not payload.text.strip() or len(payload.text) > 4000:
            raise HTTPException(status_code=400, detail="Invalid self introduction")
        try:
            identity = self_intro_writer.save(overview_owner_id, payload.text, payload.expected_id, idempotency_key)
        except SelfIntroductionConflict as error:
            raise HTTPException(status_code=409, detail="Self introduction changed; reload before saving") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid self introduction") from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="Could not save self introduction") from error
        return JSONResponse(content={"id": identity})

    @app.post("/api/control/{action}")
    async def post_action(
        action: str,
        request: Request,
        payload: ControlAction,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        await authorize(request, authorization, x_csrf_token)
        if payload.action != action or action not in {"start", "stop"}:
            raise HTTPException(status_code=404, detail="Unknown action")
        if not idempotency_key or len(idempotency_key) > 128:
            raise HTTPException(status_code=400, detail="A valid Idempotency-Key is required")
        return control.operate(action, idempotency_key)

    return app


def _failed_overview_result() -> OverviewResult:
    return OverviewResult(
        status="failed",
        count_basis=COUNT_BASIS,
        counts={
            "idea_records": 0,
            "person_records": 0,
            "asset_records": 0,
            "report_version_records": 0,
        },
        recent=(),
    )
