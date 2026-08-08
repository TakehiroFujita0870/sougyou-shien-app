const stages = ['発散', '反証', '深掘り', '一次検証', '決裁'];
export function App() {
  return <main><header><strong>Kadode</strong><span>アイデアを、構造で育てる。</span></header><section><p className="eyebrow">最初の一案</p><h1>始める前に、<br />ダメな理由を見つけよう。</h1><p>迎合しない反証、残る判断記録、検証までの道筋。</p><button>アイデアを登録する</button></section><section className="card"><h2>パイプライン</h2><ol>{stages.map((stage, index) => <li key={stage} className={index === 0 ? 'active' : ''}><span>{index + 1}</span>{stage}</li>)}</ol></section><section className="card"><h2>卒業の定義</h2><p>一次検証の結果を持ち、続ける・やめる・保留する理由を記録できた状態です。</p></section></main>;
}
