"""Shared policy for the L1 foundation hooks.

Single source of truth for:
  1. the HARD-DENY FLOOR (irreversible / external / self-privilege ops), and
  2. an ADVISORY reversibility classifier (auto / ask / deny) used only for
     logging in Phase 0.

Standard library only. Imported by deny_guard.py, l1_shadow_log.py and
permission_gate.py.
"""
import re

# ---------------------------------------------------------------------------
# HARD-DENY FLOOR
# Enforced by deny_guard.py. Regexes match ANYWHERE in the command string,
# unlike settings.json globs which only match a command *prefix*. This is the
# reliable layer; the declarative rules in settings.json are a backstop.
# ---------------------------------------------------------------------------
DENY_BASH = [
    (r'(?<![\w-])rm\b'
     r'(?=[^;&|\n]*(?:\s-\w*r\b|\s-\w*r[a-z]*\b|\s--recursive\b))'
     r'(?=[^;&|\n]*(?:\s-\w*f\b|\s-\w*f[a-z]*\b|\s--force\b))', "recursive+force delete (rm -rf)"),
    (r'\bgit\s+push\b[^\n]*(?:--force\b|--force-with-lease\b|\s-f\b)', "git force push"),
    (r'\bgit\b[^\n]*--no-verify\b', "bypass git hooks (--no-verify)"),
    (r'\bsudo\b', "sudo"),
    (r'\bchmod\s+(?:-\S+\s+)*0*777\b', "chmod 777"),
    (r'\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b', "pipe download into shell"),
    (r'\bdd\s+if=', "dd raw write"),
    (r'\bmkfs\b', "format filesystem"),
    (r'>\s*(?:[^\s]*/)?\.env\b', "overwrite .env"),
    (r'\b(?:DROP|TRUNCATE)\s+(?:TABLE|DATABASE|SCHEMA)\b', "destructive SQL"),
    (r'\b(?:npm|yarn|pnpm)\s+publish\b', "package publish"),
    (r'\bdocker\s+push\b', "container image push"),
    (r'\b(?:terraform|tofu)\s+(?:apply|destroy)\b', "infra apply/destroy"),
    (r'\bkubectl\s+(?:delete|apply)\b', "k8s mutate"),
]
# File paths the agent must never WRITE/EDIT: secrets + self-privilege escalation.
DENY_PATH_WRITE = [
    (r'(?:^|/)\.env(?:\.|$)', "secret file (.env)"),
    (r'(?:^|/)secrets?/', "secrets directory"),
    (r'\.pem$|(?:^|/)id_rsa\b', "private key"),
    (r'(?:^|/)\.claude/(?:settings\.json|hooks/)',
     "agent config (.claude/settings.json, hooks/) — self-privilege escalation"),
    (r'(?:^|/)\.git/hooks/', "git hooks — self-privilege escalation"),
]
# Paths the agent must never READ.
DENY_PATH_READ = [
    (r'(?:^|/)\.env(?:\.|$)', "secret file (.env)"),
    (r'(?:^|/)secrets?/', "secrets directory"),
    (r'\.pem$|(?:^|/)id_rsa\b', "private key"),
]


def match_deny(tool_name, tool_input):
    """Return a human-readable reason if the call hits the hard-deny floor,
    otherwise None."""
    ti = tool_input or {}
    if tool_name == "Bash":
        cmd = ti.get("command", "") or ""
        for pat, reason in DENY_BASH:
            if re.search(pat, cmd, re.IGNORECASE):
                return reason
        return None
    if tool_name in ("Write", "Edit", "MultiEdit"):
        path = ti.get("file_path", "") or ""
        for pat, reason in DENY_PATH_WRITE:
            if re.search(pat, path, re.IGNORECASE):
                return reason
        return None
    if tool_name == "Read":
        path = ti.get("file_path", "") or ""
        for pat, reason in DENY_PATH_READ:
            if re.search(pat, path, re.IGNORECASE):
                return reason
        return None
    return None


