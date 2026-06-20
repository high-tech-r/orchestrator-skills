# Skill: orchestrate（パイプライン制御）

## いつ使うか
- 新しいプロジェクトを開始するとき
- セッションを再開するとき（project_status.yamlを読んで続きから）
- 「オーケストレーション開始」「パイプライン実行」等の指示を受けたとき

## プロジェクト初期化

ユーザーから要件を受け取ったら、以下を作成する。

### 1. backlog.md を作成

```markdown
# プロダクトバックログ

## サマリー
- 全項目数: N
- 完了: 0 / 進行中: 0 / 未着手: N

## バックログ

| ID | 機能名 | 優先度 | ステータス | Tier | 概要 |
|----|--------|--------|-----------|------|------|
| F-001 | xxx | 高 | ⬜ 未着手 | 中 | xxx |
```

### 2. project_status.yaml を作成

```yaml
project:
  name: "プロジェクト名"
  type: "new"
  scale: "light"  # light / standard / medium
  tech_stack:
    language: ""
    framework: ""
    database: ""
    frontend: ""
  created_at: "YYYY-MM-DD"
  updated_at: "YYYY-MM-DD"

current:
  feature_id: "F-001"
  phase: "requirements"  # requirements / design / gate1 / implement / test_design / test_code / gate2 / review_guide / done
  iteration: 0

features:
  F-001:
    name: "xxx"
    status: "pending"    # pending / in_progress / done / escalation
    gate1_iterations: 0
    gate2_iterations: 0
```

### 3. 環境構築ファイルを作成（必須）

プロジェクト初期化時に、技術スタックに応じて以下を**必ず**生成する。
これらは後から追加ではなく、最初に用意する。開発環境の再現性を保証するため。

#### requirements.txt（Python の場合）/ package.json（Node.js の場合）
- 技術スタックで指定されたフレームワーク・ライブラリをバージョン固定で記載
- dev用の依存（テストフレームワーク等）は requirements-dev.txt / devDependencies に分離

#### Dockerfile
```dockerfile
FROM python:3.13-slim  # 言語に応じて変更
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]  # フレームワークに応じて変更
```

#### docker-compose.yaml
```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - .:/app
    # DB等の外部サービスがあればここに追加
```

#### .dockerignore
```
__pycache__/
*.pyc
.env
.orchestrator/
docs/
```

### 4. パイプライン実行

#### Phase 0: 要件定義（対話型）
1. `requirements` Skillで要件を整理 → `docs/requirements.md` + `docs/backlog.md`
2. ユーザーが「承認」するまで次に進まない
3. 未決事項がある場合、設計に進めるものと止めるべきものを区別して報告

#### Phase 1〜3: 設計→実装→レビュー
バックログの優先度順に、1機能ずつ以下を実行:

1. `design` Skillで設計書を生成 → `docs/design/F-XXX.md`
2. Gate 1: `consistency-check` Skillで設計レビュー
   - pass → 次へ
   - fail → `design` Skillに差し戻し（最大3回）
3. `implement` Skillでコード生成 → `src/`
4. `test-design` Skillでテスト仕様書生成 → `docs/test_spec/F-XXX.md`
5. 実装コード + テスト仕様書 → テストコード生成 → `tests/`
6. Gate 2: `consistency-check` Skillで整合性チェック
   - pass → 次へ
   - fail → 該当Skillに差し戻し（最大3回）
7. `review-guide` Skillでレビュー対象マップ生成

各ステップ完了時にproject_status.yamlを更新する。

## セッション再開

1. `.orchestrator/project_status.yaml` を読む
2. current.feature_id と current.phase を確認
3. 未解決のイシューがあれば報告
4. 前回の続きから実行再開
