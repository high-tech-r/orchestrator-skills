# Skill: orchestrate（パイプライン制御）

## いつ使うか
- 新しいプロジェクトを開始するとき
- セッションを再開するとき（project_status.yamlを読んで続きから）
- 「オーケストレーション開始」「パイプライン実行」等の指示を受けたとき

## プロジェクト初期化

ユーザーから要件を受け取ったら、以下を作成する。

**ファイル配置の原則（厳守）**: 状態管理は `.orchestrator/`、成果物は `docs/` に分ける。
- 状態（再開地点）: `.orchestrator/project_status.yaml`
- 成果物: `docs/backlog.md` / `docs/requirements.md` / `docs/design/` 等

### 1. `docs/backlog.md` を作成

```markdown
# プロダクトバックログ

## サマリー
- 全項目数: N
- 完了: 0 / 進行中: 0 / 未着手: N

## バックログ

| ID | 機能名 | 優先度 | ステータス | Tier | 概要 |
|----|--------|--------|-----------|------|------|
| F-001 | xxx | 高 | ⬜ 未着手 | B | xxx |
```

### 2. `.orchestrator/project_status.yaml` を作成

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

**Docker（Dockerfile + docker-compose.yaml）は言語を問わず必須**。依存定義ファイルと
.dockerignore の中身は言語によって変わる。以下のコード例はいずれも **Python/FastAPI の一例**で、
`tech_stack.language` に応じて base image・依存ファイル・起動コマンドを差し替える。

#### 依存定義ファイル
- 技術スタックで指定されたフレームワーク・ライブラリをバージョン固定で記載
- 本番用と dev用（テストフレームワーク等）を分離する
- 言語別の例: Python → `requirements.txt` / `requirements-dev.txt`、
  Node.js → `package.json`（dependencies / devDependencies）、Go → `go.mod`

#### Dockerfile（以下は Python 例。言語に応じて変更）
```dockerfile
FROM python:3.13-slim          # 言語のベースイメージに変更（node:22-slim / golang:1.23 等）
WORKDIR /app
COPY requirements.txt .         # 言語の依存定義ファイルに変更
RUN pip install --no-cache-dir -r requirements.txt   # 言語のインストールコマンドに変更
COPY . .
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]  # 言語/FWの起動コマンドに変更
```

#### docker-compose.yaml（言語非依存）
```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"   # アプリのリッスンポートに合わせる
    volumes:
      - .:/app
    # DB等の外部サービスがあればここに追加
```

#### .dockerignore（以下は Python 例。言語に応じて変更）
```
__pycache__/          # 言語の生成物に変更（node_modules/ など）
*.pyc
.env
.orchestrator/
docs/
```

### 4. セキュリティ設定を技術スタックに合わせる（必須）

同梱のセキュリティCIは言語非依存だが、**依存パッケージのスキャンだけは言語ごとに
有効化が要る**。初期化時に `tech_stack.language` を見て、以下を自動で設定する。
利用者にYAMLを手で触らせない（このフレームワークの方針）。

#### 4-1. `.github/dependabot.yml` の該当エコシステムを有効化

`tech_stack.language` を下表で引き、対応する `package-ecosystem` ブロックの
コメントを外す（`github-actions` と `docker` は既定で有効なのでそのまま）。

| language | package-ecosystem | 依存ファイルの目安 |
|---|---|---|
| Python | `pip` | requirements*.txt / pyproject.toml / Pipfile |
| Node.js / TypeScript | `npm` | package.json |
| Go | `gomod` | go.mod |
| Rust | `cargo` | Cargo.toml |
| Ruby | `bundler` | Gemfile |
| Java (Maven) | `maven` | pom.xml |
| Java (Gradle) | `gradle` | build.gradle |
| PHP | `composer` | composer.json |
| C# / .NET | `nuget` | *.csproj |

複数言語のプロジェクトなら該当する全ブロックを有効化する。

#### 4-2. Semgrep の言語ルール（任意）

`.github/workflows/security.yml` の Semgrep は `p/default` が言語を自動判定するため
基本は変更不要。特定言語を厳しめに見たい場合のみ `--config p/python` `p/javascript`
`p/golang` 等を追記する。

#### 4-3. DAST のポート（必要時）

`.github/workflows/dast-zap.yml` は既定で `localhost:8000` を対象にする。
生成する Dockerfile / docker-compose が別ポートを使う場合、`app_port` の既定値、
または起動設定を合わせる。

#### 4-4. 設定内容をユーザーに提示

変更した `dependabot.yml` 等の差分を要約してユーザーに伝える
（「Python向けに pip エコシステムを有効化しました」等）。

### 5. パイプライン実行

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
