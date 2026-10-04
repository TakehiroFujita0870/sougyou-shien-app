import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';

const skill = readFileSync(fileURLToPath(new URL('../../plugins/nebula/skills/founder-graph-capture/SKILL.md', import.meta.url)), 'utf8');

function expectInOrder(...phrases) {
  let cursor = -1;
  for (const phrase of phrases) {
    const next = skill.indexOf(phrase, cursor + 1);
    expect(next, `Expected "${phrase}" after the preceding capture step`).toBeGreaterThan(cursor);
    cursor = next;
  }
}

it('keeps draft capture, internal search, one proposal, permission, and both research routes in order', () => {
  expectInOrder('同一記録がないか先に確認', '`capture_idea`', '関連する既存Idea・Asset・Sourceを検索', '`create_research_campaign`', '`approve_research_campaign`', '通常のWeb検索とDeep Research');
  expect(skill).toContain('調査を必ず一度提案する');
  expect(skill).toContain('新規保存または既存記録の再利用で未調査Ideaを扱ったら');
  expect(skill).toContain('既に提示または断られた同じ提案は繰り返さない');
});

it('captures a reusable criterion without turning it into a strength or an owner decision', () => {
  expect(skill).toContain('`kind=knowledge, home_category=criterion`');
  expect(skill).toContain('個別Ideaで決めた結論は再利用する判断基準と混同しない');
  expect(skill).toContain('判断基準は実際に新しい案へ適用したときだけ根拠付き`REUSES`候補にできる');
  expect(skill).toContain('機微な詳細は既定の`local_only`を維持');
});

it('keeps incremental findings and prior research lightweight before formal evidence', () => {
  expectInOrder('`append_research_finding`', '`capture_source`', '`save_idea_brief`', '`append_claim`', '`capture_evidence`', '`record_research_run`', '`save_researched_idea_brief`');
  expect(skill).toContain('URLが付いただけでは検証済みEvidenceとは呼ばない');
  expect(skill).toContain('`origin=prior_research_import`');
  expect(skill).toContain('承認済みCampaignやEvidenceを後から捏造しない');
  expect(skill).toContain('authorization snapshot ID・revision');
  expect(skill).toContain('双方で`egress_policy=shareable`を明示');
  expect(skill).toContain('少なくとも1件');
  expect(skill).toContain('全8章にEvidence IDを捏造しない');
  expect(skill).toContain('現行で共有可能なEvidenceが少なくとも1件ない場合は正式調査済み扱いにせず');
});

it('uses one Markdown report with the canonical headings and no duplicate section body', () => {
  expect(skill).toContain('正規8見出しを順番どおり一度ずつ');
  expect(skill).toContain('公開URLをMarkdownリンク');
  expect(skill).toContain('表、Mermaid、公開HTTPS画像');
  expect(skill).toContain('`sections`は8章の根拠ID・注釈に限り、同じ本文を二重に書かない');
  expect(skill).toContain('本文を残すなら`report_markdown`を省略');
  expect(skill).toContain('正式概要の本文がChatGPTへの共有に適する場合は、保存操作で`egress_policy=shareable`を明示する');
});

it('sends supported relation candidates in the save call without claiming queued work is complete', () => {
  expectInOrder('`relation_candidate_manifest`', '`basis=brief_hypothesis`', '`basis=external_evidence`', '`fetch_idea_brief`');
  expect(skill).toContain('下書き関係整理まで進み、調査の許諾は待たない');
  expect(skill).toContain('`sections=[{index: 0}]`');
  expect(skill).toContain('正規8章を捏造しない');
  expect(skill).toContain('候補未提出の`pending`を通常の成功形にしない');
  expect(skill).toContain('`evidence_ids=[]`');
  expect(skill).toContain('`candidates: []`');
  expect(skill).toContain('`idea_id`は保存対象のIdea IDと一致させる');
  expect(skill).toContain('通常は別途`link_entities`や`classify_entity`を呼ばない');
  expect(skill).toContain('`pending`なら保存済み・候補未評価または再試行待ち');
  expect(skill).toContain('`leased`なら処理中');
  expect(skill).toContain('候補を省略した`pending`は自動で処理が進むと約束せず');
  expect(skill).toContain('`succeeded`なら整理完了');
  expect(skill).toContain('`failed`なら保存済み・整理失敗');
  expect(skill).toContain('`superseded`なら新しい版に置換済み');
  expect(skill).toContain('`unavailable`なら本文の保存結果だけを伝え');
  expect(skill).toContain('整理だけ失敗した場合はレポートを重複保存せず');
  expect(skill).toContain('曖昧な人物統合、削除、共有範囲の拡大には確認を得る');
  expect(skill).toContain('明示的な分類操作は既存の分類用ツールを別途使う');
});
