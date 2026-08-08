from kadode_api.file_ingestion import (
    DeletionTarget,
    ExtractedPage,
    IngestionState,
    classify_file,
    deletion_manifest,
    normalize_extraction,
)


PDF = b"%PDF-1.7\n"
DOCX = b"PK\x03\x04word/document.xml"


def test_supported_text_pdf_is_pending_extraction():
    decision = classify_file("brief.pdf", PDF, page_count=2)
    assert decision.category == "supported"
    assert decision.state is IngestionState.VALIDATING
    assert decision.needs_ocr is False


def test_unsupported_extension_or_active_docx_is_rejected():
    assert classify_file("script.exe", b"MZ").category == "unsupported"
    assert classify_file("macro.docx", DOCX, contains_macro=True).category == "unsupported"


def test_encrypted_pdf_is_rejected():
    assert classify_file("locked.pdf", PDF + b"/Encrypt").category == "encrypted"


def test_oversize_source_or_page_count_is_rejected():
    assert classify_file("large.txt", b"a" * (25 * 1024 * 1024 + 1)).category == "oversize"
    assert classify_file("long.pdf", PDF, page_count=501).category == "oversize"


def test_malformed_signature_and_invalid_text_encoding_are_rejected():
    assert classify_file("broken.pdf", b"not a pdf").category == "malformed"
    assert classify_file("legacy.txt", b"\x82\xa0").category == "malformed"
    assert classify_file("broken.csv", b'"unclosed').category == "malformed"


def test_utf16_text_and_csv_with_a_bom_are_supported():
    utf16 = "見出し,値\nA,1".encode("utf-16")
    assert classify_file("notes.txt", utf16).category == "supported"
    assert classify_file("rows.csv", utf16).category == "supported"


def test_image_pdf_is_accepted_but_marked_for_future_ocr():
    decision = classify_file("scan.pdf", PDF, page_count=1, has_extractable_text=False)
    assert decision.category == "supported"
    assert decision.needs_ocr is True


def test_extraction_contract_links_document_version_page_and_hash():
    pages = normalize_extraction("doc-1", 3, [ExtractedPage(2, "根拠本文")])
    assert pages[0].document_id == "doc-1"
    assert pages[0].version == 3
    assert pages[0].page == 2
    assert len(pages[0].content_hash) == 64


def test_deletion_manifest_tracks_all_persisted_artifact_types():
    manifest = deletion_manifest("doc-1", 3, {DeletionTarget.CHUNKS: ["c-1"]})
    assert manifest.document_id == "doc-1"
    assert manifest.version == 3
    assert {item.target for item in manifest.items} == set(DeletionTarget)
