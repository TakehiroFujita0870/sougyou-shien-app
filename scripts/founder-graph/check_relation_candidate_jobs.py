"""Inspect and optionally retry owner-scoped durable relation-candidate jobs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dots.founder_graph_job_store import GraphJob, JobState  # noqa: E402
from dots.founder_graph_runtime import (  # noqa: E402
    close_neo4j_driver,
    create_neo4j_driver_from_env,
    create_neo4j_graph_composition,
    create_relation_candidate_job_processor,
    resolve_graph_backend,
)


def _limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("limit must be an integer from 1 to 20") from error
    if not 1 <= parsed <= 20:
        raise argparse.ArgumentTypeError("limit must be an integer from 1 to 20")
    return parsed


def _job_summary(job: GraphJob, action: str) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "state": job.state.value,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "candidate_payload_persisted": job.candidate_payload_persisted,
        "action": action,
    }


def inspect_jobs(processor: Any, *, limit: int = 20, apply: bool = False) -> dict[str, Any]:
    """Retry only due pending jobs with persisted payloads; never reopen failed jobs."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("inspection limit must be between 1 and 20")
    jobs = processor.jobs.list_inspection_jobs(limit=limit)
    summaries: list[dict[str, Any]] = []
    for job in jobs:
        if job.state is JobState.FAILED:
            result, action = job, "needs_review"
        elif not job.candidate_payload_persisted:
            result, action = job, "manifest_missing"
        elif not apply:
            result, action = job, "would_retry"
        else:
            result = processor.process_specific(job.id, raw_manifest=None)
            if result is None:
                summaries.append({
                    "job_id": job.id, "state": "not_found",
                    "attempt_count": job.attempt_count, "max_attempts": job.max_attempts,
                    "candidate_payload_persisted": job.candidate_payload_persisted,
                    "action": "not_processed",
                })
                continue
            action = "processed" if result.state is JobState.SUCCEEDED else result.state.value
        summaries.append(_job_summary(result, action))

    actions = [item["action"] for item in summaries]
    return {
        "mode": "apply" if apply else "inspect",
        "limit": limit,
        "summary": {
            "processed": actions.count("processed"),
            "would_retry": actions.count("would_retry"),
            "manifest_missing": actions.count("manifest_missing"),
            "terminal_failed": actions.count("needs_review"),
        },
        "jobs": summaries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=_limit, default=20, help="maximum jobs to inspect (1-20)")
    parser.add_argument("--apply", action="store_true", help="retry eligible persisted jobs")
    args = parser.parse_args(argv)

    owner_id = os.environ.get("DOTS_LOCAL_OWNER_ID", "").strip()
    if not owner_id:
        print("DOTS_LOCAL_OWNER_ID must identify the local owner", file=sys.stderr)
        return 2
    try:
        if resolve_graph_backend() != "neo4j":
            print("graph job inspection requires the persistent Neo4j backend", file=sys.stderr)
            return 2
        database = (os.environ.get("DOTS_NEO4J_DATABASE") or "neo4j").strip()
        driver = create_neo4j_driver_from_env()
        try:
            composition = create_neo4j_graph_composition(driver, owner_id, database=database)
            processor = create_relation_candidate_job_processor(composition)
            report = inspect_jobs(processor, limit=args.limit, apply=args.apply)
        finally:
            close_neo4j_driver(driver)
    except Exception:
        # Database/provider exception strings may contain sensitive connection data.
        print("graph job inspection failed; check the local service and safe logs", file=sys.stderr)
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
