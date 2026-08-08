"""Deterministic local contract for consented cross-project knowledge reuse."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


KnowledgeSourceType = Literal["anonymized_customer_interview_derivative", "decision", "manual"]


class ProjectKnowledgeInput(BaseModel):
    source_project_id: str = Field(min_length=1, max_length=200)
    source_type: KnowledgeSourceType
    source_id: str = Field(min_length=1, max_length=200)
    anonymized_content: str = Field(min_length=1, max_length=4000)


class KnowledgeGrantInput(BaseModel):
    knowledge_id: UUID
    source_project_id: str = Field(min_length=1, max_length=200)
    target_project_id: str = Field(min_length=1, max_length=200)


class ProjectKnowledgeResponse(BaseModel):
    id: UUID
    source_project_id: str
    source_type: KnowledgeSourceType
    source_id: str


class KnowledgeGrantResponse(BaseModel):
    id: UUID
    knowledge_id: UUID
    source_project_id: str
    target_project_id: str
    granted_at: datetime
    revoked_at: datetime | None


class KnowledgeCandidate(BaseModel):
    knowledge_id: UUID
    source_project_id: str
    target_project_id: str
    content: str


class KnowledgeCandidatesResponse(BaseModel):
    candidates: list[KnowledgeCandidate]


class KnowledgeReferenceResponse(BaseModel):
    status: Literal["available", "unavailable"]


@dataclass(frozen=True)
class StoredKnowledge:
    id: UUID
    owner_id: str
    source_project_id: str
    source_type: KnowledgeSourceType
    source_id: str
    anonymized_content: str
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class StoredGrant:
    id: UUID
    owner_id: str
    knowledge_id: UUID
    source_project_id: str
    target_project_id: str
    granted_at: datetime
    revoked_at: datetime | None = None


class InMemoryProjectKnowledgeRepository:
    """No network, embedding, or export client is used by this local contract."""

    def __init__(self) -> None:
        self._knowledge: dict[UUID, StoredKnowledge] = {}
        self._grants: dict[UUID, StoredGrant] = {}

    def create(self, owner_id: str, command: ProjectKnowledgeInput) -> ProjectKnowledgeResponse:
        knowledge = StoredKnowledge(uuid4(), owner_id, command.source_project_id, command.source_type, command.source_id, command.anonymized_content)
        self._knowledge[knowledge.id] = knowledge
        return ProjectKnowledgeResponse(id=knowledge.id, source_project_id=knowledge.source_project_id, source_type=knowledge.source_type, source_id=knowledge.source_id)

    def grant(self, owner_id: str, command: KnowledgeGrantInput) -> KnowledgeGrantResponse | None:
        knowledge = self._knowledge.get(command.knowledge_id)
        if knowledge is None or knowledge.owner_id != owner_id or knowledge.deleted_at is not None or knowledge.source_project_id != command.source_project_id:
            return None
        grant = StoredGrant(uuid4(), owner_id, knowledge.id, command.source_project_id, command.target_project_id, _now())
        self._grants[grant.id] = grant
        return _grant_response(grant)

    def revoke(self, owner_id: str, grant_id: UUID) -> KnowledgeGrantResponse | None:
        grant = self._grants.get(grant_id)
        if grant is None or grant.owner_id != owner_id:
            return None
        if grant.revoked_at is None:
            grant = replace(grant, revoked_at=_now())
            self._grants[grant.id] = grant
        return _grant_response(grant)

    def delete(self, owner_id: str, knowledge_id: UUID) -> bool:
        knowledge = self._knowledge.get(knowledge_id)
        if knowledge is None or knowledge.owner_id != owner_id:
            return False
        if knowledge.deleted_at is None:
            self._knowledge[knowledge_id] = replace(knowledge, deleted_at=_now())
        return True

    def candidates(self, owner_id: str, target_project_id: str) -> KnowledgeCandidatesResponse:
        candidates = []
        for grant in self._grants.values():
            knowledge = self._knowledge.get(grant.knowledge_id)
            if grant.owner_id == owner_id and grant.target_project_id == target_project_id and grant.revoked_at is None and knowledge and knowledge.deleted_at is None:
                candidates.append(KnowledgeCandidate(knowledge_id=knowledge.id, source_project_id=grant.source_project_id, target_project_id=target_project_id, content=knowledge.anonymized_content))
        return KnowledgeCandidatesResponse(candidates=sorted(candidates, key=lambda item: str(item.knowledge_id)))

    def reference_status(self, owner_id: str, knowledge_id: UUID, target_project_id: str) -> KnowledgeReferenceResponse:
        available = any(candidate.knowledge_id == knowledge_id for candidate in self.candidates(owner_id, target_project_id).candidates)
        return KnowledgeReferenceResponse(status="available" if available else "unavailable")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _grant_response(grant: StoredGrant) -> KnowledgeGrantResponse:
    return KnowledgeGrantResponse(id=grant.id, knowledge_id=grant.knowledge_id, source_project_id=grant.source_project_id, target_project_id=grant.target_project_id, granted_at=grant.granted_at, revoked_at=grant.revoked_at)
