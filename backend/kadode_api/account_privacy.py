"""Deterministic local/fake contracts for owner-scoped account export and deletion."""

from copy import deepcopy
import json


ARTIFACT_TYPES = (
    "profile",
    "idea",
    "document_metadata",
    "original",
    "extracted_text",
    "embedding",
    "search_index",
    "research",
    "decision",
)


class InMemoryAccountPrivacyRepository:
    """Credential-free store. Every public operation is scoped by its owner argument."""

    def __init__(self, accounts: dict[str, dict[str, object]] | None = None) -> None:
        self._accounts = deepcopy(accounts or {})

    @classmethod
    def seeded(cls) -> "InMemoryAccountPrivacyRepository":
        def account(owner: str) -> dict[str, object]:
            suffix = owner[-1]
            return {
                "profile": {"id": f"profile-{suffix}", "display_name": f"{owner} profile"},
                "ideas": [{"id": f"idea-{suffix}", "title": f"{owner} idea"}],
                "documents": [{
                    "id": f"document-{suffix}", "title": f"{owner} document", "metadata": {"version": 1},
                    "artifacts": {
                        "original": [f"original-{suffix}"],
                        "extracted_text": [f"text-{suffix}"],
                        "embedding": [f"embedding-{suffix}"],
                        "search_index": [f"index-{suffix}"],
                    },
                }],
                "research": [{"id": f"research-{suffix}", "query": f"{owner} query"}],
                "decisions": [{"id": f"decision-{suffix}", "decision": f"{owner} decision"}],
            }
        return cls({"owner-a": account("owner-a"), "owner-b": account("owner-b")})

    def export(self, owner_id: str) -> dict[str, object]:
        account = self._accounts.get(owner_id, self._empty_account())
        data = {
            "profile": account["profile"],
            "ideas": account["ideas"],
            "documents": [self._document_metadata(document) for document in account["documents"]],
            "research": account["research"],
            "decisions": account["decisions"],
        }
        return {"json": deepcopy(data), "markdown": self._markdown(data)}

    def delete(self, owner_id: str) -> dict[str, object]:
        account = self._accounts.get(owner_id, self._empty_account())
        items = self._manifest_items(account)
        self._accounts[owner_id] = self._empty_account()
        return {
            "manifest": {"items": items},
            "audit": {"status": "completed", "items": [{**item, "state": "excluded"} for item in items]},
        }

    @staticmethod
    def _empty_account() -> dict[str, object]:
        return {"profile": None, "ideas": [], "documents": [], "research": [], "decisions": []}

    @staticmethod
    def _document_metadata(document: dict[str, object]) -> dict[str, object]:
        return {key: deepcopy(value) for key, value in document.items() if key != "artifacts"}

    @staticmethod
    def _markdown(data: dict[str, object]) -> str:
        profile = data["profile"] or {}
        lines = ["# Kadode data export", "", "## Profile", f"- id: {profile.get('id', '')}", f"- display_name: {_markdown_value(profile.get('display_name', ''))}"]
        for section, fields in (
            ("ideas", ("title",)),
            ("documents", ("title", "metadata")),
            ("research", ("query",)),
            ("decisions", ("decision",)),
        ):
            lines.extend(["", f"## {section.title()}"])
            for item in data[section]:
                lines.append(f"- id: {item['id']}")
                lines.extend(f"  - {field}: {_markdown_value(item.get(field, ''))}" for field in fields)
        return "\n".join(lines)

    @staticmethod
    def _manifest_items(account: dict[str, object]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        if account["profile"]:
            items.append({"artifact_type": "profile", "id": account["profile"]["id"]})
        for key, artifact_type in (("ideas", "idea"), ("research", "research"), ("decisions", "decision")):
            items.extend({"artifact_type": artifact_type, "id": item["id"]} for item in account[key])
        for document in account["documents"]:
            items.append({"artifact_type": "document_metadata", "id": document["id"]})
            for artifact_type in ("original", "extracted_text", "embedding", "search_index"):
                items.extend({"artifact_type": artifact_type, "id": identifier} for identifier in document["artifacts"][artifact_type])
        return items


def _markdown_value(value: object) -> str:
    """Keep supplied content literal in Markdown while preserving it for import."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True).replace("`", "\\u0060")
