# WSLを主要開発環境にする

最終検証日: 2026-08-09

## ローカル接続先

- Nebulaアプリ: `http://localhost:5174/`
- ローカルAPIヘルスチェック: `http://localhost:8000/health`

画面確認、スクリーンショット、引き継ぎではこのポートを共通で使う。変更比較時は同じ最新`main`、または同じfeature worktreeからアプリを起動する。

## 役割

Windows版Codexでは、PowerShellをWindows制御面、Ubuntu WSL2をアプリケーション実行面として使う。PowerShellの文字コード、外部CLI、GitHub本文の規約は[Windows / PowerShell の安全なエージェント運用](windows-powershell.md)に従う。

Node、npm、uv、Python、FastAPI、Vite、SQL関連のコマンドはWSL内で実行する。Windows側のcloneは閲覧またはWindows固有の制御操作に限定する。

## 初回確認

PowerShellから次を実行する。`Ubuntu`は導入済みdistribution名の例である。

```powershell
wsl.exe --status
wsl.exe -l -v
wsl.exe -d Ubuntu -u <user> -- bash -lc 'id; ps -p 1 -o comm='
```

対象distributionがWSL 2、対象ユーザーが想定どおり、PID 1が`systemd`であることを確認する。資格情報を表示、保存、送信しない。

## cloneと依存同期

clone、`node_modules`、`.venv`はLinuxファイルシステムだけに置く。`/mnt/c`、OneDrive、Windows側cloneで`npm ci`や`uv sync`を実行しない。

```powershell
wsl.exe -d Ubuntu -u <user> -- bash -lc 'mkdir -p /home/<user>/projects'
wsl.exe -d Ubuntu -u <user> -- git clone https://github.com/TakehiroFujita0870/sougyou-shien-app.git /home/<user>/projects/nebula
wsl.exe -d Ubuntu -u <user> -- bash -lc 'cd /home/<user>/projects/nebula && git checkout main && git pull --ff-only origin main'
wsl.exe -d Ubuntu -u <user> -- bash -lc 'cd /home/<user>/projects/nebula && npm ci && uv sync --all-groups'
```

依存同期は`package-lock.json`または`uv.lock`が変わったときに行う。WSL内で確認する。

```powershell
wsl.exe -d Ubuntu -u <user> -- bash -lc 'cd /home/<user>/projects/nebula && command -v node npm uv python3 && node --version && uv --version && git status --short'
```

## Git同期とworktree

WindowsとWSLのclone間でファイルをコピーしない。各cloneはGitで同期し、mainへ直接pushしない。

```powershell
wsl.exe -d Ubuntu -u <user> -- bash -lc 'cd /home/<user>/projects/nebula && git fetch origin && git checkout main && git pull --ff-only origin main'
wsl.exe -d Ubuntu -u <user> -- bash -lc 'cd /home/<user>/projects/nebula && git worktree add -b codex/issue-<number>-<topic> /home/<user>/projects/nebula-issue-<number> origin/main'
```

worktree側で検査、commit、branchへのpush、PR作成を行う。PR本文の日本語は[PowerShell運用文書](windows-powershell.md)のUTF-8ファイルとread-back手順を使う。

## 検査

```powershell
wsl.exe -d Ubuntu -u <user> -- bash -lc 'cd /home/<user>/projects/nebula && npm run test'
wsl.exe -d Ubuntu -u <user> -- bash -lc 'cd /home/<user>/projects/nebula && npm run build'
wsl.exe -d Ubuntu -u <user> -- bash -lc 'cd /home/<user>/projects/nebula && uv run pytest && git diff --check'
```

## UIとAPIの起動

systemd userのtransient unitでViteとローカルFastAPIを起動する。サービスは外部資格情報を使わないlocal/fake構成である。

```powershell
wsl.exe -d Ubuntu -u <user> -- systemd-run --user --unit nebula-vite --property WorkingDirectory=/home/<user>/projects/nebula --collect /usr/bin/npm run dev -- --host 0.0.0.0 --port 5174
wsl.exe -d Ubuntu -u <user> -- systemd-run --user --unit nebula-api --property WorkingDirectory=/home/<user>/projects/nebula --collect /home/<user>/.local/bin/uv run uvicorn --app-dir backend nebula.main:app --host 0.0.0.0 --port 8000
```

状態、ログ、停止、ポート競合を確認する。

```powershell
wsl.exe -d Ubuntu -u <user> -- systemctl --user status nebula-vite nebula-api
wsl.exe -d Ubuntu -u <user> -- journalctl --user -u nebula-vite -u nebula-api -f
wsl.exe -d Ubuntu -u <user> -- systemctl --user stop nebula-vite nebula-api
wsl.exe -d Ubuntu -u <user> -- ss -ltnp '( sport = :5174 or sport = :8000 )'
```

Windows側からHTTPを確認する。

```powershell
(Invoke-WebRequest -UseBasicParsing http://localhost:5174/).StatusCode
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/health).StatusCode
```

ViteまたはAPIのunitが存在しない場合は、WSL停止後にtransient unitが破棄された状態である。上の起動コマンドを再実行する。恒久的なunit配布は別Issueで決定する。

## 障害対応

- `node`または`npm`が`/mnt/c`を指す場合は、WSL native Node/npmを導入して新しいWSLシェルで再確認する。
- ポートが使用中の場合は`ss`で所有プロセスを確認し、既存の`nebula-vite`または`nebula-api` unitを停止する。対象不明のプロセスを終了しない。
- `git pull --ff-only`が失敗した場合は、未コミット変更を`git status --short`で確認し、他作業の変更を復元または削除せずにbranchへ退避する。
- submodule取得やGitHub認証が必要になった場合は、認証情報を設定せず、必要な権限を報告して停止する。
