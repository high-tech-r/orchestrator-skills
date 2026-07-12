# 権限ポスチャ（Permission Posture）

「どこまで AI に自動承認を委ねるか」をユーザーが選べる仕組み。リスクを受容して速度を優先したい人も、
情報漏洩を防ぎたい企業も、同じフレームワークを自分の基準で使えるようにする。CLAUDE.md **Rule 9** の実装。

- **一度合意し、記録し、超えない。指示が無ければ前回の選択を引き継ぐ**（Rule 8＝Git 役割分担と同じ型）。
- **deny フロアは全ポスチャで常時有効**。これが permissive を責任もって提供できる前提。

## 3つのポスチャ

| posture | 自動承認するもの | 確認するもの | 向いている人 |
|---|---|---|---|
| **conservative**（既定） | なし | すべて（＝全部 yes を押す） | 企業・情報漏洩防止・慎重派 |
| **balanced** | 可逆・ローカル・読取専用（`policy.classify()=="auto"`） | それ以外 | 手間を減らしたい通常運用 |
| **permissive** | フロア以外すべて（`would_have_asked` を記録） | フロア該当のみ拒否 | リスク受容・使い捨てワークツリー |

**conservative は「導入しただけで素の Claude Code より安全」** ＝ 危険操作（deny フロア）を拒否し、
かつ**予期せぬ自動許可は一切起きない**。自動承認が有効になるのは、ユーザーが明示的に posture を
上げて記録したときだけ。

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
ORCH_POSTURE 環境変数  >  .orchestrator/permission_posture.json の "posture"  >  conservative
```

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

1. ユーザーが「balanced にして」等と指示する。
2. エージェントは `.orchestrator/permission_posture.json` を `{"posture":"balanced"}` に更新し、
   `project_status.yaml` の `feedback_history` に合意内容＋日付を記録する（監査証跡）。
3. **次のセッションからそのポスチャを引き継ぐ**。指示が無ければ変更しない。

一時的に1回だけ変えたいなら環境変数: `ORCH_POSTURE=permissive claude` のように起動する。

### permissive でも「確認させたい」操作の作り方（フロアを触らずに）
フックの `allow` は settings.json の `ask`/`deny` を上書きできない。だから `permissions.ask` に入れた操作は
**permissive でも必ずプロンプトが出る**。既定では次を `ask` にしている（外向き・不可逆寄りの git 操作）:

```
Bash(git push *)   Bash(git reset --hard *)   Bash(git rebase *)
```

フロア（=拒否）を広げずに「確認だけさせたい」ものはここに足す。これが Rule 8（Git 役割分担）とも噛み合う
（permissive はローカルの churn を自動承認するが、外向きの git は依然プロンプトが出る）。

## 観測レシートと allow-list 昇格

全ポスチャで `l1_shadow_log.py` が「意図した操作（Pre）」と「実行された操作（Post）」を
`~/.claude/receipts/<日付>/l1-shadow.jsonl` に記録する（既定は**リポジトリ外**）。

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

- **既存プロジェクトへの導入**: `python3 scripts/apply_posture.py /path/to/your-project`
  （このフレームワークの checkout から実行）。フック配置・settings.json のマージ・posture 初期値の
  作成・レシートの .gitignore 追記までを**冪等**に行う。マージは温存優先:
  `permissions.allow` と導入者の独自フック配線は消さず、置き換えた配線は必ず報告する（loud）。
  コミットはしないので、実行後に diff を確認してからコミットする。
- **検証**: `python3 scripts/verify_permission_hooks.py`（保守者向け）。合成 PreToolUse JSON で
  決定表・フォールバック・redact・導入スクリプトの温存/冪等性まで自動検証する（全PASSで exit 0）。

## 関連
- CLAUDE.md **Rule 9**（合意・引き継ぎのルール）／ **Rule 8**（Git 役割分担・同じ型）
- `docs/security/LEVEL2_SECURITY.md`（セキュリティ全体像）
- 実装: `.claude/hooks/policy.py`・`deny_guard.py`・`permission_gate.py`・`l1_shadow_log.py`・`scripts/analyze_l1.py`
- ツール: `scripts/apply_posture.py`（既存PJ導入）・`scripts/verify_permission_hooks.py`（検証）
