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
│   └── skills/
│       ├── orchestrate/SKILL.md     # パイプライン制御・初期化
│       ├── design/SKILL.md          # 設計書生成
│       ├── implement/SKILL.md       # ソースコード生成
│       ├── test-design/SKILL.md     # テスト仕様書生成
│       ├── consistency-check/SKILL.md  # Gate 1 & Gate 2
│       └── review-guide/SKILL.md    # レビュー対象マップ
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

## 検証ポイント

1. Claude CodeがSkillを正しく認識して順番に実行するか
2. Gate判定で問題を検出して差し戻しが機能するか
3. project_status.yamlでセッション再開できるか
4. SKILL.mdのサイズがContext Rotを起こさないか
5. 成果物の品質（設計書・コード・テストの整合性）
