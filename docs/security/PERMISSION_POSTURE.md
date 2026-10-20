# 権限ポスチャ（Permission Posture）

「どこまで AI に自動承認を委ねるか」をユーザーが選べる仕組み。リスクを受容して速度を優先したい人も、
情報漏洩を防ぎたい企業も、同じフレームワークを自分の基準で使えるようにする。CLAUDE.md **Rule 9** の実装。

- **一度合意し、記録し、超えない。指示が無ければ前回の選択を引き継ぐ**（Rule 8＝Git 役割分担と同じ型）。
- **deny フロアは全ポスチャ・全 permission mode で常時有効**。これが auto / permissive を責任もって提供できる前提。

## 前提: Claude Code の auto mode が既定になった

このフレームワークの権限ポスチャは、Claude Code に **auto mode**（バックグラウンドの分類器が
操作ごとに承認/拒否を判断するモード）が無かった時代に、「可逆な操作だけフックで自動承認する」
近似として作られた（balanced / permissive）。現在は Claude Code 自身が auto mode を持ち、
**ターミナル起動の組み込み既定も auto**（v2.1.283 以降）である。したがって本フレームワークは:

- **auto mode を正（authority）とする**。フックは auto mode の分類器と競合しない（allow を出さない）。
- フレームワークが足すのは **deny フロア（分類器が何と言おうと拒否する操作）** と **観測レシート**。
  公式ドキュメントどおり、hook の `deny` と `permissions.deny` は auto mode でも分類器より先に効く。
- `permissions.ask` の操作（`git push` 等）は auto mode でも**必ず人に聞く**（分類器は上書きできない）。

> **重要な仕様上の制約と、その非対称性**: `permissions.defaultMode: "auto"` は**プロジェクトの `.claude/settings.json` /
> `.claude/settings.local.json` では効かない**（書くと無効なだけでなく、`~/.claude/settings.json` の
> defaultMode まで無視される）。auto mode を既定にできるのは **`~/.claude/settings.json`（ユーザー設定）、
> managed settings、または `claude --permission-mode auto`** だけ。
> 一方 **`"default"`（Manual）はプロジェクト設定から有効**で、設定の優先順位は
> managed > CLI > プロジェクト local > プロジェクト共有 > ユーザー なので、リポジトリに書けばクローンした全員に Manual を強制できる。
> つまり **リポジトリは権限を「締める」ことはできるが「緩める」ことはできない**。本フレームワークはこの非対称性を
> 前提にする: ポスチャ `auto` は「締めない（Claude Code の既定に乗る）」宣言、`conservative` は「Manual を強制する」設定。

## 4つのポスチャ

| posture | 誰が自動承認するか | 確認するもの | 向いている人 |
|---|---|---|---|
| **auto**（推奨・新規既定） | **Claude Code の auto mode 分類器**。フックは allow を出さない | 分類器が止めたもの・`permissions.ask`・deny フロア | 一人SIer・通常運用（auto mode が使える環境） |
| **conservative** | なし（フックも分類器も使わない運用） | すべて（＝全部 yes を押す） | 企業・情報漏洩防止・慎重派 |
| **balanced** | フック: 可逆・ローカル・読取専用（`policy.classify()=="auto"`） | それ以外 | auto mode が**使えない**環境で手間を減らしたい |
| **permissive** | フック: フロア以外すべて（`would_have_asked` を記録） | フロア該当のみ拒否 | auto mode が使えない環境でリスク受容・使い捨てワークツリー |

- **auto** は「分類器に任せる」宣言。セッションの `permission_mode` が `auto` でないとき（auto mode が
  利用不可・管理者が無効化・別モードで起動）、フックは **conservative 相当**で動き、**セッション最初の
  1回だけ systemMessage で不一致を通知**する（無音で「自動承認されているつもり」にさせない）。
- **conservative はリポジトリ単位で Manual を強制する**: `scripts/apply_posture.py --posture conservative <PJ>` が
  プロジェクトの `.claude/settings.json` に `permissions.defaultMode: "default"` を書く。これはクローンした全員に効き、
  上書きできるのは `--permission-mode` フラグと managed settings だけ。ポスチャを auto に戻すとこの値は除去される。
  CLI フラグで auto mode に上書きされたセッションでは、フックが**初回に「conservative だが auto mode で動いている」と通知**する。
  組織として auto mode を完全に禁止したいなら managed settings の `disableAutoMode: "disable"` を併用する。
