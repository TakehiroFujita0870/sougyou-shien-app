from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


DecisionStatus = Literal['active', 'expired']
Disposition = Literal['accepted', 'rejected', 'pending', 'reconsider']


class ObservationInput(BaseModel):
    observation: str = Field(min_length=1, max_length=2000)
    disposition: Disposition
    evidence_id: str | None = Field(default=None, max_length=200)


class DecisionInput(BaseModel):
    idea_id: str = Field(min_length=1, max_length=200)
    decision: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=5, max_length=4000)
    valid_from: datetime
    status: DecisionStatus = 'active'
    supersedes_id: UUID | None = None
    observations: list[ObservationInput] = Field(default_factory=list, max_length=100)


class ObservationResponse(ObservationInput):
    pass


class DecisionResponse(BaseModel):
    id: UUID
    idea_id: str
    decision: str
    rationale: str
    valid_from: datetime
    status: DecisionStatus
    supersedes_id: UUID | None
    observations: list[ObservationResponse]


class DecisionSearchResponse(BaseModel):
    decisions: list[DecisionResponse]


class DecisionNotFound(Exception):
    pass


@dataclass(frozen=True)
class StoredDecision:
    id: UUID
    owner_id: str
    idea_id: str
    decision: str
    rationale: str
    valid_from: datetime
    status: DecisionStatus
    supersedes_id: UUID | None
    observations: tuple[ObservationInput, ...]

    def to_response(self) -> DecisionResponse:
        return DecisionResponse(
            id=self.id,
            idea_id=self.idea_id,
            decision=self.decision,
            rationale=self.rationale,
            valid_from=self.valid_from,
            status=self.status,
            supersedes_id=self.supersedes_id,
            observations=[ObservationResponse(**observation.model_dump()) for observation in self.observations],
        )


class InMemoryDecisionRepository:
    """Local contract repository. It intentionally has no external credentials or persistence."""

    def __init__(self) -> None:
        self._decisions: dict[UUID, StoredDecision] = {}

    def create(self, owner_id: str, command: DecisionInput) -> DecisionResponse:
        if command.supersedes_id is not None:
            superseded = self._decisions.get(command.supersedes_id)
            if superseded is None or superseded.owner_id != owner_id or superseded.idea_id != command.idea_id:
                raise DecisionNotFound

        record = StoredDecision(
            id=uuid4(),
            owner_id=owner_id,
            idea_id=command.idea_id,
            decision=command.decision,
            rationale=command.rationale,
            valid_from=command.valid_from,
            status=command.status,
            supersedes_id=command.supersedes_id,
            observations=tuple(command.observations),
        )
        self._decisions[record.id] = record
        return record.to_response()

    def search(self, owner_id: str, idea_id: str, query: str) -> list[DecisionResponse]:
        normalized_query = query.casefold()
        matches = [
            decision
            for decision in self._decisions.values()
            if decision.owner_id == owner_id
            and decision.idea_id == idea_id
            and _matches_query(decision, normalized_query)
        ]
        return [decision.to_response() for decision in sorted(matches, key=lambda decision: decision.valid_from, reverse=True)]


def _matches_query(decision: StoredDecision, normalized_query: str) -> bool:
    searchable = [decision.decision, decision.rationale]
    searchable.extend(observation.observation for observation in decision.observations)
    return any(normalized_query in value.casefold() for value in searchable)
