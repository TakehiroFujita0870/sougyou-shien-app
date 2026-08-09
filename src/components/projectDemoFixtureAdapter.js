// Explicit admin/demo boundary. This fixture contains no real user data and must not be used by runtime auth.
export const demoProjectFixture = {
  name: '製造現場向け省エネ診断',
  status: '採用済み',
  sections: {
    事業: { status: '整理済み', summary: '工場の設備データを診断し、削減施策を提案するサービス。', evidence: '顧客課題インタビュー 6件', unknown: '導入後の運用体制' },
    市場: { status: '仮説', summary: '脱炭素投資を進める中堅製造業を初期市場とする。', evidence: '公開統計と業界レポート', unknown: '有料導入可能な社数' },
    競合: { status: '比較済み', summary: '大手SIerの総合提案と、専門コンサルの間に機会がある。', evidence: '競合3社の公開サービス比較', unknown: '現場定着率の差' },
    利益: { status: '試算済み', summary: '診断費と継続利用料の二本立てで粗利を確保する。', evidence: '初年度の単価・原価試算', unknown: '営業獲得コスト' },
    実現性: { status: '検証中', summary: '既存センサー連携の小規模実証から開始できる。', evidence: '連携方式の技術検証メモ', unknown: '複数拠点展開の負荷' },
  },
};