- **balanced / permissive は auto mode セッションでは allow を出さない**（分類器に委ねる。初回に通知）。
  これらは auto mode が無い環境（旧バージョン・`disableAutoMode`・`-p` ヘッドレス）向けの近似として残す。

## 常時有効な deny フロア（どのポスチャでも拒否）

`.claude/hooks/policy.py` の正規表現が**コマンド文字列のどこにマッチしても**拒否する
（settings.json の glob は前方一致だけなので `foo && rm -rf /` を取り逃す。フロアはそれを捕まえる）。

- 破壊・不可逆: `rm -rf` / `dd if=` / `mkfs` / `DROP|TRUNCATE TABLE|DATABASE` / `.env` 上書き
- 外向き・供給: `git push --force` / `npm publish` / `docker push` / `terraform apply|destroy` / `kubectl delete|apply`
- 権限昇格・自己改変: `sudo` / `chmod 777` / `curl|wget … | sh` / 特権定義ファイル（`.claude/settings.json`・
  `.claude/hooks/`・`.git/hooks/`）への書込
- 機密の読み書き: `.env` / `secrets/` / `*.pem` / `id_rsa`

> 自己改変ブロックは**特権を定義するファイルに限定**する（`settings.json`＝許可ルール、`hooks/`＝強制ロジック、
> `.git/hooks/`）。`.claude/skills/`・`.claude/agents/` などの**振る舞いプロンプトは対象外**（機能開発は
> 通常 `src/` で完結し、スキル調整は保守作業として許可する）。ハード強制（settings/hooks）が守られていれば、
> プロンプトの微調整が自己封鎖や権限昇格につながることはない。

フロアは **`deny_guard.py`（allow を一切出さない独立フック）** と **宣言的 `permissions.deny`（fail-open
バックストップ）** の二層。`deny_guard` がバグや停止で動かなくても宣言的ルールが残る。逆に宣言的 glob が
取り逃す複合コマンドは `deny_guard` の regex が捕まえる。

## ポスチャの決まり方（読取優先順位）

```
ORCH_POSTURE 環境変数  >  .orchestrator/permission_posture.json の "posture"  >  conservative（ファイル無し）
```

新規プロジェクトでは `orchestrate` の作業合意インタビュー／`scripts/apply_posture.py` が **`auto`** を既定として
書く（企業は `--posture conservative`）。ファイルが**無い**ときのフォールバックは最も安全な `conservative`
（フックは何も自動承認しない）。

- `.orchestrator/permission_posture.json` は `orchestrate` がプロジェクト初期化時に生成し、**リポジトリに
  コミットされる**。これにより会社の `conservative` 設定はクローンした全員に引き継がれる。
- `ORCH_POSTURE` はテストや一時的な上書き用（設定ファイルを書き換えずに1セッションだけ変える）。
- ファイルが**壊れている・未知値**のときは最も安全な `conservative` にフォールバックし、**stderr に警告を
  出す**（loud＝無音で劣化させない）。ファイルが**無い**ときは既定どおり `conservative`（初回・劣化ではないので静か）。

### なぜ `.orchestrator/` に置くのか
`.claude/` はフロアで書込禁止（自己権限昇格の防止）なので、posture ファイルをそこに置くと**自分で更新できず
自己封鎖**になる。`.orchestrator/` は禁止対象外なので、再合意時にエージェントが `permission_posture.json` を
書き換えられる。フックは stdlib のみで動くため YAML でなく **JSON**（`project_status.yaml` を読むと PyYAML 依存が要る）。

## ポスチャの切り替え方

1. ユーザーが「auto にして」「conservative にして」等と指示する。
2. エージェントは `.orchestrator/permission_posture.json` を `{"posture":"auto"}` に更新し、
   `project_status.yaml` の `feedback_history` に合意内容＋日付を記録する（監査証跡）。
3. **次のセッションからそのポスチャを引き継ぐ**。指示が無ければ変更しない。

一時的に1回だけ変えたいなら環境変数: `ORCH_POSTURE=balanced claude` のように起動する。

