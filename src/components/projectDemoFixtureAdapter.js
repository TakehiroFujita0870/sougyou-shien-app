// Explicit admin/demo boundary. Mirrors the PII-free synthetic dataset from #139.
// This adapter is presentation-only and must not be used by runtime auth or user data.
export const demoProjectFixture = {
  datasetId: 'kadode-admin-demo-v1',
  provenance: 'synthetic_demo',
  name: '現場改善ミニ診断（合成デモ）',
  status: '採用済み',
  sections: {
    事業: { status: '整理済み', summary: '製造現場の改善候補を短時間で整理するサービス。', evidence: '匿名化済み課題要約', unknown: '経験知を診断テンプレートへ転換できる範囲' },
    市場: { status: '仮説', summary: '反復課題を持つ小規模事業者を初期顧客候補とする。', evidence: '合成市場メモ', unknown: '有料導入可能な社数' },
    競合: { status: '比較済み', summary: '同種サービス、専門家相談、社内改善会議の3分類で比較する。', evidence: '合成市場メモ', unknown: '短納期と現場言語の差別化効果' },
    利益: { status: '試算済み', summary: '月次base/upside/downsideを決定的に試算し、固定費回収を確認する。', evidence: '合成市場メモ', unknown: '継続率と営業獲得コスト' },
    実現性: { status: '検証中', summary: '週6時間・家計資金5万円以内の可逆な週末実験から開始する。', evidence: '匿名化済み課題要約', unknown: '2週連続で上限を超えない運用' },
  },
};
