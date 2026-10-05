"""Input, output and SQL guardrails for the agent.

Deliberately standard-library only. Keeping the rules free of LangGraph, a vector
store and an HTTP client means they can be unit-tested in milliseconds and reused
by any service in the stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_QUESTION_CHARS = 500

# --- PII and secret redaction ------------------------------------------------

_PHONE_RE = r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\d)"

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(_PHONE_RE)),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{16,}")),
    ("api_key", re.compile(r"(?i)\b(?:sk|pk)-[A-Za-z0-9_-]{16,}")),
    ("api_key", re.compile(r"(?i)\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}")),
)

# --- Prompt-injection screening ---------------------------------------------

_INJECTION_PATTERNS: tuple[str, ...] = (
    r"(?i)\bignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?|rules?)\b",
    r"(?i)\bdisregard\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above)\b",
    r"(?i)\b(?:reveal|print|show|repeat)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions?)\b",
    r"(?i)\byou\s+are\s+now\b",
    r"(?i)\bact\s+as\s+(?:a\s+)?(?:different|new|unrestricted)\b",
    r"(?i)\bdeveloper\s+mode\b",
    r"(?i)\b(?:drop|truncate|alter)\s+table\b",
    r";\s*--",
)

# --- SQL safety --------------------------------------------------------------

READ_ONLY_PREFIXES = ("select", "with")

FORBIDDEN_SQL_TOKENS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "grant",
        "revoke",
        "truncate",
        "attach",
        "detach",
        "pragma",
        "vacuum",
        "reindex",
        "replace",
        "call",
        "merge",
        "copy",
    }
)


@dataclass(frozen=True)
class Result:
    """Outcome of a guardrail check. `reasons` holds machine-readable codes."""

    ok: bool
    reasons: tuple[str, ...] = ()


def redact(text: str) -> tuple[str, tuple[str, ...]]:
    """Mask anything that looks like PII or a credential.

    Returns the redacted text and the kinds that were found, so callers can log
    the kinds without logging the values.
    """
    found: list[str] = []
    out = text
    for kind, pattern in _PII_PATTERNS:
        if pattern.search(out):
            found.append(kind)
            out = pattern.sub(f"[REDACTED:{kind}]", out)
    return out, tuple(dict.fromkeys(found))


def sanitise(text: str) -> str:
    """Redact in one call, for the common case where only the cleaned text is wanted."""
    return redact(text)[0]


def screen_injection(text: str) -> Result:
    """Flag prompt-injection shaped input.

    Heuristic only: it narrows the attack surface, it does not close it.
    """
    hit = [p for p in _INJECTION_PATTERNS if re.search(p, text)]
    return Result(ok=not hit, reasons=tuple(hit))


def validate_question(text: str) -> Result:
    """Cheap structural checks before anything is embedded or sent to a model."""
    problems: list[str] = []
    if not text or not text.strip():
        problems.append("empty")
    if len(text) > MAX_QUESTION_CHARS:
        problems.append("too_long")
    if "\x00" in text:
        problems.append("nul_byte")
    return Result(ok=not problems, reasons=tuple(problems))


def strip_sql_fences(raw: str) -> str:
    """Remove markdown fences and a trailing semicolon that models like to add."""
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.lower().startswith("sql"):
            text = text[3:]
    return text.strip().rstrip(";")


def is_read_only_sql(sql: str) -> bool:
    """True only for a single SELECT/WITH statement with no DDL or DML anywhere in it.

    This is a gate, not a sandbox. The real control is a least-privilege database
    role; see docs/adr/0002.
    """
    tokens = " ".join(sql.split()).lower().split()
    if not tokens or tokens[0] not in READ_ONLY_PREFIXES:
        return False
    return not any(t in FORBIDDEN_SQL_TOKENS for t in tokens)
