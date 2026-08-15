from datetime import date

from dots.research import (
    DailyLimitExceeded,
    FakeJpoPatentSource,
    FakeWebResearchSource,
    JpoPatentRecord,
    ResearchTimeout,
    WebResult,
    research_patents,
)


def test_web_candidate_and_jpo_record_are_normalized_to_evidence() -> None:
    web = FakeWebResearchSource(
        [WebResult(title="候補", url="https://example.test/patent", text="特開２０２３－１２３４５６")]
    )
    jpo = FakeJpoPatentSource(
        {
            "JP2023-123456A": JpoPatentRecord(
                publication_number="特開2023-123456",
                applicant="架空株式会社",
                publication_date=date(2023, 7, 20),
                cited_documents=("特開2020-000001",),
            )
        }
    )

    outcome = research_patents("再生材", web, jpo)

    assert outcome.errors == ()
    assert len(outcome.evidence) == 1
    evidence = outcome.evidence[0]
    assert evidence.publication_number == "JP2023-123456A"
    assert evidence.applicant == "架空株式会社"
    assert evidence.publication_date == date(2023, 7, 20)
    assert evidence.cited_documents == ("JP2020-000001A",)
    assert evidence.source_url == "https://ip-data.jpo.go.jp/api"


def test_timeout_keeps_a_recoverable_error() -> None:
    outcome = research_patents("再生材", FakeWebResearchSource(error=ResearchTimeout()), FakeJpoPatentSource())

    assert outcome.evidence == ()
    assert outcome.errors == ("web: timeout; retry the source",)


def test_daily_limit_stops_jpo_lookup_but_keeps_web_discovery() -> None:
    web = FakeWebResearchSource([WebResult("候補", "https://example.test", "JP2023123456")])
    outcome = research_patents("再生材", web, FakeJpoPatentSource(error=DailyLimitExceeded()))

    assert outcome.evidence == ()
    assert outcome.errors == ("jpo: daily limit reached; retry after 00:00 JST",)


def test_zero_candidates_is_not_a_patent_absence_claim() -> None:
    outcome = research_patents("再生材", FakeWebResearchSource(), FakeJpoPatentSource())

    assert outcome.evidence == ()
    assert outcome.errors == ()
    assert outcome.candidate_count == 0


def test_partial_success_returns_available_evidence_and_failure() -> None:
    web = FakeWebResearchSource(
        [
            WebResult("一件目", "https://example.test/1", "特開2023-123456"),
            WebResult("二件目", "https://example.test/2", "特開2024-654321"),
        ]
    )
    jpo = FakeJpoPatentSource(
        {"JP2023-123456A": JpoPatentRecord("特開2023-123456", "架空株式会社", date(2023, 7, 20), ())},
        failures={"JP2024-654321A": ResearchTimeout()},
    )

    outcome = research_patents("再生材", web, jpo)

    assert len(outcome.evidence) == 1
    assert outcome.errors == ("jpo: timeout; retry the source",)
