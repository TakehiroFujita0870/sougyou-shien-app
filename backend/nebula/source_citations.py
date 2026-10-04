"""Fail-closed public citation metadata helpers."""
from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit

from .founder_graph import Claim, ContentChunk, EgressPolicy, Evidence, Source, SourceRevision, Status


def citation_metadata(source: Mapping[str, Any]) -> dict[str, str] | None:
    """Expose only a public URL and title, never source/revision content."""
    locator = source.get("locator")
    title = source.get("title")
    if not isinstance(locator, str) or not isinstance(title, str) or not title.strip():
        return None
    locator = locator.strip()
    sensitive_names = {"access_token", "api_key", "apikey", "auth", "authorization", "code", "hdnea", "hdnts", "key", "jwt", "private_key", "password", "rlkey", "secret", "session", "signature", "sig", "token"}

    def sensitive_parameter(name: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
        return normalized in {re.sub(r"[^a-z0-9]", "", item) for item in sensitive_names} or any(
            marker in normalized for marker in ("token", "credential", "signature", "secret", "password", "passwd", "authorization", "authkey", "sessionid", "keypairid")
        )

    try:
        parsed = urlsplit(locator)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(sensitive_parameter(key) for key, _value in parse_qsl(parsed.query, keep_blank_values=True))
            or any(sensitive_parameter(key) for key, _value in parse_qsl(parsed.fragment, keep_blank_values=True))
        ):
            return None
    except ValueError:
        return None
    return {"url": locator, "title": title.strip()}


def parse_object(value: Any) -> dict[str, Any] | None:
    import json

    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def researched_evidence_ids(sections: Any) -> tuple[str, ...]:
    """Collect bounded, unique evidence references from the eight sections."""
    if not isinstance(sections, (tuple, list)) or len(sections) != 8:
        return ()
    result: list[str] = []
    for section in sections:
        refs = getattr(section, "evidence_ids", None)
        if not isinstance(refs, (tuple, list)):
            return ()
        for ref in refs:
            if not isinstance(ref, str) or not ref.strip():
                return ()
            if ref not in result:
                result.append(ref)
    return tuple(result)


def evidence_lineage_is_current(writes: Any, evidence_id: str, owner_id: str) -> bool:
    """Validate a shareable Evidence→chunk→revision→Source chain fail-closed."""
    gateway = getattr(writes, "gateway", None)
    if gateway is not None:
        try:
            from .founder_graph_neo4j_read import Neo4jGraphReadService

            return Neo4jGraphReadService(gateway).validate_evidence_citation(evidence_id, owner_id=owner_id)
        except Exception:
            return False
    get_node = getattr(writes, "get_node", None)
    if not callable(get_node):
        return False
    try:
        evidence = get_node(evidence_id)
        if not isinstance(evidence, Evidence):
            return False
        if (
            evidence.owner_id != owner_id or evidence.status is not Status.ACTIVE
            or evidence.egress_policy is not EgressPolicy.SHAREABLE
            or evidence.material_id is not None or evidence.excerpt != ""
            or not evidence.claim_id or not evidence.content_chunk_id or not evidence.source_revision_id
        ):
            return False
        claim = get_node(evidence.claim_id)
        chunk = get_node(evidence.content_chunk_id)
        revision = get_node(evidence.source_revision_id)
        if not isinstance(claim, Claim):
            return False
        source = get_node(revision.source_id) if isinstance(revision, SourceRevision) else None
        return (
            claim.owner_id == owner_id and claim.status is Status.ACTIVE
            and isinstance(chunk, ContentChunk) and chunk.owner_id == owner_id
            and chunk.status is Status.ACTIVE and chunk.source_revision_id == revision.id
            and isinstance(revision, SourceRevision) and revision.owner_id == owner_id
            and revision.status is Status.ACTIVE and revision.egress_policy is EgressPolicy.SHAREABLE
            and isinstance(source, Source) and source.owner_id == owner_id
            and source.status is Status.ACTIVE and source.egress_policy is EgressPolicy.SHAREABLE
            and source.current_revision_id == revision.id
            and evidence.locator == f"chars:{evidence.char_start}-{evidence.char_end}"
            and evidence.content_hash == chunk.text_hash
            and citation_metadata({"locator": source.locator, "title": source.title}) is not None
        )
    except Exception:
        return False
