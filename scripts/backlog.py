#!/usr/bin/env python3
"""プロダクトバックログ（docs/backlog.html）の生成・更新 CLI。

バックログは **HTML 1ファイルのみ**で管理する（Markdown のバックログは作らない）。
  - 表示（HTML/CSS/JS）はフレームワークが所有するテンプレート templates/backlog/backlog.html
    （未完了/完了・優先度・Tier・種別での絞り込み、検索、並べ替え、進捗、詳細展開、
     ダーク/ライト対応、file:// で開ける自己完結）。UX はテンプレートで担保する。
  - データは HTML 内の <script id="backlog-data" type="application/json"> に埋め込む JSON。
  - 人も AI も HTML を手で編集しない。更新は必ずこの CLI を通す（壊れたデータを書かない＝誠実性）。
    すべての書込み前にスキーマ検証を行い、失敗したら書かずに exit 1 で止まる。

使い方（プロジェクト root で実行。既定ファイルは docs/backlog.html）:
  backlog.py init --project "案件名"                       # 新規作成（既存があれば --force が必要）
  backlog.py add --id F-001 --name "タスク追加" --priority 高 --tier B \
             --summary "..." --acceptance "条件1" --acceptance "条件2"
  backlog.py add --type td --id TD-001 --name "..." --priority 中 --severity 高 \
             --location "src/api/x.py:42" --action 修正 --source docs/audit/2026-10-20_summary.md --summary "..."
  backlog.py add --from-json items.json                   # 一括追加（配列 or {"items":[...]}）
  backlog.py update F-001 --status 進行中 --phase design   # 任意フィールドの更新
  backlog.py set-status F-001 完了                        # ステータスだけ更新（updated_at も更新）
  backlog.py list [--status 未着手 --status 進行中] [--type feature] [--format table|json|ids]
  backlog.py show F-001                                   # 1件を JSON で表示
  backlog.py next-id [--type feature|td]                  # 次の採番を表示（F-003 / TD-002）
  backlog.py validate                                     # スキーマ検証のみ
  backlog.py render                                        # 最新テンプレートでデータを再埋め込み（テンプレート更新の反映）
  backlog.py import-md docs/backlog.md --project "案件名"  # 旧 Markdown 表からの一度限りの移行
  backlog.py export-json                                   # 埋め込みデータを stdout に出力

語彙（テンプレートの JS と一致させる。変えるときは両方を変える）:
  status   : 未着手 / 進行中 / 完了 / 保留 / エスカレーション
  priority : 高 / 中 / 低
  tier     : S / A / B / C / D / 未判定
  type     : feature（F-xxx）/ td（TD-xxx 技術的負債。audit の起票先）
  phase    : requirements / design / gate1 / implement / test_design / test_code / gate2 / review_guide / code_review / human_review / done

標準ライブラリのみ。
"""
import argparse
import datetime
import json
import os
import re
import sys

SCHEMA_VERSION = 1
DEFAULT_FILE = os.path.join("docs", "backlog.html")
STATUSES = ["未着手", "進行中", "完了", "保留", "エスカレーション"]
PRIORITIES = ["高", "中", "低"]
TIERS = ["S", "A", "B", "C", "D", "未判定"]
TYPES = ["feature", "td"]
SEVERITIES = ["高", "中", "低"]
ACTIONS = ["修正", "撤去", "リファクタ", "要調査"]
PHASES = ["requirements", "design", "gate1", "implement", "test_design", "test_code",
          "gate2", "review_guide", "code_review", "human_review", "done"]
ID_RE = {"feature": re.compile(r"^F-\d{3,}$"), "td": re.compile(r"^TD-\d{3,}$")}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DATA_RE = re.compile(
    r'(<script id="backlog-data" type="application/json">)(.*?)(</script>)', re.DOTALL)
TEMPLATE_VERSION_RE = re.compile(r'<meta name="backlog-template-version" content="([^"]+)">')


def today():
    return datetime.date.today().isoformat()


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- template
def find_template(explicit=None):
    """テンプレートの探索順: --template > <FW>/templates/backlog/backlog.html（この scripts/ の親）
    > ./templates/backlog/backlog.html > .orchestrator/backlog_template.html"""
    cands = []
    if explicit:
        cands.append(explicit)
    here = os.path.dirname(os.path.abspath(__file__))
    cands.append(os.path.join(os.path.dirname(here), "templates", "backlog", "backlog.html"))
    cands.append(os.path.join("templates", "backlog", "backlog.html"))
    cands.append(os.path.join(".orchestrator", "backlog_template.html"))
    for c in cands:
        if os.path.isfile(c):
            return c
    die("バックログのテンプレートが見つかりません。templates/backlog/backlog.html を配置するか "
        "--template で指定してください（探索: " + ", ".join(cands) + "）")


