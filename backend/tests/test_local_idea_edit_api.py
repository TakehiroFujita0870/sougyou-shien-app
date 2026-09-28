from fastapi.testclient import TestClient

from dots.founder_graph_write import RevisionConflictError, WriteReceipt
from dots.local_control import LocalControl, create_local_control_app


class IdeaWriter:
    def __init__(self):
        self.calls = []

    def save(self, idea_id, **kwargs):
        self.calls.append((idea_id, kwargs))
        if kwargs["expected_revision"] != 0:
            raise RevisionConflictError("stale")
        return WriteReceipt("revise_idea", "idea-new", "idea", 1, kwargs["idempotency_key"])


def test_idea_edit_is_local_guarded_and_revision_checked():
    writer = IdeaWriter()
    control = LocalControl({}, expected_host="localhost:8765", allowed_origin="http://localhost:8765",
                           start_order=(), stop_order=())
    app = create_local_control_app(control, overview_owner_id="owner-test", idea_writer=writer)
    client = TestClient(app, base_url="http://localhost:8765", client=("127.0.0.1", 12345))
    headers = {"Origin": "http://localhost:8765", "X-CSRF-Token": client.get("/api/status").json()["csrf_token"]}
    payload = {"title": "修正案", "description": "修正した説明", "expected_revision": 0, "idempotency_key": "idea-edit"}
    url = "/api/ideas/idea-old"

    assert client.put(url, json=payload).status_code == 403
    assert client.put(url, json=payload, headers={**headers, "Origin": "https://other.test"}).status_code == 403
    assert client.put(url, json={**payload, "egress_policy": "public"}, headers=headers).status_code == 422
    assert client.put(url, json={**payload, "expected_revision": True}, headers=headers).status_code == 422
    assert writer.calls == []

    saved = client.put(url, json=payload, headers=headers)
    assert saved.status_code == 200 and saved.json()["id"] == "idea-new"
    assert writer.calls == [("idea-old", {"title": "修正案", "description": "修正した説明",
                                        "expected_revision": 0, "idempotency_key": "idea-edit"})]
    assert client.put(url, json={**payload, "expected_revision": 1}, headers=headers).status_code == 409
