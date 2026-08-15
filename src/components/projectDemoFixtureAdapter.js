// Explicit admin/demo boundary. Mirrors the PII-free synthetic dataset from #139.
// This adapter is presentation-only and must not be used by runtime auth or user data.
export const demoProjectFixture = {
  datasetId: 'dots-admin-demo-v1',
  provenance: 'synthetic_demo',
  name: '現場改善ミニ診断（合成デモ）',
  status: '採用済み',
  overview: '現場で見つかった改善の芽を、低リスクの検証計画と事業計画書まで育てるための小さな伴走サービスです。',
  sections: {
    'どんな事業？': { status: '整理済み', summary: '製造現場の改善候補を短時間で整理するサービス。', evidence: '匿名化済み課題要約', unknown: '経験知を診断テンプレートへ転換できる範囲' },
    '市場はある？': { status: '仮説', summary: '反復課題を持つ小規模事業者を初期顧客候補とする。', evidence: '合成市場メモ', unknown: '有料導入可能な社数' },
    '競合は誰？': { status: '比較済み', summary: '同種サービス、専門家相談、社内改善会議の3分類で比較する。', evidence: '合成市場メモ', unknown: '短納期と現場言語の差別化効果' },
    '利益はでる？': { status: '試算済み', summary: '月次base/upside/downsideを決定的に試算し、固定費回収を確認する。', evidence: '合成市場メモ', unknown: '継続率と営業獲得コスト' },
    '実現できる？': { status: '検証中', summary: '週6時間・家計資金5万円以内の可逆な週末実験から開始する。', evidence: '匿名化済み課題要約', unknown: '2週連続で上限を超えない運用' },
  },
  decisions: [
    { id: 'decision-1', kind: '採用', date: '2026/08/09', title: '現場改善ミニ診断として深掘り', reason: '既存の経験と低コストで始められる条件が揃ったため。' },
    { id: 'decision-2', kind: '保留', date: '2026/08/08', title: '初期価格の決定', reason: '顧客ヒアリングで支払意向を確認してから決める。' },
    { id: 'decision-3', kind: '却下', date: '2026/08/07', title: '大規模な個別開発', reason: '週末実験の範囲を超えるため、現時点では採用しない。' },
  ],
};
