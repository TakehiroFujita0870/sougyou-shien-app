const encoder = new TextEncoder();

function crc32(bytes) {
  let crc = -1;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ -1) >>> 0;
}

function writeUint16(target, offset, value) { target[offset] = value & 255; target[offset + 1] = (value >>> 8) & 255; }
function writeUint32(target, offset, value) { writeUint16(target, offset, value & 0xffff); writeUint16(target, offset + 2, value >>> 16); }

function zipStored(files) {
  const entries = files.map(([name, text]) => ({ name: encoder.encode(name), data: encoder.encode(text) }));
  let size = 22 + entries.reduce((total, entry) => total + 30 + entry.name.length + entry.data.length + 46 + entry.name.length, 0);
  const output = new Uint8Array(size); let offset = 0; const central = [];
  for (const entry of entries) {
    const localOffset = offset; const crc = crc32(entry.data);
    writeUint32(output, offset, 0x04034b50); writeUint16(output, offset + 4, 20); writeUint16(output, offset + 8, 0); writeUint32(output, offset + 14, crc); writeUint32(output, offset + 18, entry.data.length); writeUint32(output, offset + 22, entry.data.length); writeUint16(output, offset + 26, entry.name.length); writeUint16(output, offset + 28, 0); offset += 30;
    output.set(entry.name, offset); offset += entry.name.length; output.set(entry.data, offset); offset += entry.data.length;
    central.push({ ...entry, crc, localOffset });
  }
  const centralStart = offset;
  for (const entry of central) {
    writeUint32(output, offset, 0x02014b50); writeUint16(output, offset + 4, 20); writeUint16(output, offset + 6, 20); writeUint16(output, offset + 10, 0); writeUint32(output, offset + 16, entry.crc); writeUint32(output, offset + 20, entry.data.length); writeUint32(output, offset + 24, entry.data.length); writeUint16(output, offset + 28, entry.name.length); writeUint16(output, offset + 30, 0); writeUint16(output, offset + 32, 0); writeUint32(output, offset + 42, entry.localOffset); offset += 46;
    output.set(entry.name, offset); offset += entry.name.length;
  }
  writeUint32(output, offset, 0x06054b50); writeUint16(output, offset + 8, central.length); writeUint16(output, offset + 10, central.length); writeUint32(output, offset + 12, offset - centralStart); writeUint32(output, offset + 16, centralStart);
  return output;
}

function escapeXml(value) { return String(value ?? '').replace(/[<>&"']/g, (character) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' })[character]); }
function paragraph(value, style = 'Normal') { return `<w:p><w:pPr><w:pStyle w:val="${style}"/></w:pPr><w:r><w:t xml:space="preserve">${escapeXml(value)}</w:t></w:r></w:p>`; }

export function createFormalPlanDocx(project) {
  const sections = Object.entries(project.sections ?? {}).flatMap(([label, section]) => [paragraph(label, 'Heading1'), paragraph(`Status: ${section.status}`), paragraph(section.summary), paragraph(`Evidence: ${section.evidence}`), paragraph(`Unconfirmed: ${section.unknown}`)]);
  const decisions = (project.decisions ?? []).flatMap((decision) => [paragraph('Decision history', 'Heading1'), paragraph(`${decision.kind}: ${decision.title}`), paragraph(`Reason: ${decision.reason}`)]);
  const body = [paragraph(project.name, 'Title'), paragraph(project.overview), ...sections, ...decisions, paragraph('This document is a local draft and not financial, lending, tax, or legal advice.', 'Note')].join('');
  const document = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>`;
  return new Blob([zipStored([
    ['[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'],
    ['_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'],
    ['word/document.xml', document], ['word/_rels/document.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'],
  ])], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
}

export function downloadFormalPlanDocx(project, { documentRef = globalThis.document, url = globalThis.URL } = {}) {
  const blob = createFormalPlanDocx(project); const href = url.createObjectURL(blob); const anchor = documentRef.createElement('a');
  anchor.href = href; anchor.download = 'kadode-business-plan.docx'; documentRef.body.append(anchor); anchor.click(); anchor.remove(); url.revokeObjectURL(href);
  return blob;
}
