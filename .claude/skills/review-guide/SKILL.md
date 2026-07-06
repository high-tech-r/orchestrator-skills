# Skill: review-guide（テスト手順書 + レビュー対象マップ生成）

## いつ使うか
- Gate 2を通過した後、人間レビューの前に実行

## 重要な前提
**このドキュメントの読者は、対象システムの前提知識がゼロの人である。**
開発者でなくても、手順書に書かれた通りに上から順に実施すれば、レビューとテストが完了できる粒度で書くこと。
「わかるだろう」「常識的に」という前提を一切置かない。

## 入力
- `docs/design/F-XXX.md`（設計書 + 実装マッピング）
- Tier情報（バックログから）
- `.claude/skills/review-guide/review_tier_definition.yaml`（Tier判定定義）
- 生成されたソースコードのファイル一覧
- `docker-compose.yaml`（環境構築手順に必要）
- **`.orchestrator/stack-profile.md`（アクティブなスタックプロファイル）** ←
  起動・動作確認・テスト実行・テストダブルの**具体コマンド**はここに従う。
  本SKILL内の手順例（FastAPI/Swagger）はあくまで例。プロファイルが Laravel なら
  `php artisan serve` / `php artisan test` / Mailpit / `Mail::assertSent` 等に読み替える。

## Tier判定ロジック

バックログで手動指定されたTierがある場合はそれを使う。
指定がない場合は `review_tier_definition.yaml` を読み込み、以下の手順で自動判定する。

1. 対象機能の実装コードとAPI仕様から、各TierのkeywordsとRisk_signalsを照合する
2. 複数Tierに該当する場合、**最も高いTierを採用する**
3. risk_factorsの6軸（金銭的損失/個人情報/法的責任/可逆性/影響ユーザー数/複雑度）で追加判定
   - high が 4個以上 → Tier S
   - high が 2-3個 → Tier A
   - high が 1個 → Tier B
   - high が 0個 → Tier C or D（複雑度で判断）
4. 判定に迷った場合は1つ上のTierを採用する
5. 判定結果とその根拠をテスト手順書の冒頭に明記する

### Tier別の人間承認要否
- **Tier S, A**: AIレビュー後に人間が最終承認する（requires_human_approval: true）
- **Tier B, C, D**: AIレビューのみで承認可（ai_autonomous: true）

## Gate 3（マージ前 /code-review）の effort 判定

Tierを判定したら、続けて **Gate 3 の推奨 effort** を算出し、手順書に明記する。
判定と実行を1本につなぐため、review-guide の出力が「そのまま /code-review の実行指示」になる。

1. 対象Tierの `code_review.effort` を基準値とする（S=max / A=high / B=medium / C=low_or_skip / D=skip）
2. **変更差分（diff）を読み**、`code_review_risk_signals` に照合する
   - catch/例外ハンドリングの変更、成功/失敗判定ロジック、サービス間契約（URL・レスポンス形状）、
     認証・認可・所有権スコープ、成功メッセージ経路、不可逆な外向き処理（通知・課金・削除）
   - **1つでも該当したら effort を1段引き上げる**（`code_review_effort_ladder`: low→medium→high→max で頭打ち）
   - 該当した risk_signal を手順書に列挙し、引き上げの根拠を残す
3. `skip_signals`「のみ」の差分（docs のみ / テストのみ / コメント・整形のみ）は **Gate 3 をスキップ**（effort: skip）
4. 提案の判定（Gate 3 は「提案」であって強制ではない。実行するかは常にユーザーが決める）:
   - **Tier S / A**: `propose_by_default: true` → フレームワークがマージ前に `/code-review` の実行を**提案**する（強く推奨）
   - **Tier B / C / D**: `propose_by_default: false` → 既定では提案しない。ただし risk_signals 該当で
     effort が上がった場合は提案する
5. 最終 effort が `skip` の場合を除き、手順書 Part 5 に「提案する /code-review コマンド」を明記し、
   ユーザーに実行するかを尋ねる形にする

