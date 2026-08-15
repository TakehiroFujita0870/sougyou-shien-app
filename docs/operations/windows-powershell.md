# Windows / PowerShell の安全なエージェント運用

最終検証日: 2026-08-09

## 目的と適用範囲

Windows版Codexで、パス、文字コード、外部CLI、ファイル操作、GitHub CLIを安全に扱うための実行規約である。PowerShellを標準シェルとし、Git Bashはbash構文でしか検査できない限定用途にだけ使う。OS設定、`PATH`、認証情報、依存関係、アプリコード、CIランナーはこの手順で変更しない。

リポジトリ全体の変更規律は[AGENTS.md](../../AGENTS.md)、AIモデルとAPIの運用は[モデルライフサイクル](model-lifecycle.md)を参照する。継承資料の`docs/inherited/`は参照専用である。

## 基本ルール

- コマンドはPowerShellで実行し、`workdir`にはOneDrive配下、日本語、空白を含む可能性がある絶対パスを指定する。
- ファイル名検索には`rg --files`、本文検索には`rg -n`を使う。PowerShellでパスを渡すときはワイルドカード解釈を避けるため`-LiteralPath`を使う。
- UTF-8の文書を読むときは`Get-Content -Raw -Encoding UTF8 -LiteralPath`を使う。既存ファイルの編集は`apply_patch`で行い、`echo`、`cat`、`>`、`>>`、here-stringによる書込みは使わない。
- `npm`、`uv`、`gh`、`git`は単純なコマンドを優先する。条件分岐や業務ロジックが必要なら、シェルの複雑な一行ではなくNode.jsまたはPythonのスクリプトに移す。
- `HOME`、`home`、`CODEX_HOME`は作業変数名に使わない。環境変数の意味を上書きしない。

### セッション開始時のUTF-8初期化

リポジトリのpreflightをdot-sourceする。これはConsoleと現在のプロセスだけを変更し、profile、レジストリ、PATH、認証情報、ファイルへ書き込まない。Windows PowerShell 5.1でも利用できる。

```powershell
. .\scripts\powershell\Initialize-Utf8Preflight.ps1
if (-not (Test-Utf8Preflight)) { throw 'UTF-8 preflight failed' }
Test-Utf8ReadBack -LiteralPath .\scripts\powershell\fixtures\日本語パス.txt
```

別プロセスの安全確認は、未初期化なら非ゼロで停止する。

```powershell
powershell.exe -NoProfile -File .\scripts\powershell\Initialize-Utf8Preflight.ps1 -Check
```

この診断に合格しても日本語本文の直接パイプは禁止する。本文はUTF-8ファイルまたはNode.jsのUTF-8 Bufferで送信し、read-back完全一致を確認する。

PowerShellを使うセッションでは、最初に入出力エンコーディングをUTF-8（BOMなし）にそろえる。これは画面表示とASCIIのみの制御データを安定させるための初期化であり、日本語本文をネイティブCLIへ直接パイプしてよいという意味ではない。

```powershell
$utf8NoBom = [Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
```

初期化後も、非ASCII本文の送信は「CLI引数と長い本文」の安全経路だけを使う。文字列をPowerShellのパイプラインに渡す経路は、`$OutputEncoding`の設定値や子プロセス実装に左右されるため、本文送信の安全策にしない。

### 安全な検索・読取

```powershell
rg --files -g 'AGENTS.md' -g 'docs/**'
rg -n 'TODO|FIXME' -g '*.ts'
Get-Content -Raw -Encoding UTF8 -LiteralPath 'C:\Users\user\OneDrive - 会社\開発\創業 支援\AGENTS.md'
```

`Get-Content path\*.md`のようにワイルドカードに依存した参照や、既定文字コードに委ねたUTF-8文書の読取は禁止する。

## 編集と破壊操作

変更は`apply_patch`を使う。次は編集手段として禁止する。

```powershell
echo 'text' > docs\guide.md
cat <<'EOF' > docs\guide.md
...
EOF
```

削除や移動はPowerShellの中だけで完結させ、`cmd.exe`、Git Bash、PowerShellをまたがない。再帰操作の前に対象を絶対パスへ解決し、意図した作業ツリー内であることを確認する。

```powershell
$targetPath = (Resolve-Path -LiteralPath '.\tmp\generated').Path
if ($targetPath -notlike 'C:\Users\user\OneDrive - 会社\開発\創業 支援\tmp\*') {
  throw "対象外のパスです: $targetPath"
}
Remove-Item -LiteralPath $targetPath -Recurse -Force
```

未解決の環境変数、グロブ、ドライブ直下、ホームディレクトリ、リポジトリ全体を再帰削除・移動の対象にしない。削除や移動の前後に対象パスを記録し、Gitで追跡されるファイルは`git status --short`で確認する。

## CLI引数と長い本文

PowerShellでは複数行のコマンド出力が`string[]`になる。これを外部CLIの単一引数として渡すと、各行が別引数に展開され、Issue/PR本文が壊れることがある。

```powershell
# 危険: 各行が別の引数になり得る
$bodyLines = @('## 目的', '', '- 変更内容')
gh pr create --body $bodyLines

# 安全: 一つの文字列に結合する
$body = $bodyLines -join [Environment]::NewLine
# 非ASCII本文を gh へ直接渡さず、下記のUTF-8ファイル又はNode.js方式を使う
```

長いIssue/PR本文、Markdown、引用符を含む本文は、引数に押し込まない。ただし、非ASCII本文をPowerShellからネイティブCLIへ直接パイプしてはならない。PowerShellの`$OutputEncoding`と`[Console]::OutputEncoding`は別物であり、プロセスごとの既定値も異なる。片方をUTF-8へ変更しても、送信経路全体が安全とは限らない。例えば`$OutputEncoding`がUS-ASCIIのままなら、日本語の複数行文字列を`$newBody | gh issue edit --body-file -`へ渡した時点で`?`へ置換される。

