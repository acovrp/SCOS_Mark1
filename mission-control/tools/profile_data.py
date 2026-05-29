#!/usr/bin/env python3
"""Read-only profiler for the SleepyCat raw data.

Surface the REAL shape of each file (true headers, encoding, dtypes, row counts,
date ranges, candidate join keys) BEFORE any parser is written — the step
skipped in prior sessions that caused column-name and encoding bugs.

Usage:  python tools/profile_data.py [DATA_DIR]
No external deps; stdlib only. Never mutates the source files.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

# Read-only. Point at a local copy of the raw data (never committed here).
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/pwa-data/data")
JOIN_HINTS = re.compile(r"(asin|fsn|sku|internal|child|parent|keyword|campaign)", re.I)
DATE_HINT = re.compile(r"\b(date|day|week|month|period)\b", re.I)


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:4]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    return "utf-8"


def sniff_delim(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        return ","


def profile_csv(path: Path) -> None:
    enc = detect_encoding(path)
    with path.open("r", encoding=enc, errors="replace", newline="") as f:
        sample = f.read(8192)
        f.seek(0)
        delim = sniff_delim(sample)
        reader = csv.reader(f, delimiter=delim)
        try:
            header = next(reader)
        except StopIteration:
            print("  (empty)")
            return
        rows = 0
        first_row = None
        date_cols = [i for i, h in enumerate(header) if DATE_HINT.search(h or "")]
        date_vals: dict[int, set] = {i: set() for i in date_cols}
        for row in reader:
            rows += 1
            if first_row is None and row:
                first_row = row
            if rows <= 50000:
                for i in date_cols:
                    if i < len(row) and row[i]:
                        date_vals[i].add(row[i])
    print(f"  encoding={enc}  delimiter={delim!r}  data_rows={rows}  columns={len(header)}")
    print(f"  columns: {header}")
    join_cols = [h for h in header if JOIN_HINTS.search(h or "")]
    if join_cols:
        print(f"  >> candidate join keys: {join_cols}")
    for i in date_cols:
        vals = sorted(v for v in date_vals[i] if v)
        if vals:
            print(f"  >> date col '{header[i]}': {vals[0]} .. {vals[-1]} ({len(date_vals[i])} distinct sampled)")
    if first_row:
        preview = {header[j]: first_row[j] for j in range(min(len(header), len(first_row)))}
        print(f"  sample row (first 8 cols): {dict(list(preview.items())[:8])}")


def walk_json(obj, depth=0, max_depth=3):
    pad = "    " + "  " * depth
    if depth > max_depth:
        print(f"{pad}...")
        return
    if isinstance(obj, dict):
        keys = list(obj.keys())
        print(f"{pad}object with {len(keys)} keys: {keys[:15]}{' ...' if len(keys) > 15 else ''}")
        for k in keys[:3]:
            print(f"{pad}  ['{k}'] ->")
            walk_json(obj[k], depth + 2, max_depth)
    elif isinstance(obj, list):
        print(f"{pad}array len={len(obj)}")
        if obj:
            walk_json(obj[0], depth + 1, max_depth)
    else:
        print(f"{pad}{type(obj).__name__}: {repr(obj)[:80]}")


def profile_json(path: Path) -> None:
    enc = detect_encoding(path)
    try:
        obj = json.loads(path.read_text(encoding=enc, errors="replace"))
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        return
    print(f"  encoding={enc}")
    walk_json(obj)


def main() -> None:
    if not DATA.exists():
        sys.exit(f"data dir not found: {DATA} (pass path as argv[1])")
    for path in sorted(DATA.iterdir()):
        print(f"\n{'='*70}\n{path.name}  ({path.stat().st_size/1e6:.2f} MB)\n{'='*70}")
        if path.suffix == ".csv":
            profile_csv(path)
        elif path.suffix == ".json":
            profile_json(path)


if __name__ == "__main__":
    main()
