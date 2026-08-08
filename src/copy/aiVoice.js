export const AI_TONES = {
  empowering: '利用者の経験と強みを具体的に見つけ、次の一歩を後押しする',
  candid: '迎合せず、失敗を避けるための反対意見を根拠とともに伝える',
  collaborative: '利用者の判断を主語にする',
  precise: '事実と提案を混ぜない',
};

export const AI_COPY_CATALOG = {
  welcome: {
    heading: 'あなたの経験から、事業の芽を育てよう。',
    body: 'まとまっていなくても大丈夫です。強みと現実的な懸念を一緒に整理し、無理のない次の一歩を選べます。',
  },
  empty: {
    heading: 'まだ記録はありません。',
    body: '気になる人、困りごと、制約の一つを起点にできます。',
  },
  input: {
    heading: 'あなたの言葉で書いてください。',
    body: 'AIは整理案を出しますが、内容を決めるのはあなたです。',
  },
  processing: {
    heading: '整理案を準備しています。',
    body: '確認できた事実と、AIの考えを分けて表示します。',
  },
  evidence: {
    heading: '確認できた事実',
    body: '出典や記録を開いて、元の情報を確かめられます。',
  },
  inference: {
    heading: 'AIの考え',
    body: '賛成材料と反対意見を同じ基準で示します。これは提案であり、事実やあなたの判断とは分けて扱います。',
  },
  uncertainty: {
    heading: 'まだ分からないこと',
    body: '法的な判断、資金調達の可否、成果の見込みは確定できません。',
  },
  nextStep: {
    heading: '次に確かめたいことを選べます。',
    body: '進める順番や、いったん保留にすることもあなたが決められます。',
  },
};

export const AI_OUTPUT_CONTRACT = ['facts', 'inference', 'uncertainty', 'userDecision'];

export function formatAiOutput({ facts = [], inference = '', uncertainty = [], userDecision = '' } = {}) {
  return { facts, inference, uncertainty, userDecision };
}