def template_version(html):
    m = TEMPLATE_VERSION_RE.search(html)
    return m.group(1) if m else "unknown"


# ---------------------------------------------------------------- io
def read_html(path):
    if not os.path.isfile(path):
        die(f"{path} がありません。`backlog.py init` で作成してください")
    with open(path, encoding="utf-8") as f:
        return f.read()


def extract_data(html, path="<html>"):
    m = DATA_RE.search(html)
    if not m:
        die(f"{path} にデータ島（<script id=\"backlog-data\">）が見つかりません。テンプレートが壊れています")
    raw = m.group(2).replace("<\\/", "</")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        die(f"{path} の埋め込み JSON を解析できません: {e}")


def embed(html, data):
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    payload = payload.replace("</", "<\\/")  # </script> 早期終了の防止
    if not DATA_RE.search(html):
        die("テンプレートにデータ島がありません")
    return DATA_RE.sub(lambda m: m.group(1) + payload + m.group(3), html, count=1)


def write_html(path, html, data):
    """検証に通らないデータは書かない（壊れた状態を『正常』として保存しない）。"""
    errors = validate_data(data)
    if errors:
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        die("検証に失敗したため書き込みを中止しました（ファイルは変更していません）")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(embed(html, data))
    os.replace(tmp, path)


def load(path):
    html = read_html(path)
    return html, extract_data(html, path)


# ---------------------------------------------------------------- validation
def validate_item(it, idx):
    errs = []
    p = f"items[{idx}]" + (f"({it.get('id')})" if isinstance(it, dict) and it.get("id") else "")
    if not isinstance(it, dict):
        return [f"{p}: オブジェクトではありません"]
    t = it.get("type", "feature")
    if t not in TYPES:
        errs.append(f"{p}: type は {TYPES} のいずれか（{t!r}）")
    iid = it.get("id")
    if not isinstance(iid, str) or not iid:
        errs.append(f"{p}: id が必要です")
    elif t in ID_RE and not ID_RE[t].match(iid):
        errs.append(f"{p}: id の形式が不正（feature は F-001 / td は TD-001 形式）: {iid!r}")
    if not it.get("name"):
        errs.append(f"{p}: name が必要です")
    if it.get("priority") not in PRIORITIES:
        errs.append(f"{p}: priority は {PRIORITIES} のいずれか（{it.get('priority')!r}）")
    if it.get("status") not in STATUSES:
        errs.append(f"{p}: status は {STATUSES} のいずれか（{it.get('status')!r}）")
    if it.get("tier", "未判定") not in TIERS:
        errs.append(f"{p}: tier は {TIERS} のいずれか（{it.get('tier')!r}）")
    if it.get("phase") not in (None, "") and it.get("phase") not in PHASES:
        errs.append(f"{p}: phase は {PHASES} のいずれか（{it.get('phase')!r}）")
    for k in ("acceptance", "depends_on"):
        v = it.get(k, [])
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            errs.append(f"{p}: {k} は文字列の配列")
    for k in ("created_at", "updated_at"):
        v = it.get(k)
        if v and not DATE_RE.match(str(v)):
            errs.append(f"{p}: {k} は YYYY-MM-DD（{v!r}）")
    links = it.get("links", {})
    if not isinstance(links, dict) or not all(isinstance(v, str) for v in links.values()):
        errs.append(f"{p}: links は {{名前: 相対パス}} の辞書")
    if t == "td":
        if it.get("severity") not in SEVERITIES:
            errs.append(f"{p}: TD には severity（{SEVERITIES}）が必要")
        if not it.get("location"):
            errs.append(f"{p}: TD には location（file:line）が必要（着手時にそのまま作業できる粒度）")
        if it.get("action") not in ACTIONS:
            errs.append(f"{p}: TD には action（{ACTIONS}）が必要")
    return errs