# ---------------------------------------------------------------------------
# ADVISORY REVERSIBILITY CLASSIFIER  (logging only, never enforced in Phase 0)
#   auto = reversible / local / read-only  -> Phase 2 allow-list candidate
#   deny = hits the hard-deny floor
#   ask  = everything else (stays a human decision)
# ---------------------------------------------------------------------------
AUTO_BASH_PREFIXES = [
    "ls", "cat", "head", "tail", "wc", "find", "grep", "rg", "pwd", "which",
    "file", "stat", "du", "df", "echo", "tree", "date", "env", "printenv",
    "git status", "git log", "git diff", "git show", "git branch", "git fetch",
    "git add", "git commit", "git stash", "git worktree",
    "npm test", "npm run test", "npm run lint", "npm run typecheck", "npm ci",
    "composer install", "composer validate",
    "vendor/bin/phpunit", "php vendor/bin/phpunit", "./vendor/bin/phpunit",
    "pytest", "./gradlew test", "make test", "mvn test",
]
AUTO_READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit"}
_SUBCMD_TOOLS = ("git", "npm", "yarn", "pnpm", "composer", "php", "docker",
                 "kubectl", "make", "mvn", "go", "cargo")


def _bash_key(cmd):
    toks = (cmd or "").strip().split()
    if not toks:
        return "(empty)"
    if toks[0] in _SUBCMD_TOOLS and len(toks) > 1:
        return toks[0] + " " + toks[1]
    return toks[0]


def normalize_key(tool_name, tool_input):
    """Collapse a call into a command *family* for frequency counting."""
    ti = tool_input or {}
    if tool_name == "Bash":
        return "Bash: " + _bash_key(ti.get("command", "") or "")
    if "file_path" in ti:
        p = ti.get("file_path", "") or ""
        top = p.lstrip("./").split("/", 1)[0] if p else "(none)"
        return f"{tool_name}: {top}/"
    return tool_name


def classify(tool_name, tool_input):
    if match_deny(tool_name, tool_input):
        return "deny"
    if tool_name in AUTO_READ_TOOLS:
        return "auto"
    if tool_name in EDIT_TOOLS:
        return "auto"  # edits inside a git worktree are reversible
    if tool_name == "Bash":
        c = ((tool_input or {}).get("command", "") or "").strip()
        for pref in AUTO_BASH_PREFIXES:
            if c == pref or c.startswith(pref + " ") or c.startswith(pref + "\t"):
                return "auto"
        return "ask"
    return "ask"


# ---------------------------------------------------------------------------
# RECEIPT REDACTION
# Receipts (l1-shadow.jsonl / l1-decisions.jsonl) store the raw command line so
# you can eyeball what a command family looked like. That sample must never
# become a secret leak: a single `curl -H "Authorization: Bearer sk-…"` would
# otherwise land in plaintext on disk. redact() masks high-signal secrets
# BEFORE the sample is written.
#
# Bias: OVER-masking is fine — the receipt only needs the command *shape*, and
# frequency analysis keys off normalize_key() (the command family), never the
# raw sample. Leaking a token is not fine. So we err toward masking.
# ---------------------------------------------------------------------------
_REDACT_SUBS = [
    # --password SECRET | --password=SECRET | --token SECRET | -pSECRET (attached)
    (re.compile(r"(--password[=\s]+|--token[=\s]+)(\S+)", re.IGNORECASE), r"\1***"),
    (re.compile(r"(-p)(\S{5,})"), r"\1***"),
    # Authorization: Bearer <token>
    (re.compile(r"(Bearer\s+)(\S+)", re.IGNORECASE), r"\1***"),
    # key=value / key: value secrets
    (re.compile(r"\b((?:api[_-]?key|secret[_-]?key|access[_-]?key|token|secret|"
                r"passwd|password|auth)\s*[=:]\s*)(\S+)", re.IGNORECASE), r"\1***"),
    # URL embedded credentials  ://user:pw@host
    (re.compile(r"(://[^:/\s@]+:)([^@/\s]+)(@)"), r"\1***\3"),
    # AWS access key id
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA***"),
    # long opaque blobs (base64/hex-ish, >=32 chars) — likely keys/tokens
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}\b"), "***"),
]


def redact(s):
    """Mask high-signal secrets in a command-line sample. Applied to the raw
    sample only, never to the command family key used for frequency analysis.
    Returns the input unchanged if it is falsy."""
    if not s:
        return s
    out = s
    for pat, repl in _REDACT_SUBS:
        out = pat.sub(repl, out)
    return out
