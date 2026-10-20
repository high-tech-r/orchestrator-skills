# Skill: orchestrate（パイプライン制御）

## いつ使うか
- 新しいプロジェクトを開始するとき
- セッションを再開するとき（project_status.yamlを読んで続きから）
- 「オーケストレーション開始」「パイプライン実行」等の指示を受けたとき

## プロジェクト初期化

ユーザーから要件を受け取ったら、以下を作成する。

**ファイル配置の原則（厳守）**: 状態管理は `.orchestrator/`、成果物は `docs/` に分ける。
- 状態（再開地点）: `.orchestrator/project_status.yaml`
- 成果物: `docs/backlog.html` / `docs/requirements.md` / `docs/design/` 等

### 1. `docs/backlog.html` を作成（HTML のみ。Markdown のバックログは作らない）

バックログは **HTML 1ファイル**で管理する。表示（未完了/完了・優先度・Tier・種別の絞り込み、検索、
並べ替え、進捗バー、詳細展開、ダーク/ライト、file:// で開ける自己完結）はフレームワーク所有のテンプレート
`templates/backlog/backlog.html` が担保し、データは HTML 内の JSON に埋め込む。
**HTML を手で書かない・編集しない。必ず `scripts/backlog.py` を通す**（書込み前にスキーマ検証。通らなければ書かない）。

```bash
python3 scripts/backlog.py init --project "案件名"
# 要件定義書（docs/requirements.md §3 機能一覧）の各行を登録。1件ずつでも JSON 一括でもよい
python3 scripts/backlog.py add --id F-001 --name "xxx" --priority 高 --tier B \
  --summary "..." --acceptance "受入条件1" --acceptance "受入条件2"
python3 scripts/backlog.py add --from-json /tmp/items.json     # [{"id":"F-002","name":...}, ...]
python3 scripts/backlog.py validate
```

- 語彙: status = 未着手/進行中/完了/保留/エスカレーション、priority = 高/中/低、tier = S/A/B/C/D/未判定、
  type = feature（F-xxx）/ td（TD-xxx。audit の起票先）。
- 工程が進むたびに `set-status` / `update --phase` で更新し、`project_status.yaml` と**同時に**書き換える。
  設計書等ができたら `update F-001 --link design=design/F-001.md` で紐づける。
- 既存プロジェクトに `docs/backlog.md` があれば `python3 scripts/backlog.py import-md docs/backlog.md --project "案件名"`
  で一度だけ移行し、**旧 Markdown は削除**する（二重帳簿にしない）。
- `scripts/backlog.py` / `templates/backlog/backlog.html` が無いプロジェクトでは、フレームワークから両方をコピーする
  （README「既存プロジェクトに組み込む」A）。テンプレートを更新したら `backlog.py render` で既存バックログに反映する。

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

#### スタックプロファイル（必須）
「どう起動し・どう確認し・どうテストし・どう外部作用をfakeするか」をスタックごとに記した
プロファイルを、**適用先プロジェクトの `.orchestrator/stack-profile.md`** に用意する。
`design` / `test-design` / `implement` / `review-guide` はこれを参照する（FastAPI前提を脱するため）。

手順:
1. `.orchestrator/stack-profile.md` が既にあればそれを使う。
2. 無ければ `tech_stack` に一致する同梱例（`templates/stack-profiles/laravel.md` /
   `fastapi.md`）を下敷きに、`.orchestrator/stack-profile.md` を作る。
3. 一致する例が無ければ `templates/stack-profiles/_template.md` の契約（全見出し）に沿って
   **実スタック用に生成**する。
4. 同梱例は**リファレンス（権威ではない）**。現行バージョンとコマンド/イディオムが食い違うと
   気づいたら、プロジェクト側のプロファイルを正として更新する（メタ情報の最終確認日も更新）。

### 4. セキュリティ設定を技術スタックに合わせる（必須）

同梱のセキュリティCIは言語非依存だが、**依存パッケージのスキャンだけは言語ごとに
有効化が要る**。初期化時に `tech_stack.language` を見て、以下を自動で設定する。
利用者にYAMLを手で触らせない（このフレームワークの方針）。