def validate_data(data):
    errs = []
    if not isinstance(data, dict):
        return ["ルートはオブジェクトである必要があります"]
    if data.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version は {SCHEMA_VERSION}（{data.get('schema_version')!r}）")
    if not isinstance(data.get("items"), list):
        return errs + ["items は配列である必要があります"]
    seen = set()
    for i, it in enumerate(data["items"]):
        errs.extend(validate_item(it, i))
        if isinstance(it, dict) and it.get("id"):
            if it["id"] in seen:
                errs.append(f"id が重複しています: {it['id']}")
            seen.add(it["id"])
    for it in data["items"]:
        if isinstance(it, dict):
            for d in it.get("depends_on", []) or []:
                if d not in seen:
                    errs.append(f"{it.get('id')}: depends_on の {d} はバックログに存在しません")
    return errs


# ---------------------------------------------------------------- helpers
def new_data(project):
    return {"schema_version": SCHEMA_VERSION, "project": project or "", "updated_at": today(), "items": []}


def touch(data, item=None):
    data["updated_at"] = today()
    if item is not None:
        item["updated_at"] = today()


def find_item(data, iid):
    for it in data["items"]:
        if it.get("id") == iid:
            return it
    die(f"{iid} はバックログにありません")


def next_id(data, typ):
    prefix = "F-" if typ == "feature" else "TD-"
    nums = [int(it["id"][len(prefix):]) for it in data["items"]
            if it.get("type", "feature") == typ and it.get("id", "").startswith(prefix) and it["id"][len(prefix):].isdigit()]
    return f"{prefix}{(max(nums) + 1 if nums else 1):03d}"


def build_item(a, data):
    typ = a.type or "feature"
    it = {
        "id": a.id or next_id(data, typ),
        "type": typ,
        "name": a.name,
        "priority": a.priority,
        "status": a.status or "未着手",
        "tier": a.tier or "未判定",
        "summary": a.summary or "",
        "acceptance": a.acceptance or [],
        "depends_on": a.depends_on or [],
        "phase": a.phase or "",
        "links": dict(kv.split("=", 1) for kv in (a.link or [])),
        "notes": a.notes or "",
        "created_at": today(),
        "updated_at": today(),
    }
    if typ == "td":
        it.update({"severity": a.severity, "location": a.location, "action": a.action, "source": a.source or ""})
    return it


def add_items(data, items):
    ids = {it.get("id") for it in data["items"]}
    for it in items:
        if it.get("id") in ids:
            die(f"id が既に存在します: {it.get('id')}（更新は `update`）")
        ids.add(it.get("id"))
        data["items"].append(it)
    touch(data)


# ---------------------------------------------------------------- commands
def cmd_init(a):
    if os.path.exists(a.file) and not a.force:
        die(f"{a.file} は既に存在します。上書きするなら --force（データは消えます）")
    html = read_html(find_template(a.template))
    data = new_data(a.project)
    write_html(a.file, html, data)
    print(f"作成: {a.file}（template v{template_version(html)}）")


def cmd_add(a):
    html, data = load(a.file)
    if a.from_json:
        with open(a.from_json, encoding="utf-8") as f:
            raw = json.load(f)
        items = raw.get("items") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            die("--from-json は配列、または {\"items\": [...]} を受け付けます")
        for it in items:
            it.setdefault("type", "feature")
            it.setdefault("status", "未着手")
            it.setdefault("tier", "未判定")
            it.setdefault("acceptance", [])
            it.setdefault("depends_on", [])
            it.setdefault("links", {})
            it.setdefault("created_at", today())
            it.setdefault("updated_at", today())
            if not it.get("id"):
                it["id"] = next_id(data, it["type"])
            add_items(data, [it])  # 逐次追加（連番の重複を避ける）
        write_html(a.file, html, data)
        print(f"追加: {len(items)} 件 → {a.file}")
        return
    if not a.name or not a.priority:
        die("--name と --priority は必須です（または --from-json）")
    it = build_item(a, data)
    add_items(data, [it])
    write_html(a.file, html, data)
    print(f"追加: {it['id']} {it['name']} → {a.file}")


def cmd_update(a):
    html, data = load(a.file)
    it = find_item(data, a.id)
    for k in ("name", "priority", "status", "tier", "summary", "phase", "notes", "severity", "location", "action", "source"):
        v = getattr(a, k, None)
        if v is not None:
            it[k] = v
    if a.acceptance is not None:
        it["acceptance"] = a.acceptance
    if a.add_acceptance:
        it.setdefault("acceptance", []).extend(a.add_acceptance)
    if a.depends_on is not None:
        it["depends_on"] = a.depends_on
    if a.link:
        it.setdefault("links", {}).update(dict(kv.split("=", 1) for kv in a.link))
    touch(data, it)
    write_html(a.file, html, data)
    print(f"更新: {it['id']}（status={it['status']}, phase={it.get('phase') or '—'}）")