> effort 語彙は `/code-review` の実効値（low / medium / high / max）に合わせる。
> `ultra` はクラウド多エージェント・課金・ユーザー起動専用のため、この自動 Gate では扱わない
> （最上位でも max 止まり。必要なら人間が別途 `/code-review ultra` を起動する）。

## 出力ファイル
`docs/review_map/F-XXX.md`

```markdown
# テスト手順書 & レビュー対象マップ: F-XXX（機能名）

## 基本情報
- Tier: B
- Gate 3 推奨 /code-review effort: medium（基準 medium。risk_signals 非該当）
- 推定所要時間: XX分
- 前提条件: Docker Desktop がインストールされていること
- 作成日: YYYY-MM-DD

---

## Part 1: 環境構築手順

### Step 1: ソースコードを取得する
1. ターミナル（コマンドプロンプト）を開く
2. 以下のコマンドを入力してEnterを押す：
   ```bash
   cd プロジェクトのパス
   ```
3. 以下のコマンドでDockerコンテナを起動する：
   ```bash
   docker compose up --build -d
   ```
4. 以下のメッセージが表示されれば成功：
   ```
   ✔ Container xxx  Started
   ```
5. エラーが出た場合 → 「トラブルシューティング」セクションを参照

### Step 2: 動作確認
1. アプリのヘルスチェック/トップURL（フレームワークに応じて。例: `http://localhost:8000/`）を確認する：
   ```bash
   curl -i http://localhost:8000/
   ```
   ブラウザで開いてもよい。APIドキュメント機能（Swagger UI / OpenAPI 等）があるFWなら
   そのURL（例: FastAPI なら `/docs`）を開くと以降のテストが楽になる。
2. ステータス 200 系が返る／画面が表示されれば環境構築完了
3. 表示されない場合 → 30秒待って再実行。それでもダメなら「トラブルシューティング」参照

> 以下のテスト手順は Swagger UI を持つフレームワーク（例: FastAPI）を例に書いている。
> **実際の起動・確認・テストのコマンドは `.orchestrator/stack-profile.md` に従うこと。**
> Swagger UI が無いスタック（例: Laravel）は、各操作を `curl` や `php artisan` 等に読み替える。

---

## Part 2: 機能テスト手順

### テスト 2-1: （テストケースIDに対応する名前）
**テスト目的:** （何を確認するのか。1文で）
**期待結果:** （成功した場合どうなるか。1文で）

#### 操作手順:
1. ブラウザで `http://localhost:8000/docs` を開く
2. `POST /api/xxx` をクリックする
3. 「Try it out」ボタンをクリックする
4. Request body欄に以下をコピー&ペーストする：
   ```json
   {
     "title": "テストタスク",
     "description": "テスト用の説明文"
   }
   ```
5. 「Execute」ボタンをクリックする
6. 以下を確認する：
   - [ ] Response code が `201` と表示されている
   - [ ] Response body に `"id"` が含まれている
   - [ ] Response body に `"title": "テストタスク"` が含まれている

**結果:** □ PASS  □ FAIL（FAIL時の画面をスクリーンショットで保存）

### テスト 2-2: （エラーケース）
**テスト目的:** タイトルが空の場合にエラーが返ることを確認する
**期待結果:** 422エラーが返る

#### 操作手順:
1. ブラウザで `http://localhost:8000/docs` を開く
2. `POST /api/xxx` をクリックする
3. 「Try it out」ボタンをクリックする
4. Request body欄に以下をコピー&ペーストする：
   ```json
   {
     "title": "",
     "description": "タイトルなし"
   }
   ```
5. 「Execute」ボタンをクリックする
6. 以下を確認する：
   - [ ] Response code が `422` と表示されている
   - [ ] エラーメッセージが表示されている

**結果:** □ PASS  □ FAIL

（テスト仕様書の全テストケースについて、同様の粒度で手順を記載する）

---

