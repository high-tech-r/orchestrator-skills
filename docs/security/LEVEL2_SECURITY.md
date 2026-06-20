# レベル2セキュリティ構成（無料ツールのみ）

このリポジトリに組み込んだ、AI駆動開発向けレベル2セキュリティの実体ファイルと、
有効化に必要な手動ステップをまとめる。**すべて無料ツールで構成**している
（Snyk有料 / FOSSA有料 / Portkey / Burp Pro / GitGuardian は不採用）。

## 何が入っているか

| # | カテゴリ | 採用ツール（無料） | 実体ファイル | ブロック |
|---|---|---|---|---|
| 1 | シークレット | Gitleaks（pre-commit）＋ TruffleHog（CI） | `.pre-commit-config.yaml`, `.gitleaks.toml`, `security.yml` | ✅ |
| 2 | SCA（脆弱性） | Dependabot ＋ Trivy ＋ OSV-Scanner（多言語）／ pip-audit（Python任意） | `dependabot.yml`, `security.yml` | ✅ |
| 3 | SCA（slopsquatting） | Socket GitHub App ＋ OSV-Scanner ＋ lockfile運用 | `security.yml`（OSV）＋ 手動 | 一部 |
| 4 | SAST（汎用） | Semgrep OSS CLI | `security.yml` | ✅ |
| 5 | SAST（AI特化） | Semgrep AI Security / Shadow AI（無料パック） | `security.yml` | ✅ |
| 6 | ライセンス | Trivy（license スキャナ） | `security.yml` | ✅ |
| 7 | Content Exclusion | Claude Code `permissions.deny` | `.claude/settings.json`, `.gitignore` | ✅ |
| 8 | DAST | OWASP ZAP Baseline | `dast-zap.yml` | 警告 |
| 9 | LLMゲートウェイ | （レベル3のため対象外） | — | — |

ブロック列「✅」= 検出時にCIが失敗し、PRのマージを自動拒否する（品質ゲート）。
これがレベル1（人間レビュー頼み）との本質的な違い。

## セットアップ手順

### 1. ローカル（各開発者が1回だけ）

```bash
pip install pre-commit
pre-commit install          # 以後、コミット時にGitleaksが自動実行
pre-commit run --all-files  # 既存ファイルを一括スキャン（任意）
```

### 2. CI（コミット不要・自動で動く）

`.github/workflows/security.yml` はPR作成時とmainへのpushで自動実行される。
追加設定は不要。

### 3. リポジトリ設定（GitHub UI / 無料・要手動）

GitHubの画面でのみ有効化できる無料機能。Settings から1回だけ設定する。

- **Dependabot alerts / security updates**：Settings → Code security → 両方を Enable
- **Secret scanning（push protection）**：Settings → Code security → Enable
  （public リポジトリは無料）
- **Socket（slopsquatting対策の本命）**：https://socket.dev から GitHub App を
  インストール（OSSリポジトリは無料）。PRごとに新規パッケージの振る舞いを分析する。
- **必須ステータスチェック**：Settings → Branches → main の保護ルールで
  `Security (Level 2)` の各ジョブを "Required" にすると、合格まで物理的にマージできない。

## カテゴリ別のメモ

### 言語非依存について（重要）
本構成は特定言語に依存しない。Trivy / OSV-Scanner / Semgrep / TruffleHog が
リポジトリ内の言語・lockfile を**自動判定**してスキャンする。言語ごとに必要な調整は
最小限で、**オーケストレーター（`orchestrate` スキル）が初期化時に自動で行う**
（利用者はYAMLを手で触らない）。

- **`dependabot.yml`**: 既定で有効なのは `github-actions` と `docker` のみ。
  `tech_stack.language` に応じた `package-ecosystem`（`pip` / `npm` / `gomod` /
  `bundler` 等）を、初期化時にオーケストレーターが有効化する。
  （手動でやる場合は該当ブロックのコメントを外すだけ）
- **`security.yml` の Semgrep**: `p/default` が言語を自動判定。特定言語に寄せたい
  ときだけ `p/python` `p/javascript` 等を足す。
- **`pip-audit` ジョブ**: Python専用の任意層。`requirements*.txt` が無ければ自動スキップ。
- **`dast-zap.yml`**: アプリのポートは `app_port` 入力で指定（既定 8000）。

### 3. slopsquatting について
従来のSCA（Dependabot/Trivy/OSV）は **CVEベース** なので、CVEの付かない
slopsquattingパッケージは検出できない。本命は **Socket の振る舞い分析**（無料App、
npm/PyPI/Go/Maven等10+エコシステム対応）。CIの OSV-Scanner は既知の悪性アドバイザリ
照合の補助層。加えて運用で固める：

- AIが提案したパッケージをそのまま `install` しない（各レジストリ公式でDL数・更新日を確認）
- lockfile（`package-lock.json` / `poetry.lock` / `go.sum` 等）をコミットし、差分をレビューで必ず見る
- CIは lockfile ベースでインストールする

### 5. SemgrepのAIルールについて
無料の AI Security / Shadow AI パックは `security.yml` 内のコメントで有効化箇所を
示している。公式レジストリ（https://semgrep.dev/explore）でのパック名は更新されることが
あるため、導入時に最新のスラッグを確認すること。Semgrep Guardian と Agent Skills(Pro)
パックは**有料**なので本構成では不採用。

### 7. Content Exclusion の注意
`.claude/settings.json` の `permissions.deny` は機密ファイルの読み取りを確実に止める。
`.claudeignore` は Read ツールを防げないバグ報告があるため、`permissions.deny` を正とする。

### 8. DAST の注意
`dast-zap.yml` は起動済みアプリが必要なため、手動実行（workflow_dispatch）または
ステージングデプロイ後の実行を想定。`docker-compose` でアプリを立ち上げてから
スキャンする（ポートは `app_port` 入力で指定・既定 8000）。初期は警告止まり
（`fail_action: false`）。

## このリポジトリでの位置づけ
生成されたソースは `src/` `tests/`、依存は各言語の依存定義ファイル（`requirements.txt` /
`package.json` / `go.mod` 等）に出力される。本構成はそれらを言語非依存で
リポジトリ単位でスキャンするため、**AIが生成したコードがそのまま品質ゲートを通る**。