### auto mode を「デフォルト」にする（ポスチャ auto と組で行う）
ポスチャはフックの振る舞いを決めるだけで、**Claude Code のモードは変えられない**。auto mode を既定で使うには
次のいずれか（ユーザー＝人が行う。エージェントは自分の権限を上げる操作はせず、提案に留める）:

| 方法 | コマンド / 設定 | 範囲 |
|---|---|---|
| 組み込み既定に任せる | 何もしない（v2.1.283+ のターミナル起動は既定で auto） | その環境 |
| ユーザー設定に書く | `~/.claude/settings.json` → `"permissions": {"defaultMode": "auto"}` | その人の全プロジェクト |
| 導入スクリプトで書く | `python3 scripts/apply_posture.py --set-user-default-mode auto <PJ>`（バックアップ作成） | 同上 |
| 1セッションだけ | `claude --permission-mode auto` | そのセッション |
| 企業で止める | managed settings の `disableAutoMode: "disable"` | 組織 |

**プロジェクトの `.claude/settings.json` に `defaultMode: "auto"` を書かない**（無効。かつユーザー設定の
defaultMode も無視される）。`apply_posture.py` はそれを見つけると警告して除去する。

### 分類器にフレームワークの意図を教える（任意・opt-in）
auto mode の分類器は 2 か所から文脈を読む:
1. **プロジェクトの CLAUDE.md**（分類器は Claude と同じ CLAUDE.md を読む）。本フレームワークの Rule 9 にある
   deny フロアの説明やバックログの運用ルールは、そのまま分類器の判断材料になる。プロジェクト固有の約束はここに書く。
2. **`autoMode` 設定ブロック**（`hard_deny` / `soft_deny` / `allow` / `environment`、散文）。**ユーザー設定か managed settings
   にしか置けない**（プロジェクト設定では読まれない）。フレームワーク推奨ルールを `templates/auto-mode-rules.json` に同梱し、
   `python3 scripts/apply_posture.py --install-auto-mode-rules` で `~/.claude/settings.json` にマージできる
   （`--remove-auto-mode-rules` で除去。ルールは `[AI Orchestrator]` 接頭辞で識別し、利用者の独自ルールと `"$defaults"` は温存）。

| セクション | 入れているもの | 意味 |
|---|---|---|
| `hard_deny` | 特権定義ファイル（settings.json / hooks / .git/hooks）への書込み、レシートの外部送信、秘密ファイル読取の迂回 | ユーザーの明示意図でも上書きされない。deny フロアと同じ線を分類器にも引く |
| `soft_deny` | ポスチャ/作業合意ファイルの勝手な変更、本番 DB の破壊的操作、`docs/backlog.html` の手編集、既定ブランチへの直接 push/merge | 明示意図があれば通る（再合意・明示依頼のフロー） |
| `allow` | `scripts/backlog.py`、検証/分析スクリプト、`docker compose` と各言語のテスト実行、`docs/` `src/` `tests/` `.orchestrator/` の工程成果物 | 定型作業が分類器で止まる頻度を下げ、自走が途切れにくくする |

注意: ルールは散文で確定的ではなく、**deny フロアの代替にはならない**（二重線を維持する）。また `~/.claude/settings.json`
なので**その人の全プロジェクトに効く**。企業配布や使い方が人によって違う環境では入れない方が無難。
反映確認は `claude auto-mode config`。

### auto / permissive でも「確認させたい」操作の作り方（フロアを触らずに）
フックの `allow` も auto mode の分類器も settings.json の `ask`/`deny` を上書きできない。だから `permissions.ask`
に入れた操作は **auto mode でも permissive でも必ずプロンプトが出る**。既定では次を `ask` にしている（外向き・不可逆寄りの git 操作）:

```
Bash(git push *)   Bash(git reset --hard *)   Bash(git rebase *)
```

フロア（=拒否）を広げずに「確認だけさせたい」ものはここに足す。これが Rule 8（Git 役割分担）とも噛み合う
（permissive はローカルの churn を自動承認するが、外向きの git は依然プロンプトが出る）。

## 観測レシートと allow-list 昇格

全ポスチャで `l1_shadow_log.py` が「意図した操作（Pre）」と「実行された操作（Post）」を
`~/.claude/receipts/<日付>/l1-shadow.jsonl` に記録する（既定は**リポジトリ外**）。`permission_gate.py` の
決定レシート（`l1-decisions.jsonl`）には **セッションの `permission_mode`** と決定主体
（`classifier` = auto mode に委ねた / `allow` = フックが承認 / `prompt` = 人 / `deny` = フロア）も残る。

