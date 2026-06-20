# AI Orchestrator - 一人SIerモデル

## 概要

このプロジェクトはAIオーケストレーションで「設計→実装→テスト→チェック」のパイプラインを回す。
ユーザー（Kojiro）が要件を自然言語で指示し、各Skillを順番に実行して成果物を生成する。

## パイプラインフロー

```
要件定義（対話型）→ [承認] → 設計 → [Gate 1] → 実装＋テスト設計（並列） → テストコード生成 → [Gate 2] → レビューガイド → 人間レビュー
```

## 実行ルール

### 1. 状態管理
- `.orchestrator/project_status.yaml` を常に最新に保つ
- 各ステップの開始時に status を "in_progress" に、完了時に "done" に更新
- セッション開始時は必ず project_status.yaml を読んで、前回の続きから再開する

### 2. 機能単位で処理する
- バックログの1アイテム（1機能）を処理の基本単位とする
- 1機能の全工程が完了してから次の機能に進む

### 3. Gate判定
- Gate 1（設計レビュー）: 設計完了後、要件カバレッジ・矛盾・曖昧性をチェック
- Gate 2（整合性チェック）: 実装＋テスト完了後、設計書⇔コード⇔テストの突合
- 各Gateのやり直し上限は3回。超えたらユーザーにエスカレーション

### 4. 成果物の保存場所
```
project_root/
├── .orchestrator/
│   └── project_status.yaml
├── docs/
│   ├── requirements.md    # 要件定義書（Phase 0で生成）
│   ├── backlog.md
│   ├── design/           # 機能別の設計書
│   ├── test_spec/         # 機能別のテスト仕様書
│   ├── consistency_report/
│   └── review_map/
├── src/                   # ソースコード
├── tests/                 # テストコード
├── requirements.txt       # 本番依存パッケージ（必須）
├── requirements-dev.txt   # 開発用依存パッケージ（必須）
├── Dockerfile             # コンテナ定義（必須）
├── docker-compose.yaml    # コンテナ構成（必須）
└── .dockerignore
```

### 5. Skill呼び出し順序
0. `requirements` — 要件定義（対話型。ユーザー承認まで次に進まない）
1. `orchestrate` — パイプライン開始・再開時に最初に呼ぶ
2. `design` — 設計書生成
3. `consistency-check` — Gate 1（設計レビュー）
4. `implement` — ソースコード生成
5. `test-design` — テスト仕様書生成（4と並列可）
6. `consistency-check` — Gate 2（設計⇔コード⇔テスト突合 + Tier判定妥当性検証）
7. `review-guide` — テスト手順書生成（`review_tier_definition.yaml` に基づくTier自動判定）

### 6. 差し戻し時のルール
- 問題点と修正方針を具体的に指示に含める
- feedback_historyに全履歴を残す（同じ指摘の繰り返しを防ぐ）
- 差し戻し先は問題の原因に応じて最小限の工程に戻す

### 7. セキュリティ（レベル2 / 無料ツールのみ）
生成物はリポジトリのセキュリティCI（`.github/workflows/security.yml`）で品質ゲートにかかる。
コード・依存を生成する際は次を守る:
- ハードコードされたシークレットを出力しない（Gitleaks/TruffleHogでブロックされる）
- 実在性が確認できないパッケージを追加しない（slopsquatting対策。`implement` スキル参照）
- 機密ファイル（.env, *.pem, *.key 等）は `.claude/settings.json` の `permissions.deny` で読み取り禁止
- 構成の全体像は `docs/security/LEVEL2_SECURITY.md`
