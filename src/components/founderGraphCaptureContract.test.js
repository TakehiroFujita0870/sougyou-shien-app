import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';

const skill = readFileSync(fileURLToPath(new URL('../../plugins/dots/skills/founder-graph-capture/SKILL.md', import.meta.url)), 'utf8');

function expectInOrder(...phrases) {
  let cursor = -1;
  for (const phrase of phrases) {
    const next = skill.indexOf(phrase, cursor + 1);
    expect(next, `Expected "${phrase}" after the preceding capture step`).toBeGreaterThan(cursor);
    cursor = next;
  }
}

it('keeps draft capture, internal search, one proposal, permission, and both research routes in order', () => {
  expectInOrder('`capture_idea`', 'Dots内を検索', '`create_research_campaign`', '`approve_research_campaign`', '通常のWeb検索とDeep Research');
});

it('requires original public source metadata and distinct claim, evidence, run, and brief records', () => {
  expectInOrder('`capture_source`', '`append_claim`', '`capture_evidence`', '`record_research_run`', '`save_researched_idea_brief`');
  expect(skill).toContain('URL、資料タイトル');
  expect(skill).toContain('`egress_policy=shareable`');
  expect(skill).toContain('Runのsources欄だけでSourceやEvidenceが保存されたとは扱わない');
  expect(skill).toContain('authorization snapshot ID・revision');
  expect(skill).toContain('双方で`egress_policy=shareable`を明示する');
  expect(skill).toContain('全8章');
});

it('requires evidence for a researched brief without fabricating evidence for every chapter', () => {
  expect(skill).toContain('概要全体で少なくとも1件の現行・共有可能な出典Evidence');
  expect(skill).toContain('外部根拠に依拠する章だけに実在IDを紐付け');
  expect(skill).toContain('全8章にEvidence IDを捏造しない');
});

it('allows evidence based relationship updates without extra graph approval while retaining safety boundaries', () => {
  expectInOrder('追加の承認を求めず', '`link_entities`', '`supersedes_id`', '`expected_family_revision`');
  expect(skill).toContain('`retract_relation_assertion`');
  expect(skill).toContain('曖昧な人物統合、削除、共有範囲の拡大には確認を得る');
  expect(skill).toContain('URL・タイトルを推測で作らない');
  expect(skill).toContain('訂正後の検索で旧判断を現行として返さない');
});