安全な方式は次のいずれかである。

1. 本文をUTF-8ファイルとして`apply_patch`で作成し、`gh`の`--body-file`へそのファイルのパスを渡す。
2. Node.jsの`spawnSync`からUTF-8 `Buffer`を標準入力へ渡す。PowerShellからNode.jsへスクリプトをパイプする場合、スクリプト本文はASCIIだけにし、日本語データはUTF-8 Base64またはUTF-8ファイルで渡す。

```powershell
# `$newBody` はPowerShell内だけで扱い、Base64はASCIIとして環境変数へ渡す。
$env:ISSUE_BODY_BASE64 = [Convert]::ToBase64String(
  [Text.Encoding]::UTF8.GetBytes($newBody)
)

# -e のスクリプトはASCIIだけで構成する。
node -e "const{spawnSync}=require('node:child_process');const input=Buffer.from(process.env.ISSUE_BODY_BASE64,'base64');const r=spawnSync('gh',['issue','edit','33','--body-file','-'],{input,stdio:'inherit'});process.exit(r.status??1)"
```

`$newBody | gh issue edit --body-file -`や`$body | gh pr create --body-file -`は、本文が日本語など非ASCIIを含む場合の送信手段として禁止する。パイプラインへ渡す値は、シークレットを含めない。本文を再利用する場合も、`$bodyLines -join [Environment]::NewLine`のように一つの文字列へ明示的に結合する。

## Remote本文のread-back検査と停止条件

IssueまたはPR本文を更新した直後に、APIから本文をread-backする。連続する`???`、置換文字U+FFFD、日本語文字数、必須見出しに加え、送信元UTF-8ファイルとの完全一致を検査する。これにより、文字化けだけでなく本文末尾や指示の欠損も検出する。いずれかが不正なら更新を完了扱いにせず、以後のIssue/PR更新、コミット、pushを停止する。

```powershell
node -e "const{spawnSync}=require('node:child_process');const r=spawnSync('gh',['api','repos/TakehiroFujita0870/dots/issues/33'],{encoding:'buffer'});if(r.status)process.exit(r.status);const body=JSON.parse(r.stdout.toString('utf8')).body??'';const ja=(body.match(/[\u3040-\u30ff\u3400-\u9fff]/g)||[]).length;const required=['## 目的','## 受入条件'];if(/\?{3,}|\uFFFD/.test(body)||ja===0||required.some(x=>!body.includes(x)))throw Error('Issue本文のread-back検査に失敗');"
```

送信元のUTF-8ファイルを`body.md`として保存した場合は、次の完全一致検査を続けて実行する。Node.jsのプログラム本体はASCIIだけであり、本文はファイルからUTF-8で読む。改行コードの差だけは正規化する。

```powershell
node -e "const{readFileSync}=require('node:fs');const{spawnSync}=require('node:child_process');const expected=readFileSync('body.md','utf8').replace(/\r\n/g,'\n');const r=spawnSync('gh',['api','repos/TakehiroFujita0870/dots/issues/33'],{encoding:'buffer'});if(r.status)process.exit(r.status);const actual=(JSON.parse(r.stdout.toString('utf8')).body??'').replace(/\r\n/g,'\n');if(actual!==expected)throw Error('Issue本文が送信元と一致しない');"
```

PRではAPIパスを`repos/TakehiroFujita0870/dots/pulls/<PR番号>`へ替え、PRで必要な見出しと`Closes #33`を`required`へ加える。本文の更新に成功したというCLIの終了コードだけを、文字化けしていない根拠にしない。

### 再発防止の確認例

この不具合ではIssue #8〜#25を復旧し、全21 Issueの横断read-back検査が合格した。今後も同じ方式で、個別の修正後と一括更新後の両方を検査してから完了とする。

## GitHub CLIとPATHの診断

Git Bashで`gh`が動いても、CodexまたはPowerShellのプロセスが同じ`PATH`と認証状態とは限らない。`PATH`や認証情報を変更せず、実行対象のPowerShellプロセスで診断する。

```powershell
Get-Command gh -All
gh --version
gh auth status
Get-Command git -All
git --version
```

`gh`が見つからない、または認証に失敗する場合は、出力から実行ファイルの有無と対象プロセスの状態だけを報告する。別シェルの成功を根拠にせず、`PATH`の変更、資格情報の再設定、互換コピーの作成はしない。認証トークン、Cookie、設定内容はIssue、PR、ログへ記録しない。

## ローカル検査とUbuntu CI

ローカルではPowerShellから、変更範囲に応じて次を実行する。

```powershell
npm run test
npm run build
npm run build-storybook
uv run pytest
git diff --check
```

Ubuntu CIはbash、Linuxパス、ケースセンシティブなファイルシステムで実行される。PowerShellで成功しても、次を別途確認する。

- スクリプトがbash構文、Linuxのパス区切り、実行権限、ファイル名の大文字・小文字に依存していないこと。
- CI固有の環境変数、シークレット、ランナー設定をローカルから変更しないこと。
- CI結果を確認し、失敗時はログを根拠に修正または未検査としてPRへ記載すること。

CI通過後はリポジトリの承認ルールに従って自動マージしてよい。固定的なStageゲートを復活させず、変更範囲に応じた検査と既存CIを使う。

## PR作成前の確認

```powershell
git status --short
git diff --check
git diff -- AGENTS.md docs/operations/windows-powershell.md
```

PR本文には目的、受入条件との対応、実行した検査、影響の有無を記載し、Issueを完了するPRでは`Closes #33`を含める。mainへ直接pushせず、1 Issueを1 PRで扱う。
