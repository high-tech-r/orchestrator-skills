# AI Orchestrator - Claude Code Skills構成

Claude Codeの CLAUDE.md + Skills でAIオーケストレーションパイプラインを実行する。
API従量課金不要。Claude Code（Pro/Maxプラン）の範囲内で動作。

## セットアップ

1. このディレクトリをプロジェクトルートとして使う（またはCLAUDE.mdとskillsを既存プロジェクトにコピー）
2. Claude Codeを起動

```bash
cd orchestrator-skills
claude
```

## 使い方

Claude Codeのプロンプトに要件を入力するだけ:

```
以下の要件でオーケストレーションを開始してください。

プロジェクト名: シンプルTODOアプリ
技術スタック: Python / FastAPI / SQLite
機能:
- F-001: タスク追加（タイトル必須、説明任意、作成日時自動記録）
- F-002: タスク一覧取得（作成日時降順、完了/未完了フィルタ）
```

Claude Codeが CLAUDE.md を読み、各Skillを順番に実行してパイプラインを回す。

## セッション再開

中断しても、次回Claude Code起動時に:

```
前回の続きからお願いします
```

project_status.yaml を読んで、前回の続きから再開する。

## ディレクトリ構成

```
orchestrator-skills/
├── CLAUDE.md                        # オーケストレーターのメインルール
├── .claude/
│   ├── settings.json                # 権限制御（Content Exclusion / permissions.deny）
│   └── skills/
│       ├── requirements/SKILL.md    # 要件定義（対話型）
│       ├── orchestrate/SKILL.md     # パイプライン制御・初期化
│       ├── design/SKILL.md          # 設計書生成
│       ├── implement/SKILL.md       # ソースコード生成
│       ├── test-design/SKILL.md     # テスト仕様書生成
│       ├── consistency-check/SKILL.md  # Gate 1 & Gate 2
│       └── review-guide/
│           ├── SKILL.md             # レビュー手順書生成
│           └── review_tier_definition.yaml  # Tier自動判定の定義
├── .github/
│   ├── workflows/
│   │   ├── security.yml             # レベル2セキュリティCI（品質ゲート）
│   │   └── dast-zap.yml             # DAST（OWASP ZAP・手動実行）
│   ├── dependabot.yml               # 依存パッケージの脆弱性スキャン
│   └── PULL_REQUEST_TEMPLATE.md     # AI利用チェック付きPRテンプレート
├── .pre-commit-config.yaml          # Gitleaks等のコミット前フック
├── .gitleaks.toml                   # シークレットスキャンのルール
├── .zap/rules.tsv                   # ZAP誤検知の抑制ルール
├── .gitignore
├── docs/
│   └── security/LEVEL2_SECURITY.md  # セキュリティ構成の解説・手順
├── example_requirements.yaml        # テスト用要件サンプル
└── README.md
```

## 実行後に生成される成果物

```
├── .orchestrator/
│   └── project_status.yaml   # 状態管理（再開地点）
├── docs/
│   ├── backlog.md             # バックログ
│   ├── design/F-001.md        # 設計書
│   ├── test_spec/F-001.md     # テスト仕様書
│   ├── consistency_report/    # 整合性レポート
│   └── review_map/F-001.md    # レビュー対象マップ
├── src/                       # ソースコード
└── tests/                     # テストコード
```

## セキュリティ（レベル2 / 無料ツールのみ）

AI駆動開発向けのレベル2セキュリティを無料ツールだけで組み込み済み。
詳細とセットアップ手順は [`docs/security/LEVEL2_SECURITY.md`](docs/security/LEVEL2_SECURITY.md) を参照。

- pre-commit（Gitleaks）でコミット前にシークレットをブロック
- GitHub Actions（`Security (Level 2)`）でPR時に TruffleHog / Semgrep / Trivy / pip-audit / OSV-Scanner を自動実行し、品質ゲートでマージを制御
- Dependabot・Secret scanning・Socket(OSS無料App) はリポジトリ設定で有効化（手動）
- DAST（OWASP ZAP）は手動実行ワークフロー
- `.claude/settings.json` の `permissions.deny` で機密ファイルをAIから遮断

### このリポジトリを使い始めるとき（フォーク／クローン後の手動ステップ）

ファイルを置くだけでは完結しない設定がある。**フォークしたら必ず以下を実施**すること（すべて無料）。

1. **ローカルフック**（各開発者が1回）
   ```bash
   pip install pre-commit && pre-commit install
   ```
2. **Dependabot alerts / security updates** を有効化
   → Settings → Code security → 両方を Enable
3. **Secret scanning（push protection）** を有効化
   → Settings → Code security → Enable（public リポジトリは無料）
4. **Socket GitHub App** をインストール（slopsquatting対策の本命）
   → https://socket.dev から導入（OSSリポジトリは無料）
5. **ブランチ保護で品質ゲートを必須化**
   → Settings → Branches → main の保護ルールで `Security (Level 2)` を Required に設定
   （これで合格するまで物理的にマージ不可になる）
6. **Semgrep の AI生成コード特化ルール**を有効化
   → https://semgrep.dev/explore で AI Security / Shadow AI パックの最新名を確認し、
   `.github/workflows/security.yml` のコメント箇所を有効化

各ステップの背景と詳細は [`docs/security/LEVEL2_SECURITY.md`](docs/security/LEVEL2_SECURITY.md) を参照。

## 検証ポイント

1. Claude CodeがSkillを正しく認識して順番に実行するか
2. Gate判定で問題を検出して差し戻しが機能するか
3. project_status.yamlでセッション再開できるか
4. SKILL.mdのサイズがContext Rotを起こさないか
5. 成果物の品質（設計書・コード・テストの整合性）
6. セキュリティCI（`Security (Level 2)`）が生成物に対して品質ゲートとして機能するか
