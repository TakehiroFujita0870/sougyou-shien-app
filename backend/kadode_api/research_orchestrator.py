"""Local, credential-free orchestration for research-run API contracts."""

from dataclasses import asdict, dataclass
from enum import StrEnum
from uuid import uuid4

from .research import DailyLimitExceeded, ResearchTimeout


class Source(StrEnum):
    WEB = "web"
    PATENT = "patent"
    DOCUMENT = "document"
    DECISION = "decision"


@dataclass(frozen=True)
class LocatedEvidence:
    source_type: Source
    locator: str
    excerpt: str


class LocalSource:
    def search(self, owner_id: str, query: str) -> tuple[LocatedEvidence, ...]:
        raise NotImplementedError


class FakeSource(LocalSource):
    def __init__(self, evidence: tuple[LocatedEvidence, ...] = (), error: Exception | None = None) -> None:
        self.evidence, self.error = evidence, error

    def search(self, owner_id: str, query: str) -> tuple[LocatedEvidence, ...]:
        if self.error:
            raise self.error
        return self.evidence


@dataclass
class Run:
    id: str
    owner_id: str
    query: str
    selected_sources: tuple[Source, ...]
    evidence: list[LocatedEvidence]
    source_status: dict[Source, str]

    def payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": "completed" if all(value == "completed" for value in self.source_status.values()) else "partial",
            "selected_sources": [source.value for source in self.selected_sources],
            "source_status": {source.value: value for source, value in self.source_status.items()},
            "evidence": [asdict(item) | {"source_type": item.source_type.value} for item in self.evidence],
        }


class ResearchOrchestrator:
    def __init__(self, sources: dict[Source, LocalSource]) -> None:
        self.sources, self.runs = sources, {}

    def create(self, owner_id: str, query: str, selected: tuple[Source, ...]) -> Run:
        run = Run(str(uuid4()), owner_id, query, selected, [], {})
        self.runs[run.id] = run
        self._execute(run, selected)
        return run

    def retry(self, owner_id: str, run_id: str) -> Run | None:
        run = self.get(owner_id, run_id)
        if not run:
            return None
        self._execute(run, tuple(source for source, status in run.source_status.items() if status != "completed"))
        return run

    def get(self, owner_id: str, run_id: str) -> Run | None:
        run = self.runs.get(run_id)
        return run if run and run.owner_id == owner_id else None

    def _execute(self, run: Run, selected: tuple[Source, ...]) -> None:
        for source in selected:
            try:
                run.evidence.extend(self.sources[source].search(run.owner_id, run.query))
                run.source_status[source] = "completed"
            except ResearchTimeout:
                run.source_status[source] = "timeout: retry the source"
            except DailyLimitExceeded:
                run.source_status[source] = "limit: retry after 00:00 JST"
