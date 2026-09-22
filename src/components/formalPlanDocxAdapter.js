import {
  AlignmentType,
  Document,
  HeadingLevel,
  Packer,
  Paragraph,
  TextRun,
} from 'docx';

const noteText = 'この文書はローカル下書きであり、融資・税務・法務の助言ではありません。';

function text(value, options = {}) {
  return new TextRun({ text: String(value ?? ''), font: 'Noto Sans JP', ...options });
}

function paragraph(value, options = {}) {
  return new Paragraph({ children: [text(value)], spacing: { after: 120 }, ...options });
}

export async function createFormalPlanDocx(project) {
  const children = [
    new Paragraph({ children: [text(project.name, { bold: true, size: 34 })], heading: HeadingLevel.TITLE, alignment: AlignmentType.CENTER, spacing: { after: 240 } }),
    paragraph(project.overview),
  ];

  for (const [label, section] of Object.entries(project.sections ?? {})) {
    children.push(
      new Paragraph({ children: [text(label, { bold: true })], heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 120 } }),
      paragraph(`状態: ${section.status}`),
      paragraph(section.summary),
      paragraph(`根拠: ${section.evidence}`),
      paragraph(`未確認: ${section.unknown}`),
    );
  }

  for (const decision of project.decisions ?? []) {
    children.push(
      new Paragraph({ children: [text('意思決定の履歴', { bold: true })], heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 120 } }),
      paragraph(`${decision.kind}: ${decision.title}`),
      paragraph(`理由: ${decision.reason}`),
    );
  }

  children.push(new Paragraph({ children: [text(noteText, { italics: true, color: '666666', size: 18 })], spacing: { before: 240 } }));
  const document = new Document({
    creator: 'Dots.',
    title: project.name,
    description: 'Dots. business plan draft',
    sections: [{
      properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
      children,
    }],
  });
  return Packer.toBlob(document);
}

export async function downloadFormalPlanDocx(project, { documentRef = globalThis.document, url = globalThis.URL } = {}) {
  const blob = await createFormalPlanDocx(project);
  const href = url.createObjectURL(blob);
  const anchor = documentRef.createElement('a');
  anchor.href = href;
  anchor.download = 'dots-business-plan.docx';
  documentRef.body.append(anchor);
  anchor.click();
  anchor.remove();
  url.revokeObjectURL(href);
  return blob;
}
