"""Deterministic, local DOCX adapter for the formal business-plan contract."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from xml.sax.saxutils import escape

from pydantic import BaseModel, Field

from .project_dossier import ProjectDossier


class FormalPlanContent(BaseModel):
    owner_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    title: str = "Dots. フォーマル事業計画書"
    dossier: ProjectDossier


class DocxTemplateAdapter:
    """Render only an already-authorized content contract; no fetching or calculation."""

    def render(self, content: FormalPlanContent, principal_owner_id: str) -> bytes:
        if content.owner_id != principal_owner_id:
            raise PermissionError("owner_boundary_mismatch")
        files = {
            "[Content_Types].xml": _content_types(),
            "_rels/.rels": _root_rels(),
            "word/document.xml": _document_body(content),
            "word/_rels/document.xml.rels": _document_rels(),
        }
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for name, value in files.items():
                entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = ZIP_DEFLATED
                entry.external_attr = 0o600 << 16
                archive.writestr(entry, value, compress_type=ZIP_DEFLATED, compresslevel=9)
        return output.getvalue()


def content_from_dossier(owner_id: str, dossier: ProjectDossier) -> FormalPlanContent:
    return FormalPlanContent(owner_id=owner_id, project_id=dossier.project_id, dossier=dossier)


def _document_body(content: FormalPlanContent) -> str:
    paragraphs = [_paragraph(content.title, "Title"), _paragraph(f"project: {content.project_id}", "Subtitle")]
    for section in content.dossier.sections:
        paragraphs += [_paragraph(section.question, "Heading1"), _paragraph(f"状態: {'未確認' if section.status == 'unconfirmed' else '確認済み'}")]
        paragraphs += [_paragraph(f"根拠 [{item.source_id}] {item.summary} (locator: {item.locator})") for item in section.facts]
        paragraphs += [_paragraph(f"AI推論: {inference}") for inference in section.ai_inference]
        paragraphs += [_paragraph(f"本人判断: {decision.statement}") for decision in section.owner_decisions]
        paragraphs += [_paragraph(f"未確認理由: {reason}") for reason in section.missing_reasons]
    if content.dossier.contradictory_evidence:
        paragraphs.append(_paragraph("相反する根拠", "Heading1"))
        paragraphs += [_paragraph(f"[{item.source_id}] {item.summary} (locator: {item.locator})") for item in content.dossier.contradictory_evidence]
    paragraphs.append(_paragraph(content.dossier.disclaimer, "Note"))
    body = "".join(paragraphs)
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'


def _paragraph(text: str, style: str = "Normal") -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def _content_types() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'


def _root_rels() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'


def _document_rels() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
