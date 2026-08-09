import { PDFDocument, rgb } from 'pdf-lib';
import fontkit from '@pdf-lib/fontkit';
import notoSansJp from '../assets/fonts/NotoSansJP-Regular.ttf?inline';

const A4 = [595.28, 841.89];
const MARGIN = 54;

function fontBytes() {
  const payload = notoSansJp.slice(notoSansJp.indexOf(',') + 1);
  return Uint8Array.from(atob(payload), (character) => character.charCodeAt(0));
}

function wrap(text, maxCharacters) {
  const source = String(text ?? '').trim() || '未確定';
  const result = [];
  let line = '';
  for (const character of source) {
    line += character;
    if (line.length >= maxCharacters || character === '\n') {
      result.push(line.trim());
      line = '';
    }
  }
  if (line) result.push(line);
  return result;
}

function documentItems(project) {
  const items = [
    { text: project.name || 'Kadode 事業計画書', size: 20, gap: 14 },
    { text: '事業計画書（ローカル下書き）', size: 10, color: rgb(0.35, 0.35, 0.35), gap: 10 },
    { text: project.overview || '未確定', size: 11, gap: 14 },
  ];
  for (const [label, section] of Object.entries(project.sections ?? {})) {
    items.push(
      { text: label, size: 14, gap: 7 },
      { text: `状態: ${section.status || '未確定'}`, size: 10 },
      { text: `内容: ${section.summary || '未確定'}`, size: 10 },
      { text: `根拠: ${section.evidence || '未確定'}`, size: 10 },
      { text: `未確定: ${section.unknown || '未確定'}`, size: 10, gap: 9 },
    );
  }
  items.push({ text: '意思決定の履歴', size: 14, gap: 7, keepCount: 2 });
  for (const decision of project.decisions ?? []) {
    items.push({ text: `${decision.kind || '判断'}: ${decision.title || '未確定'}`, size: 10, keepCount: 1 }, { text: `理由: ${decision.reason || '未確定'}`, size: 10, gap: 9 });
  }
  items.push({ text: '注記: 未確定の項目は確認後に更新してください。本資料はローカルの下書きであり、財務・融資・税務・法務上の助言または提出書類ではありません。', size: 9, color: rgb(0.35, 0.35, 0.35) });
  return items;
}

export async function createFormalPlanPdf(project) {
  const pdf = await PDFDocument.create();
  pdf.registerFontkit(fontkit);
  const font = await pdf.embedFont(fontBytes(), { subset: false });
  let page = pdf.addPage(A4);
  let y = A4[1] - MARGIN;
  const items = documentItems(project);
  const itemHeight = (item) => wrap(item.text, item.size >= 14 ? 22 : 34).length * (item.size + 5) + (item.gap ?? 3);
  for (const [index, item] of items.entries()) {
    const leading = item.size + 5;
    const groupHeight = items.slice(index, index + 1 + (item.keepCount ?? 0)).reduce((height, groupedItem) => height + itemHeight(groupedItem), 0);
    if (y - groupHeight < MARGIN) {
      page = pdf.addPage(A4);
      y = A4[1] - MARGIN;
    }
    for (const text of wrap(item.text, item.size >= 14 ? 22 : 34)) {
      if (y - leading < MARGIN) {
        page = pdf.addPage(A4);
        y = A4[1] - MARGIN;
      }
      page.drawText(text, { x: MARGIN, y, size: item.size, font, color: item.color ?? rgb(0.1, 0.1, 0.1) });
      y -= leading;
    }
    y -= item.gap ?? 3;
  }
  pdf.setTitle(`${project.name || 'Kadode'} 事業計画書`);
  pdf.setSubject('Kadode ローカル下書き');
  return new Blob([await pdf.save()], { type: 'application/pdf' });
}

export async function downloadFormalPlanPdf(project, { documentRef = globalThis.document, url = globalThis.URL } = {}) {
  const blob = await createFormalPlanPdf(project);
  const href = url.createObjectURL(blob);
  const anchor = documentRef.createElement('a');
  anchor.href = href;
  anchor.download = 'kadode-business-plan.pdf';
  documentRef.body.append(anchor);
  anchor.click();
  anchor.remove();
  url.revokeObjectURL(href);
  return blob;
}
