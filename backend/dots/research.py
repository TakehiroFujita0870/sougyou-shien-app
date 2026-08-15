"""Offline contracts for research-source adapters; no credentials or network clients."""

from dataclasses import dataclass
from datetime import date
import re
from typing import Protocol
from unicodedata import normalize


JPO_API_BASE_URL = "https://ip-data.jpo.go.jp/api"
_PATENT_NUMBER = re.compile(r"(?:特開|JP)?\s*(\d{4})\s*[-－]?\s*(\d{6})(?:\s*[AＡ])?", re.IGNORECASE)


class ResearchTimeout(Exception):
    """A source did not respond within the caller's configured timeout."""


class DailyLimitExceeded(Exception):
    """The registered JPO ID has reached an API-specific daily limit."""


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    text: str


@dataclass(frozen=True)
class JpoPatentRecord:
    publication_number: str
    applicant: str
    publication_date: date
    cited_documents: tuple[str, ...]


@dataclass(frozen=True)
class Evidence:
    publication_number: str
    applicant: str
    publication_date: date
    cited_documents: tuple[str, ...]
    source_url: str


@dataclass(frozen=True)
class ResearchOutcome:
    evidence: tuple[Evidence, ...]
    errors: tuple[str, ...]
    candidate_count: int


class ResearchSource(Protocol):
    def discover(self, query: str) -> tuple[WebResult, ...]: ...


class PatentResearchSource(Protocol):
    def confirm(self, publication_number: str) -> JpoPatentRecord | None: ...


def normalize_patent_number(value: str) -> str | None:
    match = _PATENT_NUMBER.search(normalize("NFKC", value))
    if not match:
        return None
    return f"JP{match.group(1)}-{match.group(2)}A"


def research_patents(query: str, web: ResearchSource, jpo: PatentResearchSource) -> ResearchOutcome:
    try:
        results = web.discover(query)
    except (ResearchTimeout, DailyLimitExceeded) as error:
        return ResearchOutcome((), (_message("web", error),), 0)

    candidates = tuple(
        dict.fromkeys(number for result in results if (number := normalize_patent_number(result.text)))
    )
    evidence: list[Evidence] = []
    errors: list[str] = []
    for candidate in candidates:
        try:
            record = jpo.confirm(candidate)
        except (ResearchTimeout, DailyLimitExceeded) as error:
            errors.append(_message("jpo", error))
            continue
        if record:
            evidence.append(Evidence(
                publication_number=normalize_patent_number(record.publication_number) or candidate,
                applicant=record.applicant,
                publication_date=record.publication_date,
                cited_documents=tuple(filter(None, (normalize_patent_number(item) for item in record.cited_documents))),
                source_url=JPO_API_BASE_URL,
            ))
    return ResearchOutcome(tuple(evidence), tuple(errors), len(candidates))


def _message(source: str, error: Exception) -> str:
    if isinstance(error, DailyLimitExceeded):
        return f"{source}: daily limit reached; retry after 00:00 JST"
    return f"{source}: timeout; retry the source"


class FakeWebResearchSource:
    def __init__(self, results: list[WebResult] | None = None, error: Exception | None = None) -> None:
        self.results, self.error = tuple(results or ()), error

    def discover(self, query: str) -> tuple[WebResult, ...]:
        if self.error:
            raise self.error
        return self.results


class FakeJpoPatentSource:
    def __init__(self, records: dict[str, JpoPatentRecord] | None = None, error: Exception | None = None,
                 failures: dict[str, Exception] | None = None) -> None:
        self.records, self.error, self.failures = records or {}, error, failures or {}

    def confirm(self, publication_number: str) -> JpoPatentRecord | None:
        if publication_number in self.failures:
            raise self.failures[publication_number]
        if self.error:
            raise self.error
        return self.records.get(publication_number)
