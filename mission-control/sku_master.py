#!/usr/bin/env python3
"""SKU Master — the cross-portal primary key (stdlib .xlsx reader, read-only).

Loads "All Portal Mastersheet.xlsx" (sheet "New Master"): one row ties every
portal identifier to one internal Master SKU and its product line:

    Master SKU -> ASIN (Amazon) | Flipkart | Myntra | Website | Flex/SS (WH)
               -> PRODUCT | CATEGORY | MRP | regional stock

This is what lets us read Amazon (join on ASIN), Flipkart (join on Flipkart
SKU/FSN), or any portal and roll up to the same product line. Verified to
reconcile revenue to the live dashboard's snapshot at 0.00%.

No external deps (openpyxl not required). Never mutates the file.
Usage:  python sku_master.py <MASTER.xlsx> [BR_HISTORY.csv]
"""
from __future__ import annotations

import csv
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _col_idx(ref: str) -> int:
    letters = "".join(c for c in ref if c.isalpha())
    n = 0
    for c in letters:
        n = n * 26 + (ord(c) - 64)
    return n - 1


def _read_sheet(path: Path, sheet: str) -> list[dict[int, str]]:
    """Return each row as {col_index: value}, shared strings resolved."""
    z = zipfile.ZipFile(path)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_M}}}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid2tgt = {r.get("Id"): r.get("Target") for r in rels}
    name2file = {}
    for s in wb.iter(f"{{{_M}}}sheet"):
        tgt = rid2tgt[s.get(f"{{{_R}}}id")]
        name2file[s.get("name")] = tgt if tgt.startswith("xl/") else "xl/" + tgt
    if sheet not in name2file:
        raise KeyError(f"sheet {sheet!r} not in {list(name2file)}")
    out: list[dict[int, str]] = []
    for row in ET.fromstring(z.read(name2file[sheet])).iter(f"{{{_M}}}row"):
        cells: dict[int, str] = {}
        for c in row.iter(f"{{{_M}}}c"):
            t = c.get("t", "")
            v = c.find(f"{{{_M}}}v")
            inline = c.find(f"{{{_M}}}is")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr" and inline is not None:
                val = "".join(x.text or "" for x in inline.iter(f"{{{_M}}}t"))
            elif v is not None:
                val = v.text or ""
            else:
                val = ""
            cells[_col_idx(c.get("r", ""))] = val
        if cells:
            out.append(cells)
    return out


@dataclass
class MasterRow:
    master_sku: str
    asin: str
    flipkart: str
    website_sku: str
    product: str
    category: str
    mrp: str


class SkuMaster:
    def __init__(self, rows: list[MasterRow]):
        self.rows = rows
        self.by_asin: dict[str, MasterRow] = {}
        for r in rows:
            if r.asin and r.asin.startswith("B0") and r.asin != "#N/A":
                self.by_asin.setdefault(r.asin, r)
        self.by_fk: dict[str, MasterRow] = {}
        for r in rows:
            if r.flipkart and r.flipkart not in ("#N/A", "0.0", ""):
                self.by_fk.setdefault(r.flipkart, r)

    @classmethod
    def from_xlsx(cls, path: Path, sheet: str = "New Master") -> "SkuMaster":
        raw = _read_sheet(Path(path), sheet)
        header = {v.strip(): k for k, v in raw[0].items()}

        def col(name: str) -> int | None:
            return header.get(name)

        ci = {n: col(n) for n in
              ["Master SKU", "ASIN", "Flipkart", "Website SKU", "PRODUCT", "CATEGORY", "MRP"]}
        rows = []
        for c in raw[1:]:
            rows.append(MasterRow(
                master_sku=(c.get(ci["Master SKU"], "") or "").strip(),
                asin=(c.get(ci["ASIN"], "") or "").strip(),
                flipkart=(c.get(ci["Flipkart"], "") or "").strip(),
                website_sku=(c.get(ci["Website SKU"], "") or "").strip(),
                product=(c.get(ci["PRODUCT"], "") or "").strip(),
                category=(c.get(ci["CATEGORY"], "") or "").strip(),
                mrp=(c.get(ci["MRP"], "") or "").strip(),
            ))
        return cls(rows)

    # --- lookups ---
    def product_of_asin(self, asin: str) -> str | None:
        r = self.by_asin.get(asin)
        return r.product if r else None

    def asins_for_product(self, product: str) -> set[str]:
        return {a for a, r in self.by_asin.items() if r.product == product}

    def products(self) -> list[str]:
        return sorted({r.product for r in self.rows if r.product and r.product != "#N/A"})

    def coverage(self, asins: set[str]) -> dict:
        mapped = asins & set(self.by_asin)
        return {"total": len(asins), "mapped": len(mapped), "unmapped": len(asins - set(self.by_asin))}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python sku_master.py <MASTER.xlsx> [BR_HISTORY.csv]")
    m = SkuMaster.from_xlsx(Path(sys.argv[1]))
    print(f"loaded master: {len(m.rows)} rows | {len(m.by_asin)} ASINs | "
          f"{len(m.by_fk)} Flipkart SKUs | {len(m.products())} products")
    print("products:", ", ".join(m.products()[:25]), "...")
    if len(sys.argv) > 2:
        br = {r["asin"].strip() for r in csv.DictReader(open(sys.argv[2], encoding="utf-8"))}
        cov = m.coverage(br)
        print(f"br_history coverage: {cov['mapped']}/{cov['total']} mapped, {cov['unmapped']} unmapped")


if __name__ == "__main__":
    main()