#### 4-1. `.github/dependabot.yml` の該当エコシステムを有効化

まず `.github/dependabot.yml` が無ければ、テンプレート `templates/dependabot.yml` を
`.github/dependabot.yml` にコピーする（Dependabot はこのパスにある時のみ動作する）。
次に `tech_stack.language` を下表で引き、対応する `package-ecosystem` ブロックの
コメントを外す（`github-actions` と `docker` は既定で有効なのでそのまま）。
`labels:` を使う場合は、対象リポジトリに同名ラベルが存在することを確認する（無ければ作成 or 行を削除）。

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

### 4-5. 作業合意インタビュー（最初の作業前に・CLAUDE.md Rule 8/9）

**「どう一緒に進めるか」を最初に1回まとめて合意する**。Rule 8（git 役割）・Rule 9（権限ポスチャ）・
ブランチ戦略・その他の取り決めを、初期化時に**一度のインタビュー**で決める。すべて共通の型＝
「一度合意し、記録し、その範囲を超えない。指示が無ければ**前回の合意を引き継ぐ**。変えたければ再合意」。

**まず既存の合意を確認**: `.orchestrator/working-agreement.md` があれば読み、その内容を尊重する
（＝引き継ぎ。改めて全部聞き直さない）。無ければ（初回）、以下 ①〜④ を聞いて合意する。
各項目は**推奨（既定）を先に示す**。ユーザーが「おまかせ」なら既定を採用する。

#### ① 確認の粒度（権限ポスチャ）— Rule 9
`.orchestrator/permission_posture.json` に永続化（**機械可読の正**。フックが毎回読む）。既定（推奨）は **`auto`**。
- **auto**（既定・推奨）: Claude Code の **auto mode**（分類器）に任せる。フックは自動承認を足さず、deny フロアと
  観測だけ。auto mode が使えない／別モードのセッションでは conservative 相当で動き、初回にその旨を表示する。
- **conservative**（企業/情報漏洩防止向け）: リポジトリ単位で Manual を強制する。エージェントは `.claude/settings.json` を
  書けない（deny フロア）ので、**ユーザーに `python3 scripts/apply_posture.py --posture conservative .` の実行を依頼**する
  （プロジェクト設定に `defaultMode: "default"` が書かれ、クローンした全員に効く）。
- **balanced** / **permissive**: auto mode が使えない環境向け（可逆のみ／フロア以外すべてをフックが承認）。
- どのポスチャ・どのモードでも **deny フロア（再帰強制削除・force push・特権昇格・`.env`/`.claude` 特権ファイル書込 等）は常時拒否**。
- 選択値で `permission_posture.json` を `{"posture":"<選択>"}` として作成。詳細は `docs/security/PERMISSION_POSTURE.md`。
- **auto mode を既定で使うかどうかは人の設定**（`permissions.defaultMode: "auto"` はプロジェクトの `.claude/settings.json`
  では無効）。インタビューでは現在のセッションの permission mode を伝え、必要なら
  `python3 scripts/apply_posture.py --set-user-default-mode auto .` または `claude --permission-mode auto` を**提案**する。
  エージェント自身が `~/.claude/settings.json` や `.claude/settings.json` を書き換えない。
- auto mode で長時間自走させる利用者には、分類器ルールの導入（`python3 scripts/apply_posture.py --install-auto-mode-rules`、
  opt-in・全プロジェクトに効く）を**選択肢として案内**する（勧めるのは定型作業のブロックが実際に邪魔になってから）。

#### ② git の役割 — Rule 8
どこまで AI が git を操作するか。既定は **(b) PR 作成まで**。
- (a) コミットまで（push は人）／ **(b) ブランチ push ＋ PR 作成まで（既定）**／ (c) マージまで自走。
- main への直 push・マージ・force push は明示合意が無い限りしない（提案に留める）。

#### ③ ブランチ戦略
既定は **機能別**（パイプラインの「1機能ずつ」と一致し、PR も機能単位でレビューしやすい）。
- **機能別（既定）**: バックログ1機能=1ブランチ（`feat/F-XXX-<短い名前>`）。
- **フェーズ/まとめ**: 関連する複数機能を1ブランチにまとめる（小規模・関連機能一括）。
- **単一作業ブランチ**: `work` など1本で回す（超小規模・個人実験）。
- **main 直（非推奨）**: 使い捨て・単独実験のみ。Rule 8 の不可逆操作の注意が効く。