- **秘匿**: レシートに書く前に `policy.redact()` が秘密をマスクする（`Bearer <token>` / `--password`・`-pXXX` /
  `key=value` 型の api_key・token・secret / `://user:pw@` / `AKIA…` / 長い base64 塊）。過剰マスク寄り
  （レシートはコマンドの「形」だけ分かればよく、頻度集計は秘密を含まない**コマンド族キー**で行う）。
- **コミット禁止**: レシートはコマンド列を含むので commit しない（`.gitignore` で保護。`L1_RECEIPTS_DIR` を
  repo 内に向けた場合も無視される）。定期的に削除・ローテートしてよい。
- **昇格**: 溜まったレシートを `python3 scripts/analyze_l1.py --min 5` にかけると、「毎回 yes していて可逆で
  N 回以上出た Bash コマンド族」を `permissions.allow[]` 候補として提案する。**貼る前に必ず人が精査する**
  （分類器はヒューリスティックであって安全性の証明ではない）。

## 既知の制約・注意

- **特権定義ファイルはフロアで書込禁止**（`.claude/settings.json`・`.claude/hooks/`・`.git/hooks/`）。
  エージェントが機能開発中に自分の許可ルールや強制ロジックを書き換えないための安全機構。
  `.claude/skills/`・`.claude/agents/` の編集は許可されるので、フレームワーク保守（スキル調整）は妨げない。
  許可ルールや hook 自体を編集したい場合のみ、意図的に手編集する。
- **パス regex は `/` 区切り**。WSL/Linux（本フレームワークの対象）を前提とする。Windows ネイティブの
  バックスラッシュパス（`.claude\settings.json`）は path フロアを回避し得るので、Windows ネイティブで
  使う場合は別途注意。
- **フックは exit 0 で観測に徹する場面がある**（`l1_shadow_log`）。この層のロギング失敗は best-effort で
  握り潰す（セッションを止めない）。誠実性ルールが対象とする「業務ロジックの偽成功」とは層が異なる。
- **フックの配線変更は settings.json 再読込（多くはセッション再起動）で反映**される。

## 導入・検証ツール

- **既存プロジェクトへの導入**: `python3 scripts/apply_posture.py [--posture auto|conservative|balanced|permissive] /path/to/your-project`
  （このフレームワークの checkout から実行。既定 `auto`。`--posture` を明示すると再合意として既存値を上書き、
  未指定なら既存を尊重）。フック配置・settings.json のマージ・posture 初期値の作成・**ポスチャに応じた `defaultMode` の同期**
  （conservative → `"default"` を書く／それ以外 → 除去）・レシートの .gitignore 追記までを**冪等**に行う。
  `--set-user-default-mode auto` で `~/.claude/settings.json` の `permissions.defaultMode` を、
  `--install-auto-mode-rules` / `--remove-auto-mode-rules` で同ファイルの `autoMode` ルールを更新する（いずれも opt-in・バックアップ作成）。マージは温存優先:
  `permissions.allow` と導入者の独自フック配線は消さず、置き換えた配線は必ず報告する（loud）。
  コミットはしないので、実行後に diff を確認してからコミットする。
- **検証**: `python3 scripts/verify_permission_hooks.py`（保守者向け）。合成 PreToolUse JSON で
  決定表・auto mode との共存・フォールバック・redact・導入スクリプトの温存/冪等性まで自動検証する（全PASSで exit 0）。
  `.claude/hooks/` はフロアで AI が書けないため、新版フックを別ディレクトリに置いて
  `ORCH_HOOKS_DIR=<dir> python3 scripts/verify_permission_hooks.py` で差し替え前に検証できる。

## 関連
- CLAUDE.md **Rule 9**（合意・引き継ぎのルール）／ **Rule 8**（Git 役割分担・同じ型）
- `docs/security/LEVEL2_SECURITY.md`（セキュリティ全体像）
- 実装: `.claude/hooks/policy.py`・`deny_guard.py`・`permission_gate.py`・`l1_shadow_log.py`・`scripts/analyze_l1.py`
- ツール: `scripts/apply_posture.py`（既存PJ導入）・`scripts/verify_permission_hooks.py`（検証）