## Part 3: コードレビュー手順

### レビュー対象ファイル一覧
| # | ファイルパス | 確認観点 | Tier判定 |
|---|------------|---------|---------|
| 1 | src/api/xxx.py | API処理ロジック | B: 差分レビュー（意図確認） |
| 2 | src/models/xxx.py | モデル定義 | B: 設計書との一致確認 |
| 3 | migrations/xxx.py | DB定義 | B: カラム・制約の確認 |

### レビュー 3-1: src/api/xxx.py
**確認手順:**
1. 以下のコマンドでファイルを開く：
   ```bash
   cat src/api/xxx.py
   ```
   または任意のエディタ（VSCode等）で開く
2. 以下のチェック項目を上から順に確認する：

**チェック項目:**
- [ ] バリデーション: タイトルが空文字の場合にエラーを返す処理があるか
  - 確認箇所: `def create_task` 関数内
  - 期待: タイトルの空チェック or Pydanticバリデーションが設定されている
- [ ] エラーハンドリング: DB接続エラー時に500を返す処理があるか
  - 確認箇所: DB操作を行っている箇所
  - 期待: try-except でDBエラーをキャッチしている
- [ ] 設計書との用語一致: 変数名が設計書（docs/design/F-XXX.md）と同じか
  - 設計書を横に開いて見比べる
  - 特に確認: テーブル名、カラム名、APIパラメータ名

### レビュー 3-2: 依存定義ファイル
**確認手順:**
1. 依存定義ファイルを開く（言語別: `requirements.txt` / `package.json` / `go.mod` 等）
2. `src/` 内のコードで import / require している外部パッケージを確認する
   （言語別の例）：
   ```bash
   # Python
   grep -rE "^import |^from " src/
   # Node.js
   grep -rE "require\(|^import " src/
   ```
3. 以下を確認する：
- [ ] import/require されている外部パッケージが全て依存定義ファイルに記載されている
- [ ] バージョンが固定されている（範囲指定 or lockfile）

---

## Part 4: 自動テスト実行手順

### Step 1: テストを実行する
1. ターミナルで、プロジェクトのテストコマンドをコンテナ内で実行：
   ```bash
   # 言語別の例（プロジェクトに合わせて差し替え）
   docker compose exec app pytest tests/ -v      # Python
   # docker compose exec app npm test             # Node.js
   # docker compose exec app go test ./...        # Go
   ```
2. 出力結果を確認する：
   - [ ] 全てのテストに `PASSED` と表示されている
   - [ ] `FAILED` が1つもない
   - [ ] テスト件数がテスト仕様書（docs/test_spec/F-XXX.md）のケース数と一致

### Step 2: テスト失敗時
- FAILEDのテスト名を記録する
- エラーメッセージ全文をコピーして保存する

---

## Part 5: Gate 3 — マージ前 /code-review（敵対的差分レビュー）※提案

> 設計⇔コード⇔テストの縦整合（Gate 2）とは別に、**変更差分そのものの正しさ**を
> 敵対的に見る層。偽成功・無音握り潰し・サービス間契約の不整合など、Gate 2 では
> 検出できない潜在バグを狙う。
>
> **これは強制ゲートではない。** フレームワークが「このタイミングで /code-review を
> かけますか？」と**提案**し、実行するかはユーザーが決める（CI非連携・非ブロッキング）。

### 判定結果
- 基準 effort（Tier B）: `medium`
- 検出した risk_signals:
  - （例）「成功/失敗ステータスの判定ロジック」に該当 → effort を1段引き上げ
- **最終 effort: `high`**（risk_signals 該当により medium → high）
- skip 判定: 非該当（docs/テスト/整形のみの差分ではない）

### 提案（実行するかはユーザーが決める）
- Tier S / A → フレームワークがマージ前に実行を**提案**（強く推奨）
- Tier B 以下 → 既定では提案しないが、risk_signals 該当で effort が上がった場合は提案
- 最終 effort が `skip` の場合、この Part は「スキップ（理由: 〜）」と記載し提案しない