#### ④ その他の取り決め（自由・"chat about this"）
上記で決めきれない作業上の約束を自由に聞く。例: コミットメッセージの言語、レビュー深度の既定、
デプロイ/リリースの運用、通知の希望、触ってほしくない領域 など。無ければ「特になし」でよい。

#### 合意の記録（①以外はここに集約）
`.orchestrator/working-agreement.md` を**人間可読の真実源**として作成/更新する:

```markdown
# 作業合意（Working Agreement）
- 合意日: YYYY-MM-DD
- 権限ポスチャ: auto | conservative | balanced | permissive
  （機械可読の正は .orchestrator/permission_posture.json。ここは人間向けの写し）
- 起動時の permission mode（確認用）: auto | default | ...（auto でなければ ①のとおり人が設定する）
- git の役割: (a) コミットまで | (b) PR作成まで | (c) マージまで自走
- ブランチ戦略: 機能別(feat/F-XXX-…) | フェーズ/まとめ | 単一作業ブランチ | main直(非推奨)
- その他の取り決め:
  - （自由記述。無ければ「特になし」）

## 変更履歴
- YYYY-MM-DD: 初回合意（ポスチャ=… / git=… / ブランチ=…）
```

- 合意（と以後の変更）は `project_status.yaml` の `feedback_history` にも記録する（監査証跡）。
- 二重帳簿にしない: ポスチャの**正は JSON**、working-agreement.md はその写し。食い違ったら JSON を正とする。

> 注: フックの配線変更は settings.json の再読込（多くはセッション再起動）で反映される。ポスチャ値の
> 変更（JSON 書き換え）は次のツール呼び出しから即反映される。

### 5. パイプライン実行

#### Phase 0: 要件定義（対話型）
1. `requirements` Skillで要件を整理 → `docs/requirements.md`、承認後に機能一覧を `scripts/backlog.py add` で `docs/backlog.html` に登録
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
8. **停止判定（auto mode 前提・Tier の `autonomy`）**: `review_tier_definition.yaml` の該当 Tier を見る
   - S: Gate 1 通過直後にも停止し、人が設計を承認してから 3. に進む（`gate1_design_approval`）。review-guide 後も停止
   - A: review-guide 後に停止し、人間レビュー完了（マージ可否）を待つ
   - B/C/D: `set-status ... --phase human_review` にして次の機能へ進んでよい。ただし未レビュー滞留が
     `orchestration.auto_mode_flow.max_pending_human_reviews`（既定 3）に達したら停止して消化を待つ
   - 停止時は「どこまで進んだか・人に見てほしい点・次に再開する地点」を要約して伝える（無音で止まらない）

各ステップ完了時に project_status.yaml と `docs/backlog.html`（`backlog.py set-status/update --phase`）を**同時に**更新する。

## セッション再開

1. `.orchestrator/project_status.yaml` を読む
2. current.feature_id と current.phase を確認
3. `.orchestrator/working-agreement.md` と `permission_posture.json` を読み、**現在の作業合意を毎回明示する**
   （loud・引き継ぎを不可視にしない）。例:「現在の合意 — 権限ポスチャ: auto（このセッションは auto mode）／
   git: PR作成まで／ブランチ: 機能別。変更する場合は指示してください」。どちらのファイルも無ければ既定
   （ポスチャ=auto／git=PR作成まで／ブランチ=機能別）として扱い、初回は 4-5 に沿って合意する。
   ポスチャが auto なのにセッションが auto mode でなければ、その旨と有効化手順（人が行う）を伝える。
3b. `docs/backlog.html` を `python3 scripts/backlog.py list --status 進行中 --status 未着手` で読み、
   人間レビュー待ち（phase=human_review）の件数が上限を超えていないか確認する。
   ユーザーから指示が無ければ、その合意のまま続行する（CLAUDE.md Rule 8/9）。
4. 未解決のイシューがあれば報告
5. 前回の続きから実行再開
