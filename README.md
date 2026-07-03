# AI Orchestrator — 一人SIerフレームワーク

**Claude Code だけで「設計 → 実装 → テスト → チェック」の開発パイプラインを回す、AIオーケストレーションのフレームワークです。**

要件を自然言語で渡すと、Claude Code が `CLAUDE.md` と複数の Skill を順番に実行し、設計書・ソースコード・テスト・整合性レポートまでを一貫して生成します。「一人で受託開発の全工程を回す（一人SIer）」をAIで実現するための土台です。

### 特徴

- **API従量課金なし** — Claude Code（Pro/Maxプラン）の範囲内で完結
- **品質ゲート内蔵** — Gate 1（設計レビュー）/ Gate 2（設計⇔コード⇔テスト突合）で自動差し戻し
- **セッション再開** — 中断しても `project_status.yaml` から続きを再開
- **レベル2セキュリティ同梱（無料ツールのみ）** — シークレット/SCA/SAST/ライセンス/DASTをCIの品質ゲートとして接続（[詳細](#セキュリティレベル2--無料ツールのみ)）

### 誰のためか

- AIオーケストレーションで一人SIer型の開発フローを試したい人
- 自分のプロジェクトに「設計→実装→テスト」の型と、AI生成コード向けのセキュリティを導入したい人

MITライセンスで公開しています。フォーク・改変・再配布は自由です（[LICENSE](LICENSE)）。

## クイックスタート（一本道）

clone から最初の成果物が出るまでを、この順番どおりに進めれば動きます。

### 1. clone してフックを入れる

```bash
git clone https://github.com/high-tech-r/orchestrator-skills.git
cd orchestrator-skills
pip install pre-commit && pre-commit install   # コミット前のシークレット検出
```

### 2. リポジトリ設定の手動ステップ（フォークして使う場合・すべて無料）

GitHubの画面でのみ有効化できる設定。**最初に1回だけ**実施する（自分のリポジトリとして運用する場合）。

1. Settings → Code security → **Dependabot alerts / security updates** を Enable
2. Settings → Code security → **Secret scanning（push protection）** を Enable
3. https://socket.dev から **Socket GitHub App** をインストール（slopsquatting対策・OSS無料）
4. Settings → Branches → main の保護で **`Security (Level 2)` を Required** に設定
5. https://semgrep.dev/explore で **AI Security / Shadow AI パック**の最新名を確認し、`.github/workflows/security.yml` のコメント箇所を有効化

> まず動かして試すだけなら 2 はスキップ可。後から有効化しても問題ありません。
> 各ステップの背景は [`docs/security/LEVEL2_SECURITY.md`](docs/security/LEVEL2_SECURITY.md) を参照。

### 3. Claude Code を起動して最初の要件を投入する

```bash
claude
```

起動したら、プロンプトに要件を貼るだけ:

```
以下の要件でオーケストレーションを開始してください。

プロジェクト名: シンプルTODOアプリ
技術スタック: Python / FastAPI / SQLite
機能:
- F-001: タスク追加（タイトル必須、説明任意、作成日時自動記録）
- F-002: タスク一覧取得（作成日時降順、完了/未完了フィルタ）
```

Claude Code が `CLAUDE.md` を読み、要件定義 → 設計 →[Gate 1]→ 実装＋テスト →[Gate 2]→ レビューガイド の順にパイプラインを回し、`docs/` `src/` `tests/` に成果物を生成します。中断しても次回 `前回の続きからお願いします` で再開できます。

> 上の技術スタックは一例です。**言語・フレームワークは任意**（Node.js / Go / Java など）。同梱のセキュリティCIも言語非依存で、使う言語に合わせて一部だけ設定を有効化します（[詳細](docs/security/LEVEL2_SECURITY.md)）。

## 既存プロジェクトに組み込む

新規プロジェクトだけでなく、**すでにあるリポジトリにも後付けできる**。必要なファイルを目的別にコピーする。

### A. オーケストレーション本体（必須）

これが無いとパイプラインは動かない。フォルダごとコピーする。

```
CLAUDE.md            # ★既存に CLAUDE.md があるなら「上書きせずマージ」
.claude/skills/      # 全スキル + 共通ルール（_shared）+ Tier定義。フォルダごと
```

### B. レベル2セキュリティ一式（任意・推奨）

セキュリティも入れるなら追加でコピーする。

```
.pre-commit-config.yaml  .gitleaks.toml          # シークレット（コミット前）
.github/workflows/security.yml  dast-zap.yml     # CI品質ゲート / DAST
.github/PULL_REQUEST_TEMPLATE.md                 # AI利用チェック
.zap/rules.tsv                                   # ZAP抑制ルール
.claude/settings.json                            # 機密ファイルの読み取り禁止
docs/security/LEVEL2_SECURITY.md                 # 手順書
```

> **Dependabot を使う場合**: `templates/dependabot.yml` を **自分のリポジトリの
> `.github/dependabot.yml` にコピー**してください（テンプレートを `templates/` に
> 置いているのは、このリポジトリ自体に Dependabot が動かないようにするためです）。
> `labels:` で指定するラベルは事前に Issues → Labels で作成するか、不要なら削除します。

### 上書きせず「マージ」するファイル

既存プロジェクトに同名ファイルがある場合、潰さず中身を合流させる。

| ファイル | 対応 |
|---|---|
| `CLAUDE.md` | 既存の規約に本フレームワークのセクションを追記 |
| `.gitignore` | 既存ルールにシークレット/言語別の項目を追加 |
| `.claude/settings.json` | 既存の `permissions` があれば `deny` 配列を結合 |

### コピー不要

`README.md` / `LICENSE` / `example_requirements.yaml` はこのリポジトリ固有の説明物なので不要。

### 組み込み後

`claude` を起動して `前回の続きから` ではなく新しい要件を投入すれば、既存コードを文脈に含めてパイプラインが回る。**言語別のセキュリティ設定（dependabot 等）は `orchestrate` スキルが初期化時に自動で有効化する**ため、利用者がYAMLを手で触る必要はない（手動でやる場合は [`docs/security/LEVEL2_SECURITY.md`](docs/security/LEVEL2_SECURITY.md) 参照）。

> ⚠️ **既存PJはセキュリティゲートを即 block にしない**。過去の負債（古いCVE・既存指摘）で
> 無関係なPRまで赤になる。**`SECURITY_GATE_MODE=report`（助言モード）で導入 → 既存指摘を棚卸し
> → `block` → ブランチ保護で Required** の順で段階導入する（[手順](docs/security/LEVEL2_SECURITY.md#既存プロジェクトへの段階導入重要)）。
> 新規PJは最初から block（既定）でよい。秘密情報スキャンは常に block。

---

以下は各トピックの詳細です。

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
│       ├── _shared/
│       │   └── test-quality-rules.md  # テスト品質ルールの共通真実源
│       ├── requirements/SKILL.md    # 要件定義（対話型）
│       ├── orchestrate/SKILL.md     # パイプライン制御・初期化
│       ├── design/SKILL.md          # 設計書生成
│       ├── implement/SKILL.md       # ソースコード生成
│       ├── test-design/SKILL.md     # テスト仕様書生成
│       ├── consistency-check/SKILL.md  # Gate 1 & Gate 2
│       ├── review-guide/
│       │   ├── SKILL.md             # レビュー手順書生成
│       │   └── review_tier_definition.yaml  # Tier自動判定の定義
│       ├── audit/
│       │   ├── SKILL.md             # 敵対的コードベース監査（オンデマンド）
│       │   └── lens-rubric.md       # 観点ラブリック L1〜L9（サブエージェントに全文貼付）
│       ├── security-report/SKILL.md # 顧客向けセキュリティ証跡（オンデマンド）
│       ├── quality-report/SKILL.md  # 顧客向け品質レポート（オンデマンド）
│       └── delivery/SKILL.md        # 納品ドキュメント一式の集約（オンデマンド）
├── .github/
│   ├── workflows/
│   │   ├── security.yml             # レベル2セキュリティCI（品質ゲート）
│   │   ├── dast-zap.yml             # DAST（OWASP ZAP・手動実行）
│   │   └── actionlint.yml           # ワークフロー定義の静的検証（再発防止）
│   └── PULL_REQUEST_TEMPLATE.md     # AI利用チェック付きPRテンプレート
├── templates/
│   ├── dependabot.yml               # 依存更新の設定テンプレ（.github/ にコピーして使う）
│   └── stack-profiles/              # スタック別の起動/テスト/fake手順
│       ├── _template.md             # プロファイルの契約（観点）
│       ├── laravel.md / fastapi.md  # リファレンス例（要確認・権威ではない）
│       └── README.md
├── .pre-commit-config.yaml          # Gitleaks等のコミット前フック
├── .gitleaks.toml                   # シークレットスキャンのルール
├── .zap/rules.tsv                   # ZAP誤検知の抑制ルール
├── .gitignore
├── docs/
│   ├── security/LEVEL2_SECURITY.md  # セキュリティ構成の解説・手順
│   └── delivery/README.md           # 納品ドキュメントフォルダの規約
├── SECURITY.md                      # 顧客向けセキュリティ説明書
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
│   ├── review_map/F-001.md    # レビュー対象マップ
│   └── delivery/              # 顧客向け納品ドキュメント（納品時に生成）
├── src/                       # ソースコード
└── tests/                     # テストコード
```

## スタックプロファイル（言語/FW非依存の仕組み）

「設計→実装→テスト→レビュー」の**観点はフレームワークが所有**し、**具体（起動・テスト・
外部作用の fake 等のコマンド/イディオム）はスタックプロファイルに分離**する。これにより
FastAPI 前提を脱し、`design` は HTTP 以外（ジョブ/イベント/CLI/スケジュール）も扱える。

- フレームワークが持つのは**契約**: `templates/stack-profiles/_template.md`
  （起動 / テスト / 種別ごとの確認 / テストダブル / 依存 / 落とし穴）
- 同梱の `laravel.md` / `fastapi.md` は**リファレンス例**（権威ではない・バージョンで腐る前提で「要確認」明記）
- 初期化時、`orchestrate` が適用先の**プロジェクト側 `.orchestrator/stack-profile.md`** を
  用意（一致する例があれば下敷きに、無ければ契約に沿って生成）。以後 `design` /
  `test-design` / `implement` / `review-guide` がこれを参照する

> 同梱例が古くても害は小さい（権威ではないため）。適用先の Claude Code が現行バージョンとの
> 食い違いに気づいたら、プロジェクト側のプロファイルを更新する ── という前提で設計している。

詳細は [`templates/stack-profiles/README.md`](templates/stack-profiles/README.md) を参照。

## セキュリティ（レベル2 / 無料ツールのみ）

AI駆動開発向けのレベル2セキュリティを無料ツールだけで組み込み済み。**言語非依存**で動作する。
詳細とセットアップ手順は [`docs/security/LEVEL2_SECURITY.md`](docs/security/LEVEL2_SECURITY.md) を参照。

- pre-commit（Gitleaks）でコミット前にシークレットをブロック
- GitHub Actions（`Security (Level 2)`）でPR時に TruffleHog / Semgrep / Trivy / OSV-Scanner を自動実行し、品質ゲートでマージを制御（いずれも言語自動判定。Python向けの pip-audit は任意で自動スキップ）
- Dependabot・Secret scanning・Socket(OSS無料App) はリポジトリ設定で有効化（手動）
- DAST（OWASP ZAP）は手動実行ワークフロー
- `.claude/settings.json` の `permissions.deny` で機密ファイルをAIから遮断
- **顧客説明用の証跡**: CIが SBOM（CycloneDX）・ライセンスレポート・SARIF を成果物として出力（private でも無料で証跡が残る）。顧客向けの説明は [`SECURITY.md`](SECURITY.md)、リリースごとのレポートは `security-report` スキルで生成

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

## 納品ドキュメント（顧客への説明・Gamma対応）

一人SIerが顧客に「何を作り、どう品質・セキュリティを担保したか」を説明するための成果物を、
納品時に `docs/delivery/` へ一括生成できる。パイプライン外の**オンデマンドスキル**として実行する。

```
納品ドキュメントを作成してください
```

`delivery` スキルが以下を生成する（`quality-report` / `security-report` を内包）:

| 成果物 | 内容 |
|---|---|
| `index.md` | 納品物一覧＋担保方法の要約 |
| `design_summary.md` | 顧客向け設計サマリー（提供機能・構成） |
| `quality_report_*.md` | テスト件数・合否・カバレッジ・Gate通過・既知の不具合 |
| `security_report_*.md` | セキュリティ検査内容と証跡（SBOM・ライセンス等） |
| `presentation_*.md` | 顧客説明用スライド（**Gamma取り込み用Markdown**） |

### Gamma でスライド/PPTにする

`presentation_*.md` は [Gamma](https://gamma.app) への取り込みを前提に、`---`（水平線）で
スライドを区切った形式で生成される。

1. Gamma で **Import → Markdown** を選び、`presentation_*.md` を貼り付け／アップロード
2. `---` ごとに自動でスライド分割される
3. テーマを選んで微調整し、**PPT / PDF にエクスポート**して顧客提示

> 数値・合否はレポートと一致させ、不利な事実も省かない（スライドも証跡同様、嘘をつかない）。

## 検証ポイント

1. Claude CodeがSkillを正しく認識して順番に実行するか
2. Gate判定で問題を検出して差し戻しが機能するか
3. project_status.yamlでセッション再開できるか
4. SKILL.mdのサイズがContext Rotを起こさないか
5. 成果物の品質（設計書・コード・テストの整合性）
6. セキュリティCI（`Security (Level 2)`）が生成物に対して品質ゲートとして機能するか

## ライセンス

[MIT License](LICENSE) で公開しています。商用・非商用を問わず、フォーク・改変・再配布は自由です。
