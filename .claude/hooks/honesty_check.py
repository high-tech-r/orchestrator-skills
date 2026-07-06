#!/usr/bin/env python3
# =============================================================================
# 誠実性チェック（実装の誠実性 / 嘘をつくコードの禁止）
# =============================================================================
# CLAUDE.md 最優先原則「嘘をつくコードの禁止」の *機械的バックストップ*。
# implement / consistency-check がプロンプトで指示している内容を、コードを書いた
# 瞬間（Edit / Write / MultiEdit の PostToolUse）に構文検査で二重化する。
#
# 位置づけ:
#   - security CI（Gitleaks 等）がシークレットを機械強制するのと同じ発想を、
#     「誠実性ホットスポット」に広げたもの。
#   - Gate 3（/code-review）の code_review_risk_signals と同じ観点を「書いた瞬間」に当てる。
#
# 設計方針:
#   - **誤検出を最小化する**。意味判定が必要なもの（「送信しました」が本当に送ったか等）は
#     扱わず、構文的に高シグナルなパターンだけを見る。
#   - 検出したら exit 2 で stderr を Claude に返す（=非致命。ユーザーの操作は止めない）。
#     Claude は「該当なら修正／意図的なら理由を添えて続行」で応答する。
#   - 該当ゼロなら exit 0 で沈黙する。
#
# 拡張:
#   検出器は check_* 関数として独立。パターンを増やすときは関数を足して CHECKS に登録する。
# =============================================================================

import json
import re
import sys

# 検査対象の拡張子（プロダクションコード + テスト。docs/markdown は対象外）
CODE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
             ".php", ".go", ".rb", ".java", ".kt", ".cs"}

# 無音握り潰しでない「正しい後始末」を示すキーワード（本体にこれがあれば握り潰しではない）
HANDLED_MARKERS = re.compile(
    r"\b(log|logger|logging|console|Log::|report|raise|throw|abort|"
    r"return\s+(false|False|error|Err|new\s+\w*Error)|print|warn|error)\b",
    re.IGNORECASE,
)

# 握り潰しの本体とみなす自明な文（これ「だけ」なら握り潰し）
TRIVIAL_BODY = re.compile(
    r"^(pass|\.\.\.|continue|break|return\s*;?|return\s+(None|null|nil|undefined)\s*;?)$"
)


def _load_content(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, UnicodeError):
        return None


def check_python_silent_except(lines):
    """Python: except 節の本体が pass / return None 等のみで、ログも raise も無い → 無音握り潰し。"""
    findings = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)except\b(.*):\s*(#.*)?$", line)
        if not m:
            continue
        indent = len(m.group(1))
        # bare except は無条件で誠実性の要注意
        bare = m.group(2).strip() == ""
        # 本体（より深いインデントの連続行）を集める
        body = []
        for nxt in lines[i + 1:]:
            if nxt.strip() == "" or nxt.lstrip().startswith("#"):
                continue
            cur_indent = len(nxt) - len(nxt.lstrip())
            if cur_indent <= indent:
                break
            body.append(nxt.strip())
        body_text = " ".join(body)
        trivial = body and all(TRIVIAL_BODY.match(b) for b in body)
        handled = bool(HANDLED_MARKERS.search(body_text))
        if bare and not handled:
            findings.append((i + 1, "bare `except:` で例外を捕捉している（型を絞らず、後始末も不明瞭）"))
        elif trivial and not handled:
            findings.append((i + 1, "except 節が握り潰しになっている（本体が pass / return None 等のみでログも再送出も無い）"))
    return findings


def check_brace_silent_catch(content, lines):
    """JS/TS/PHP/Java/Go 等: catch ブロックが空 or return null/false のみで、ログも throw も無い。"""
    findings = []
    for m in re.finditer(r"\bcatch\b[^\{]*\{", content):
        start = m.end() - 1  # 開き `{` の位置
        depth = 0
        end = None
        # ブロックの終端を素朴なブレースカウントで探す（最大 4000 文字まで）
        for j in range(start, min(len(content), start + 4000)):
            c = content[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end is None:
            continue
        body = content[start + 1:end]
        # コメント・空白を除去した実体
        stripped = re.sub(r"//.*|/\*.*?\*/", "", body, flags=re.DOTALL).strip()
        stripped_oneline = re.sub(r"\s+", " ", stripped).strip()
        empty = stripped == ""
        trivial = re.fullmatch(
            r"(return\s*(null|false|nil|undefined)?\s*;?)?", stripped_oneline
        ) is not None
        handled = bool(HANDLED_MARKERS.search(body))
        if (empty or trivial) and not handled:
            lineno = content.count("\n", 0, m.start()) + 1
            reason = "空の catch ブロック" if empty else "catch が return null/false のみ"
            findings.append((lineno, f"{reason}（例外を握り潰している。ログ出力も再送出も無い）"))
    return findings


def check_bearer_nullish(lines):
    """Authorization ヘッダに null/undefined 等を積んでいる（`Bearer null` を送って失敗させる嘘フロー）。"""
    findings = []
    for i, line in enumerate(lines):
        if re.search(r"[Bb]earer\s*(null|undefined|None|nil)\b", line) or (
            "Authorization" in line and re.search(r"\b(null|undefined|None|nil)\b", line)
        ):
            findings.append((i + 1, "Authorization に null/undefined を積んでいる（未実装フローに無効値を送って失敗させる嘘フロー）"))
    return findings


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # 入力が読めないときは黙って通す（フックで作業を止めない）

    if payload.get("tool_name") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    path = (payload.get("tool_input") or {}).get("file_path", "")
    if not path:
        sys.exit(0)

    # 対象拡張子のみ。フック自身・markdown・docs 配下は除外
    lower = path.lower()
    if not any(lower.endswith(ext) for ext in CODE_EXTS):
        sys.exit(0)
    if lower.endswith("honesty_check.py") or "/docs/" in lower:
        sys.exit(0)

    content = _load_content(path)
    if content is None:
        sys.exit(0)
    lines = content.splitlines()

    findings = []
    findings += check_python_silent_except(lines) if lower.endswith(".py") else []
    findings += check_brace_silent_catch(content, lines) if not lower.endswith(".py") else []
    findings += check_bearer_nullish(lines)

    if not findings:
        sys.exit(0)

    findings.sort(key=lambda f: f[0])
    header = (
        f"⚠ 誠実性チェック（CLAUDE.md 最優先原則: 嘘をつくコードの禁止）が "
        f"{path} で {len(findings)} 件を検出しました:\n"
    )
    body = "\n".join(f"  - L{ln}: {msg}" for ln, msg in findings)
    guidance = (
        "\n\n各件について: **本当に握り潰し/嘘フローなら修正する**"
        "（最低でもログ出力＋呼び出し元への失敗伝播、認証エラーなら 401 リカバリ）。"
        "\n意図的で安全と判断できる場合のみ、その理由を1行添えて続行してよい。"
    )
    print(header + body + guidance, file=sys.stderr)
    sys.exit(2)  # PostToolUse: stderr を Claude に返す（非致命）


if __name__ == "__main__":
    main()
