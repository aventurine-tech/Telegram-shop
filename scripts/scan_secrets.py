#!/usr/bin/env python3
"""Fail if a tracked file looks like it contains a real secret (CI runs this; run it locally before a push).

Only high-confidence shapes are checked, so a hit is worth reading: Telegram bot tokens, private key blocks,
AWS / GitHub / Slack / Stripe-style keys, and passwords inside a connection URL. A line that is a deliberate
placeholder carries ``secret-scan: ignore``. Usage: ``python scripts/scan_secrets.py [path ...]`` (default: every
file git tracks).
"""
import re
import subprocess
import sys
from pathlib import Path

RULES = {
    "Telegram bot token": re.compile(r"(?<![\w:])\d{8,10}:[A-Za-z0-9_-]{35}(?![\w-])"),
    "private key block": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "Stripe-style secret key": re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b"),
    "password in a URL": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@'\"<>]+:(?!\$|\{|<|\*|x{3}|password|pass\b|secret)[^\s/:@'\"<>]{6,}@(?!\S*\$\{)"),
}
IGNORE_MARK = "secret-scan: ignore"
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".zip", ".gz",
                 ".pyc", ".mo", ".sqlite", ".db"}
MAX_BYTES = 2_000_000


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True).stdout
    return [p for p in out.decode().split("\0") if p]


def scan_text(text: str) -> list[tuple[int, str]]:
    """[(line number, rule name)] for every suspicious line."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        if IGNORE_MARK in line:
            continue
        for name, rule in RULES.items():
            if rule.search(line):
                hits.append((number, name))
    return hits


def scan_file(path: str) -> list[tuple[int, str]]:
    p = Path(path)
    if p.suffix.lower() in SKIP_SUFFIXES or not p.is_file() or p.stat().st_size > MAX_BYTES:
        return []
    try:
        return scan_text(p.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return []


def main(argv: list[str]) -> int:
    found = 0
    for path in argv or tracked_files():
        for number, name in scan_file(path):
            # Never print the matched text: the log would leak the very thing being found.
            print(f"{path}:{number}: possible {name}")
            found += 1
    if found:
        print(f"\n{found} possible secret(s). Remove them (and rotate anything real); "
              f"mark a harmless placeholder line with '{IGNORE_MARK}'.")
        return 1
    print("No secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