def cmd_set_status(a):
    html, data = load(a.file)
    it = find_item(data, a.id)
    it["status"] = a.status
    if a.phase:
        it["phase"] = a.phase
    if a.status == "完了" and not a.phase:
        it["phase"] = "done"
    touch(data, it)
    write_html(a.file, html, data)
    print(f"更新: {it['id']} → {a.status}")


def cmd_list(a):
    _, data = load(a.file)
    rows = [it for it in data["items"]
            if (not a.status or it["status"] in a.status)
            and (not a.type or it.get("type", "feature") in a.type)
            and (not a.priority or it["priority"] in a.priority)
            and (not a.tier or it.get("tier", "未判定") in a.tier)]
    if a.format == "json":
        print(json.dumps({"project": data.get("project"), "updated_at": data.get("updated_at"), "items": rows},
                         ensure_ascii=False, indent=2))
        return
    if a.format == "ids":
        print("\n".join(it["id"] for it in rows))
        return
    if not rows:
        print("(該当なし)")
        return
    w = max(len(it["id"]) for it in rows)
    print(f"{'ID'.ljust(w)}  種別     優先  Tier  ステータス      名称")
    for it in rows:
        print(f"{it['id'].ljust(w)}  {('TD' if it.get('type') == 'td' else '機能').ljust(7)}  "
              f"{it['priority']}    {str(it.get('tier', '未判定')).ljust(4)}  {it['status'].ljust(8)}  {it['name']}")
    print(f"\n{len(rows)} 件 / 全 {len(data['items'])} 件（{data.get('project') or '無題'} / 更新 {data.get('updated_at')}）")


def cmd_show(a):
    _, data = load(a.file)
    print(json.dumps(find_item(data, a.id), ensure_ascii=False, indent=2))


def cmd_next_id(a):
    _, data = load(a.file)
    print(next_id(data, a.type or "feature"))


def cmd_validate(a):
    html, data = load(a.file)
    errs = validate_data(data)
    if errs:
        print(f"NG: {a.file}（{len(errs)} 件）")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print(f"OK: {a.file}（{len(data['items'])} 件 / schema v{data.get('schema_version')} / template v{template_version(html)}）")


def cmd_render(a):
    old_html, data = load(a.file)
    tpl = read_html(find_template(a.template))
    write_html(a.file, tpl, data)
    print(f"再描画: {a.file}（template v{template_version(old_html)} → v{template_version(tpl)}）")


