#!/usr/bin/env python3
"""Shared SQLite connection helper for analisa-pt tools.

Centralizes PRAGMA tuning for fast analytical queries on large databases
(procurement.db is 1.3 GB / 1.6M rows; transparency.db is 28 MB but
ingested from 100K+ row xlsx files). One-line replacement for
``sqlite3.connect()`` that gives every connection:

* ``journal_mode=WAL`` — concurrent readers, single writer; readers no
  longer block on the writer (and vice versa) like in the default
  rollback-journal mode.
* ``synchronous=NORMAL`` — safe with WAL (the WAL file itself is
  crash-safe); ~2x faster than the default ``FULL``.
* ``temp_store=MEMORY`` — temp tables and indices live in RAM.
* ``cache_size=-200000`` — 200 MB page cache (negative means KB).
* ``mmap_size=268435456`` — 256 MB memory-mapped I/O so SQLite can
  read pages directly from the OS page cache without a syscall.

Usage::

    from utils_db import connect
    conn = connect('data/procurement.db')
    rows = conn.execute("SELECT * FROM contratos WHERE ...").fetchall()

The first three PRAGMAs (``journal_mode``, ``synchronous``, ``mmap_size``)
are persistent — once set on a DB, all future connections inherit them.
``cache_size`` and ``temp_store`` are per-connection, so the helper
applies them on every connect for safety. This makes the helper safe
to call on already-tuned DBs and on in-memory (``":memory:"``) DBs
(the PRAGMAs are simply no-ops there).
"""

import os
import sqlite3
import sys
from pathlib import Path
from typing import Union

__all__ = ["connect", "PRAGMAS"]


# ``mmap_size`` is platform-conditional: SQLite's memory-mapped I/O is
# significantly slower on Windows for databases >1 GB (Windows file-cache
# behavior differs from Linux/macOS). The default is 256 MB on POSIX
# systems, no mmap on Windows. To force a custom value, set the
# ``ANALISA_MMAP_SIZE`` env var (in bytes, 0 to disable).
_MMAP_SIZE = int(
    os.environ.get("ANALISA_MMAP_SIZE", "0" if sys.platform == "win32" else "268435456")
)

# PRAGMAs applied per-connection. Order doesn't matter for correctness,
# but listing WAL first is conventional so it's clear WAL is on.
PRAGMAS = [
    "journal_mode=WAL",
    "synchronous=NORMAL",
    "temp_store=MEMORY",
    "cache_size=-200000",       # 200 MB page cache (negative = KB)
]
if _MMAP_SIZE > 0:
    PRAGMAS.append(f"mmap_size={_MMAP_SIZE}")


def connect(db_path: Union[str, Path], row_factory: bool = True, **kwargs) -> sqlite3.Connection:
    """Open a SQLite connection with PRAGMA tuning for analytical workloads.

    Args:
        db_path: Path to the .db file, or ``":memory:"`` for an in-memory DB.
        row_factory: If True (default), set ``row_factory=sqlite3.Row`` so
                     rows can be accessed like dicts (``row["column"]``).
                     Set False for raw tuple rows.
        **kwargs: Passed through to ``sqlite3.connect()`` (e.g. ``timeout``,
                  ``isolation_level``).

    Returns:
        ``sqlite3.Connection`` with the PRAGMAs in :data:`PRAGMAS` applied.

    Example::

        conn = connect('data/procurement.db')
        rows = conn.execute(
            "SELECT adjudicante_nif, COUNT(*) "
            "FROM contratos WHERE precoContratual > 0 "
            "GROUP BY adjudicante_nif"
        ).fetchall()
    """
    conn = sqlite3.connect(str(db_path), **kwargs)
    if row_factory:
        conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        # PRAGMA journal_mode returns a row (the new mode); the rest are
        # silent. We just execute and discard the cursor.
        conn.execute(f"PRAGMA {pragma}")
    return conn