「以下を実行してマージ前レビューをかけますか？」とユーザーに尋ねる：
```
/code-review high
```

### 実行した場合の記録
1. 検出された指摘を1件ずつ確認する
2. 指摘への対応を記録する：
   - [ ] 各指摘について「修正する / 誤検出として却下（理由付き） / TDとして起票」を判断した
   - [ ] 誠実性ホットスポット（偽成功・無音 catch・認証握り潰し）の指摘は必ず修正した
3. マージ可否は指摘を踏まえて**人間が最終判断**する（非ブロッキング）

**Gate 3 判定:** □ 未実施（提案のみ）  □ 指摘なし／対応済み  □ 要修正（差し戻し）  □ スキップ（理由: ）

---

## Part 6: 最終チェック

- [ ] Part 2 の全テストが PASS
- [ ] Part 3 の全チェック項目が OK
- [ ] Part 4 の自動テストが全て PASSED
- [ ] Part 5（Gate 3 / code-review）: 提案を確認済み。実行した場合は指摘が対応済み（未実施・スキップも可、理由が明確なこと）
- [ ] 設計書（docs/design/F-XXX.md）の受入条件が全て満たされている

### 総合判定
□ 承認（全項目PASS）
□ 軽微な修正が必要（修正内容: ）
□ 設計レベルの問題あり（問題内容: ）

---

## トラブルシューティング

### Docker起動エラー
- `port is already in use` → 既にポート8000を使用しているプロセスがある。`docker compose down` してから再実行
- `build failed` → `docker compose build --no-cache` で再ビルド

### テスト実行エラー
- 依存関係エラー（`ModuleNotFoundError` / `Cannot find module` 等）→ 依存定義ファイルにパッケージが足りない可能性。開発者に報告
- `Connection refused` → Dockerコンテナが起動していない。`docker compose up -d` を実行
```

## 記載の原則

1. **全ての操作にコマンドまたはURLを明記する** — 「APIを叩く」ではなく「`curl -X POST http://localhost:8000/api/xxx -d '{...}'` を実行する」（Swagger UI があれば画面操作でもよい）
2. **コピー&ペーストで実行できるようにする** — テストデータはJSON形式で丸ごと記載。「適当なデータを入れてください」は禁止
3. **確認項目はチェックボックス形式** — [ ] で列挙し、1つずつ確認できるようにする
4. **期待結果を先に書く** — 操作手順の前に「何が起きれば成功か」を明示する
5. **FAILの場合の対応を書く** — スクリーンショット保存、エラー内容の記録方法を指示する
6. **トラブルシューティングを必ず含める** — よくあるエラーと対処法を末尾に記載する

## スキップポリシー（review_tier_definition.yaml と連動）

各Tierのレビュー方針・テスト要件は `review_tier_definition.yaml` に定義されている。
テスト手順書生成時は該当Tierの `review_policy` と `test_policy` を参照する。

| Tier | レビュー方針 | テスト要件 | スキップ可能な範囲 |
|------|------------|-----------|------------------|
| S | 全行レビュー（line_by_line） | ユニット+結合+手動テスト必須、カバレッジ90% | なし。import文・定型コード含め全行 |
| A | ビジネスロジック重点レビュー | ユニット+結合テスト必須、カバレッジ80% | 定型部分は流し読み。import文はスキップ不可 |
| B | 差分レビュー | ユニットテスト推奨、カバレッジ60% | 意図通りかの差分確認のみ |
| C | 動作確認 | 画面確認のみ | コードはざっと目視。動けばOK |
| D | ビルド確認のみ | ビルド通過+lintエラーなし | コードレビュー不要 |

### オーバーライド条件（review_tier_definition.yaml で定義）
- 本番環境へのデプロイを含む → 最低Tier B
- 本番データベースへの直接操作 → Tier S強制適用
- 新規外部サービスとの初回連携 → 最低Tier A