def cmd_export_json(a):
    _, data = load(a.file)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_import_md(a):
    """旧 docs/backlog.md（Markdown 表）からの移行。列: ID | 機能名 | 優先度 | ステータス | Tier | 概要 を想定。
    ヘッダ行から列位置を推定し、読み取れない行は報告して止める（無音で捨てない）。"""
    if os.path.exists(a.file) and not a.force:
        die(f"{a.file} は既に存在します。移行結果で上書きするなら --force")
    with open(a.source, encoding="utf-8") as f:
        lines = f.read().splitlines()
    header, rows = None, []
    for ln in lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            if any("ID" in c.upper() for c in cells):
                header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    if header is None:
        die(f"{a.source} に ID 列を含む表ヘッダが見つかりません")

    def col(*names):
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        return None

    ci, cn, cp, cs, ct, cd = (col("id"), col("機能名", "名称", "name"), col("優先", "priority"),
                              col("ステータス", "状態", "status"), col("tier"), col("概要", "summary"))
    if ci is None or cn is None:
        die("ID 列と機能名/名称 列は必須です")
    st_map = {"未着手": "未着手", "進行中": "進行中", "完了": "完了", "保留": "保留", "エスカレーション": "エスカレーション", "done": "完了", "pending": "未着手", "in_progress": "進行中"}
    items, problems = [], []
    for cells in rows:
        g = lambda i: cells[i] if i is not None and i < len(cells) else ""  # noqa: E731
        iid = g(ci)
        typ = "td" if iid.startswith("TD-") else "feature"
        status_raw = re.sub(r"[^\w぀-ヿ一-鿿]", "", g(cs)) if cs is not None else "未着手"
        status = next((v for k, v in st_map.items() if k in status_raw), None)
        if status is None:
            problems.append(f"{iid}: ステータス {g(cs)!r} を解釈できません")
            status = "未着手"
        pr = g(cp) if cp is not None else "中"
        if pr not in PRIORITIES:
            problems.append(f"{iid}: 優先度 {pr!r} を解釈できません → 中 に設定")
            pr = "中"
        tier = g(ct) if ct is not None and g(ct) in TIERS else "未判定"
        it = {"id": iid, "type": typ, "name": g(cn), "priority": pr, "status": status, "tier": tier,
              "summary": g(cd), "acceptance": [], "depends_on": [], "phase": "done" if status == "完了" else "",
              "links": {}, "notes": "", "created_at": today(), "updated_at": today()}
        if typ == "td":
            it.update({"severity": "中", "location": "（移行: 要記入）", "action": "要調査", "source": a.source})
            problems.append(f"{iid}: TD の severity/location/action は移行後に `update` で記入してください")
        items.append(it)
    data = new_data(a.project)
    data["items"] = items
    tpl = read_html(find_template(a.template))
    write_html(a.file, tpl, data)
    print(f"移行: {a.source} → {a.file}（{len(items)} 件）")
    if problems:
        print("要確認（移行で推定・補完した箇所。放置しない）:")
        for p in problems:
            print(f"  - {p}")
    print("移行後は旧 Markdown を削除し、以後は HTML のみで管理してください。")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=DEFAULT_FILE, help=f"バックログ HTML（既定 {DEFAULT_FILE}）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="新規作成"); p.add_argument("--project", default=""); p.add_argument("--force", action="store_true"); p.add_argument("--template"); p.set_defaults(fn=cmd_init)

    p = sub.add_parser("add", help="項目を追加")
    p.add_argument("--from-json", help="配列 or {items:[...]} の JSON ファイルから一括追加")
    p.add_argument("--id"); p.add_argument("--type", choices=TYPES); p.add_argument("--name")
    p.add_argument("--priority", choices=PRIORITIES); p.add_argument("--status", choices=STATUSES)
    p.add_argument("--tier", choices=TIERS); p.add_argument("--summary"); p.add_argument("--acceptance", action="append")
    p.add_argument("--depends-on", action="append"); p.add_argument("--phase", choices=PHASES)
    p.add_argument("--link", action="append", help="名前=相対パス（例 design=design/F-001.md）"); p.add_argument("--notes")
    p.add_argument("--severity", choices=SEVERITIES); p.add_argument("--location"); p.add_argument("--action", choices=ACTIONS); p.add_argument("--source")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("update", help="項目を更新"); p.add_argument("id")
    p.add_argument("--name"); p.add_argument("--priority", choices=PRIORITIES); p.add_argument("--status", choices=STATUSES)
    p.add_argument("--tier", choices=TIERS); p.add_argument("--summary"); p.add_argument("--phase", choices=PHASES); p.add_argument("--notes")
    p.add_argument("--acceptance", action="append", help="受入条件を置き換える（複数指定）"); p.add_argument("--add-acceptance", action="append", help="受入条件を追加")
    p.add_argument("--depends-on", action="append"); p.add_argument("--link", action="append")
    p.add_argument("--severity", choices=SEVERITIES); p.add_argument("--location"); p.add_argument("--action", choices=ACTIONS); p.add_argument("--source")
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser("set-status", help="ステータスを更新"); p.add_argument("id"); p.add_argument("status", choices=STATUSES); p.add_argument("--phase", choices=PHASES); p.set_defaults(fn=cmd_set_status)

    p = sub.add_parser("list", help="一覧"); p.add_argument("--status", action="append", choices=STATUSES); p.add_argument("--type", action="append", choices=TYPES)
    p.add_argument("--priority", action="append", choices=PRIORITIES); p.add_argument("--tier", action="append", choices=TIERS)
    p.add_argument("--format", choices=["table", "json", "ids"], default="table"); p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="1件表示"); p.add_argument("id"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("next-id", help="次の採番"); p.add_argument("--type", choices=TYPES); p.set_defaults(fn=cmd_next_id)
    p = sub.add_parser("validate", help="検証"); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser("render", help="最新テンプレートで再描画"); p.add_argument("--template"); p.set_defaults(fn=cmd_render)
    p = sub.add_parser("export-json", help="データを出力"); p.set_defaults(fn=cmd_export_json)
    p = sub.add_parser("import-md", help="旧 Markdown 表から移行"); p.add_argument("source"); p.add_argument("--project", default=""); p.add_argument("--force", action="store_true"); p.add_argument("--template"); p.set_defaults(fn=cmd_import_md)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
