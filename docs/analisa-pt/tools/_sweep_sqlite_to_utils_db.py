#!/usr/bin/env python3
"""One-time sweep: migrate raw sqlite3.connect calls to utils_db.connect.

Replaces `sqlite3.connect(...)` / `_sqlite3.connect(...)` (and self.sqlite3.connect)
with `db_connect(...)` / `_db_connect(...)`. Removes redundant
`conn.row_factory = sqlite3.Row` lines (db_connect sets row_factory by default).
Drops the `import sqlite3` line if no other sqlite3.* symbols are used.

Dry-run by default; pass --apply to actually rewrite files; --verify to smoke-test
each modified file with `python -c "import <module>"`.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

TOOLS = Path("docs/analisa-pt/tools")

# Already-wired files: leave alone
ALREADY_WIRED = {
    "utils_db.py",                       # the helper itself
    "add_adjudicatario_nif.py",          # standalone migration script
    "_sweep_sqlite_to_utils_db.py",       # this script
}

# Match sqlite3.connect(...) or _sqlite3.connect(...) or self.sqlite3.connect(...)
# The prefix capture group is the full call expression (e.g. "sqlite3", "_sqlite3",
# "self.sqlite3"). The arg capture is the contents inside the parens.
# re.DOTALL so the non-greedy arg match can span multiple lines.
CALL_RE = re.compile(
    r"(self\.)?(sqlite3|_sqlite3)\.connect\((.*?)\)",
    re.DOTALL,
)


def detect_patterns(src: str) -> dict:
    """Return a dict describing the patterns found in the file."""
    has_plain_import = bool(re.search(r"^import sqlite3\s*$", src, re.MULTILINE))
    has_aliased_import = bool(
        re.search(r"^import sqlite3 as _sqlite3\s*$", src, re.MULTILINE)
    )
    call_matches = list(CALL_RE.finditer(src))
    # sqlite3 symbols used OTHER than .connect (decides if we can drop the import)
    other_sqlite3_uses = set()
    for m in re.finditer(r"\bsqlite3\.(?!connect\b)(\w+)", src):
        other_sqlite3_uses.add(m.group(0))
    return {
        "has_plain_import": has_plain_import,
        "has_aliased_import": has_aliased_import,
        "call_count": len(call_matches),
        "other_sqlite3_uses": other_sqlite3_uses,
    }


def transform(src: str) -> tuple[str, list[str]]:
    """Transform the file. Returns (new_src, list_of_changes)."""
    changes: list[str] = []
    info = detect_patterns(src)

    if info["call_count"] == 0:
        return src, ["no sqlite3.connect calls; skipped"]

    # Decide which symbol to use
    uses_aliased = info["has_aliased_import"]
    connect_var = "_db_connect" if uses_aliased else "db_connect"

    # 1. Add the utils_db import (at the LAST TOP-LEVEL import line, not inside
    #    try/except blocks where the previous "last import" might be wrapped).
    if "from utils_db import connect" not in src and "import utils_db" not in src:
        import_line = f"from utils_db import connect as {connect_var}"
        lines = src.split("\n")
        # Find the last top-level (indent 0) import statement.
        # Skip lines that end with '(' — those are the OPENING of a multi-line
        # `from x import (...)` paren block; inserting after them would put
        # the new import INSIDE the parens.
        insert_at = None
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].strip()
            if (stripped.startswith("import ") or stripped.startswith("from ")):
                if stripped.endswith("("):
                    continue
                indent = len(lines[i]) - len(lines[i].lstrip())
                if indent == 0:
                    insert_at = i + 1
                    break
        if insert_at is None:
            # No top-level imports — insert at top (after shebang/encoding if present)
            insert_at = 0
            if lines and lines[0].startswith("#!"):
                insert_at = 1
            if len(lines) > insert_at and "coding" in lines[insert_at]:
                insert_at += 1
        lines.insert(insert_at, import_line)
        src = "\n".join(lines)
        changes.append(f"added import at line {insert_at}: {import_line}")

    # 2. Replace sqlite3.connect(...) -> connect_var(...)
    def repl_call(m: re.Match) -> str:
        self_prefix = m.group(1) or ""
        sqlite_var = m.group(2)  # "sqlite3" or "_sqlite3"
        # The call expression prefix is self_prefix + sqlite_var
        return f"{self_prefix}{connect_var}({m.group(3)})"

    new_src, n_replaced = CALL_RE.subn(repl_call, src)
    if n_replaced > 0:
        changes.append(f"replaced {n_replaced} sqlite3.connect(...) -> {connect_var}(...)")
        src = new_src

    # 3. Remove redundant `conn.row_factory = sqlite3.Row` lines
    new_src, n_removed = re.subn(
        r"^[ \t]*(\w+\.row_factory\s*=\s*)sqlite3\.Row[ \t]*\n",
        "",
        src,
        flags=re.MULTILINE,
    )
    if n_removed > 0:
        changes.append(f"removed {n_removed} redundant conn.row_factory = sqlite3.Row line(s)")
        src = new_src

    # 4. Drop the sqlite3 import if no other sqlite3.* uses remain
    if not info["other_sqlite3_uses"]:
        if uses_aliased:
            new_src, n = re.subn(
                r"^import sqlite3 as _sqlite3\s*\n",
                "",
                src,
                flags=re.MULTILINE,
            )
        else:
            new_src, n = re.subn(
                r"^import sqlite3\s*\n",
                "",
                src,
                flags=re.MULTILINE,
            )
        if n > 0:
            changes.append("removed unused `import sqlite3` (no other sqlite3.* uses)")
            src = new_src

    return src, changes


def verify_imports(target_files: list) -> list[tuple[Path, str]]:
    """Smoke-test each modified file by importing it. Returns (file, status)."""
    results = []
    for f in target_files:
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, '.'); import {f.stem}; print('{f.stem}: OK')",
            ],
            cwd=str(TOOLS),
            capture_output=True,
            text=True,
            timeout=30,
        )
        status = "OK" if r.returncode == 0 else f"FAIL: {r.stderr.strip()[:200]}"
        results.append((f, status))
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Actually rewrite files")
    ap.add_argument(
        "--verify", action="store_true", help="Verify each modified file still imports"
    )
    args = ap.parse_args()

    target_files: list[Path] = []
    for f in TOOLS.glob("*.py"):
        if f.name in ALREADY_WIRED or f.name.startswith("__"):
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        info = detect_patterns(src)
        if info["call_count"] > 0:
            target_files.append(f)

    print(
        f"Found {len(target_files)} files with raw sqlite3.connect calls "
        f"(dry-run: {not args.apply})\n"
    )
    changed_files: list[Path] = []
    for f in sorted(target_files):
        src = f.read_text(encoding="utf-8", errors="replace")
        new_src, changes = transform(src)
        if changes:
            print(f"=== {f.name} ===")
            for c in changes:
                print(f"  - {c}")
            if args.apply and new_src != src:
                f.write_text(new_src, encoding="utf-8")
                print(f"  -> APPLIED ({len(new_src)} bytes)")
                changed_files.append(f)
            elif not args.apply and new_src != src:
                print(f"  (dry-run: would write {len(new_src)} bytes)")
            print()

    print(
        f"Files that changed (or would change): "
        f"{len(changed_files) if args.apply else len(target_files)}"
    )
    if not args.apply:
        print("\nRe-run with --apply to actually rewrite the files.")
        return 0

    if args.verify and changed_files:
        print(f"\n=== Verifying {len(changed_files)} modified files ===")
        results = verify_imports(changed_files)
        all_ok = True
        for f, status in results:
            print(f"  {f.name}: {status}")
            if not status.startswith("OK"):
                all_ok = False
        if not all_ok:
            print("\nFAIL: some files failed to import")
            return 1
        print("\nAll files imported successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
