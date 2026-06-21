# レベル2セキュリティ構成（無料ツールのみ）

このリポジトリに組み込んだ、AI駆動開発向けレベル2セキュリティの実体ファイルと、
有効化に必要な手動ステップをまとめる。**すべて無料ツールで構成**している
（Snyk有料 / FOSSA有料 / Portkey / Burp Pro / GitGuardian は不採用）。

## 何が入っているか

| # | カテゴリ | 採用ツール（無料） | 実体ファイル | ブロック |
|---|---|---|---|---|
| 1 | シークレット | Gitleaks（pre-commit）＋ TruffleHog（CI） | `.pre-commit-config.yaml`, `.gitleaks.toml`, `security.yml` | ✅ |
| 2 | SCA（脆弱性） | Dependabot ＋ Trivy ＋ OSV-Scanner（多言語）／ pip-audit（Python任意） | `templates/dependabot.yml`(→`.github/`にコピー), `security.yml` | ✅ |
| 3 | SCA（slopsquatting） | Socket GitHub App ＋ OSV-Scanner ＋ lockfile運用 | `security.yml`（OSV）＋ 手動 | 一部 |
| 4 | SAST（汎用） | Semgrep OSS CLI | `security.yml` | ✅ |
| 5 | SAST（AI特化） | Semgrep AI Security / Shadow AI（無料パック） | `security.yml` | ✅ |
| 6 | ライセンス | Trivy（license スキャナ） | `security.yml` | ✅ |
| 7 | Content Exclusion | Claude Code `permissions.deny` | `.claude/settings.json`, `.gitignore` | ✅ |
| 8 | DAST | OWASP ZAP Baseline | `dast-zap.yml` | 警告 |
| 9 | LLMゲートウェイ | （レベル3のため対象外） | — | — |

ブロック列「✅」= 検出時にCIが失敗し、PRのマージを自動拒否する（品質ゲート）。
これがレベル1（人間レビュー頼み）との本質的な違い。

## 証跡（顧客説明用）

スキャン結果は次の場所で確認・取得できる。一人SIerが顧客に「どう担保し、どうテストしたか」を
説明するための材料になる。

| 種類 | 場所 | private無料か |
|---|---|---|
| 各スキャンの合否・ログ | Actions → `Security (Level 2)` の各run | ✅ |
| スキャン指摘の一覧（SARIF） | Security → Code scanning alerts | ⚠️ private は GHAS(有料) |
| **ダウンロード可能な証跡** | 各runの **Artifacts**（`sca-evidence` / `sast-semgrep-sarif`） | ✅ private でも無料 |
| 依存の脆弱性 | Security → Dependabot alerts | ✅ |

`sca-evidence` 成果物には **SBOM（`sbom.cdx.json` / CycloneDX）**・**ライセンスレポート**・
**Trivy SARIF** が含まれる。private リポジトリで Code scanning UI が使えなくても、
この Artifacts が証跡として残る。

### CI実走時の注意（実プロジェクト適用で判明）
- **SARIF アップロードは best-effort**: private + GHAS無効リポでは Code Scanning へのアップロードが
  失敗する。各 `upload-sarif` ステップは `continue-on-error: true` とし、**証跡は artifact 側で確保**
  しているのでジョブは赤にならない。
- **言語別SCAは検出ゲート式**: `pip-audit`(Python) / `composer-audit`(PHP) は対象ファイル
  （`requirements*.txt` / `composer.lock`）が無ければステップごとスキップ。
  ※ ジョブレベルの `if:` で `hashFiles()` は使えない（ワークフロー全体が検証エラーになる）。
  必ず「検出ステップ＋ステップレベル `if`」で分岐する。
- **ワークフローの検証**: `.github/workflows/actionlint.yml` と pre-commit の actionlint で、
  「GitHub上でしか顕在化しない」不具合（上記 `hashFiles()` 誤用・無効なアクション参照 等）を
  事前に弾く。テンプレ変更時は `actionlint` を必ず通すこと。

顧客に渡す体裁にまとめるには:
- `SECURITY.md` … 顧客向けの「どう担保・テストしているか」の説明書（常設）
- `security-report` スキル … 最新スキャン結果を `docs/delivery/security_report_YYYY-MM-DD.md` に集約
  （納品ドキュメントは `delivery` スキルで `docs/delivery/` に一括パッケージ化）

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

- **`dependabot.yml`**: テンプレートは `templates/dependabot.yml`。使うには
  **自分のリポジトリの `.github/dependabot.yml` にコピー**する（テンプレートリポジトリ自体で
  Dependabot が動かないよう `templates/` に置いている）。既定で有効なのは `github-actions` と
  `docker` のみで、`tech_stack.language` に応じた `package-ecosystem`（`pip` / `npm` / `gomod` /
  `bundler` 等）を初期化時にオーケストレーターが有効化する（手動なら該当ブロックのコメントを外す）。
  `labels:` のラベルは事前に Issues → Labels で作成するか、不要なら削除する。
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
