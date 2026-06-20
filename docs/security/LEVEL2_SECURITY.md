# レベル2セキュリティ構成（無料ツールのみ）

このリポジトリに組み込んだ、AI駆動開発向けレベル2セキュリティの実体ファイルと、
有効化に必要な手動ステップをまとめる。**すべて無料ツールで構成**している
（Snyk有料 / FOSSA有料 / Portkey / Burp Pro / GitGuardian は不採用）。

## 何が入っているか

| # | カテゴリ | 採用ツール（無料） | 実体ファイル | ブロック |
|---|---|---|---|---|
| 1 | シークレット | Gitleaks（pre-commit）＋ TruffleHog（CI） | `.pre-commit-config.yaml`, `.gitleaks.toml`, `security.yml` | ✅ |
| 2 | SCA（脆弱性） | Dependabot ＋ Trivy ＋ pip-audit | `dependabot.yml`, `security.yml` | ✅ |
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

### 3. slopsquatting について
従来のSCA（Dependabot/Trivy/pip-audit）は **CVEベース** なので、CVEの付かない
slopsquattingパッケージは検出できない。本命は **Socket の振る舞い分析**（無料App）。
CIの OSV-Scanner は既知の悪性アドバイザリ照合の補助層。加えて運用で固める：

- AIが提案したパッケージをそのまま `install` しない（PyPI公式でDL数・更新日を確認）
- `requirements.txt` / lockfile をコミットし、差分をレビューで必ず見る
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
ステージングデプロイ後の実行を想定。生成プロジェクトの `docker-compose.yaml` を
立ち上げてからスキャンする。初期は警告止まり（`fail_action: false`）。

## このリポジトリでの位置づけ
生成されたソースは `src/` `tests/`、依存は `requirements*.txt`、コンテナは
`Dockerfile`/`docker-compose.yaml` に出力される（CLAUDE.md参照）。本構成はそれらを
リポジトリ単位でスキャンするため、**AIが生成したコードがそのまま品質ゲートを通る**。
