from io import BytesIO
from zipfile import ZipFile

import pytest

from kadode_api.formal_plan_export import DocxTemplateAdapter, content_from_dossier
from kadode_api.project_dossier import BusinessDefinition, DossierRequest, SourceReference, assemble_dossier


def dossier():
    return assemble_dossier(DossierRequest(project_id="project-a", business_definition=BusinessDefinition(facts=[SourceReference(source_id="src-1", locator="p1#para2", summary="匿名化済み課題")])), None)


def test_docx_is_deterministic_editable_and_preserves_unconfirmed_and_locator():
    content = content_from_dossier("owner-a", dossier())
    adapter = DocxTemplateAdapter()
    first = adapter.render(content, "owner-a")
    assert first == adapter.render(content, "owner-a")
    with ZipFile(BytesIO(first)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert all(label in xml for label in ("どんな事業", "市場はある", "実現できる", "未確認", "src-1", "p1#para2"))
    assert "owner-a" not in xml


def test_docx_rejects_other_owner_before_rendering():
    with pytest.raises(PermissionError, match="owner_boundary_mismatch"):
        DocxTemplateAdapter().render(content_from_dossier("owner-a", dossier()), "owner-b")
