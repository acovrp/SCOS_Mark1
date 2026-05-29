#!/usr/bin/env python3
"""Mission Control — first vertical slice (Amazon, read-only, real data).

The "answer machine" flow from myask.md, computed from raw files only:
  pick a product line -> this week vs last week -> Revenue, Ad Spend, Ad Sales,
  TACoS, ROAS, Organic% -> split by ad format (SP/SD/SB) -> cannibalization flag.

Two sources, joined on ASIN (ads_daily is the ASIN<->SKU bridge):
  ads_daily.csv  : spend, ad sales, by ad_type, has asin + sku
  br_history.csv : total revenue (ordered product sales) + sessions, asin only

Line membership = SKU prefix (e.g. SC-ORIG -> Original Mattress). br_history
ASINs that are never advertised cannot be line-mapped via this bridge; their
count is reported, never silently dropped.

Line membership comes from the SKU Master (ASIN→PRODUCT) when a master file is
given — this includes organic-only ASINs and makes revenue reconcile. Without a
master it falls back to the SKU-prefix heuristic from ads_daily (advertised
ASINs only).

Nothing is written; the live dashboard and raw data are untouched.
Usage:  python slice_amazon.py [DATA_DIR] [LINE] [MASTER_XLSX]
  LINE = PRODUCT name (with master, e.g. "Original Mattress") or SKU prefix.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/pwa-data/data")
MASTER = Path(sys.argv[3]) if len(sys.argv) > 3 else None
# With a master, LINE is a PRODUCT name; without one, a SKU prefix.
LINE_ARG = sys.argv[2] if len(sys.argv) > 2 else ("Original Mattress" if MASTER else "SC-ORIG")

# SKU prefix -> (friendly line name, snapshot.json channel id for reconciliation)
LINE_MAP = {
    "SC-ORIG": ("Original Mattress", "originalmatt"),
    "SC-ULTM": ("Ultima Mattress", "ultimamattre"),
    "SC-HYB": ("Hybrid Latex Mattress", "hybridlatexm"),
    "SC-CLD": ("Cloud Pillow", "cloudpillows"),
}
# PRODUCT name -> snapshot.json channel id (for reconciliation in master mode).
PRODUCT_SNAP = {
    "Original Mattress": "originalmatt",
    "Hybrid Latex Mattress": "hybridlatexm",
    "Cloud Pillow": "cloudpillows",
}
if MASTER:
    LINE_NAME, SNAP_LINE = LINE_ARG, PRODUCT_SNAP.get(LINE_ARG)
else:
    LINE_NAME, SNAP_LINE = LINE_MAP.get(LINE_ARG, (LINE_ARG, None))

# Sponsored Brands Video is a flavour of Sponsored Brands for this view.
AD_TYPE_GROUP = {"SP": "SP", "SD": "SD", "SB": "SB", "SBV": "SB"}

# Two full ISO weeks ending just before br_history's last day (2026-04-20).
WEEK_CURR = (dt.date(2026, 4, 13), dt.date(2026, 4, 19))  # 2026-W16
WEEK_PREV = (dt.date(2026, 4, 6), dt.date(2026, 4, 12))   # 2026-W15
# snapshot.json buckets months as sequential ISO-week groups, NOT calendar
# months: jan=W01-05, feb=W06-09, mar=W10-14, apr=W15-18, may=W19-22.
# Reconcile on the snapshot's own "March" = ISO weeks W10-W14.
RECON_WEEKS = {(2026, w) for w in range(10, 15)}
RECON_LABEL = "March = ISO W10-W14 (snapshot's own bucketing)"


def fnum(x: str) -> float:
    if not x:
        return 0.0
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return 0.0


def pdate(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s.strip()[:10])
    except (ValueError, AttributeError):
        return None


def in_range(d: dt.date | None, rng: tuple[dt.date, dt.date]) -> bool:
    return d is not None and rng[0] <= d <= rng[1]


@dataclass
class Agg:
    revenue: float = 0.0          # br_history: ordered product sales (total)
    units: int = 0                # br_history: units ordered
    sessions: int = 0
    ad_spend: float = 0.0
    ad_sales: float = 0.0
    spend_by_type: dict = field(default_factory=lambda: defaultdict(float))
    sales_by_type: dict = field(default_factory=lambda: defaultdict(float))

    @property
    def tacos(self) -> float:
        return 100 * self.ad_spend / self.revenue if self.revenue else 0.0

    @property
    def roas(self) -> float:
        return self.ad_sales / self.ad_spend if self.ad_spend else 0.0

    @property
    def organic_pct(self) -> float:
        return 100 * (self.revenue - self.ad_sales) / self.revenue if self.revenue else 0.0


def build_asin_set() -> tuple[set[str], str]:
    """Return (line ASINs, source description).

    Master mode: ASINs where PRODUCT == LINE_ARG (includes organic-only ASINs).
    Fallback: advertised ASINs whose SKU starts with the LINE_ARG prefix.
    """
    if MASTER:
        from sku_master import SkuMaster
        m = SkuMaster.from_xlsx(MASTER)
        asins = m.asins_for_product(LINE_ARG)
        return asins, f"SKU Master PRODUCT='{LINE_ARG}' ({len(asins)} ASINs)"
    asins = set()
    with (DATA / "ads_daily.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["sku"].strip().startswith(LINE_ARG):
                asins.add(r["asin"].strip())
    return asins, f"ads-prefix '{LINE_ARG}' — advertised ASINs only ({len(asins)})"


def _matches(d: dt.date | None, label: str) -> bool:
    if d is None:
        return False
    if label == "recon":
        return d.isocalendar()[:2] in RECON_WEEKS
    return in_range(d, WEEK_CURR if label == "curr" else WEEK_PREV)


def aggregate(asins: set[str]) -> dict[str, Agg]:
    """One Agg per bucket label: 'curr', 'prev', 'recon'."""
    buckets = {"curr": Agg(), "prev": Agg(), "recon": Agg()}

    with (DATA / "ads_daily.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["asin"].strip() not in asins:
                continue
            d = pdate(r["date"])
            grp = AD_TYPE_GROUP.get(r["ad_type"].strip(), r["ad_type"].strip())
            spend, sales = fnum(r["spend"]), fnum(r["sales"])
            for label in buckets:
                if _matches(d, label):
                    b = buckets[label]
                    b.ad_spend += spend
                    b.ad_sales += sales
                    b.spend_by_type[grp] += spend
                    b.sales_by_type[grp] += sales

    with (DATA / "br_history.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["asin"].strip() not in asins:
                continue
            d = pdate(r["date"])
            rev = fnum(r["ordered product sales"])
            units = int(fnum(r["units ordered"]))
            sess = int(fnum(r["sessions"]))
            for label in buckets:
                if _matches(d, label):
                    b = buckets[label]
                    b.revenue += rev
                    b.units += units
                    b.sessions += sess
    return buckets


def coverage_report(line_asins: set[str]) -> str:
    with (DATA / "br_history.csv").open(encoding="utf-8") as f:
        br_asins = {r["asin"].strip() for r in csv.DictReader(f)}
    present = len(line_asins & br_asins)
    if MASTER:
        return (f"{len(line_asins)} ASINs in line (from master, incl. organic-only); "
                f"{present} present in br_history.")
    with (DATA / "ads_daily.csv").open(encoding="utf-8") as f:
        ads_asins = {r["asin"].strip() for r in csv.DictReader(f)}
    return (f"{len(line_asins)} ASINs in line (advertised only); {present} in br_history. "
            f"{len(br_asins - ads_asins)} organic-only ASINs unmapped without a master "
            f"-> revenue will undercount. Pass a master to fix.")


def snapshot_march(snap_line: str) -> dict | None:
    if not snap_line:
        return None
    snap = json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))
    amz = snap.get("channels", {}).get(snap_line, {}).get("amz")
    if not amz:
        return None
    rev = sum(v for v in amz.get("revenue", {}).get("mar", []) if isinstance(v, (int, float)))
    spend = sum(v for v in amz.get("adspend", {}).get("mar", []) if isinstance(v, (int, float)))
    tacos_weeks = [v for v in amz.get("tacos", {}).get("mar", []) if isinstance(v, (int, float))]
    return {
        "revenue": rev,
        "adspend": spend,
        "tacos_computed": 100 * spend / rev if rev else 0.0,
        "tacos_weekly_avg": sum(tacos_weeks) / len(tacos_weeks) if tacos_weeks else None,
    }


def inr(x: float) -> str:
    """Indian-format rupees in lakhs."""
    return f"₹{x/1e5:,.2f}L"


def pct(x: float) -> str:
    return f"{x:.1f}%"


def delta_pct(a: float, b: float) -> str:
    if not b:
        return "n/a"
    return f"{100*(a-b)/b:+.2f}%"


def print_week_block(name: str, b: Agg) -> None:
    print(f"\n  {name}")
    print(f"    Revenue        {inr(b.revenue):>14}   Units {b.units:>5}   Sessions {b.sessions:>7}")
    print(f"    Ad Spend       {inr(b.ad_spend):>14}   Ad Sales {inr(b.ad_sales):>14}")
    print(f"    TACoS  {pct(b.tacos):>7}     ROAS {b.roas:>5.2f}     Organic {pct(b.organic_pct):>7}")
    parts = " | ".join(
        f"{t}: {inr(b.spend_by_type[t])} sp / {b.sales_by_type[t]/b.spend_by_type[t]:.1f}x"
        if b.spend_by_type[t] else f"{t}: —"
        for t in ("SP", "SD", "SB")
    )
    print(f"    By format      {parts}")


def main() -> None:
    if not DATA.exists():
        sys.exit(f"data dir not found: {DATA}")
    line_asins, src = build_asin_set()
    if not line_asins:
        sys.exit(f"no ASINs found for line {LINE_ARG!r}")
    b = aggregate(line_asins)
    curr, prev = b["curr"], b["prev"]

    print("=" * 64)
    print(f"  {LINE_NAME}   — Amazon, real data, read-only")
    print("=" * 64)
    print(f"  line source: {src}")
    print(f"  coverage: {coverage_report(line_asins)}")

    print(f"\n  WEEK-OVER-WEEK  (curr {WEEK_CURR[0]}..{WEEK_CURR[1]} vs prev {WEEK_PREV[0]}..{WEEK_PREV[1]})")
    print_week_block("This week", curr)
    print_week_block("Last week", prev)

    # The signal myask.md says matters most.
    roas_up = curr.roas > prev.roas
    tacos_up = curr.tacos > prev.tacos
    print("\n  WoW deltas:")
    print(f"    Revenue {delta_pct(curr.revenue, prev.revenue):>8}   "
          f"TACoS {delta_pct(curr.tacos, prev.tacos):>8}   "
          f"ROAS {delta_pct(curr.roas, prev.roas):>8}   "
          f"Organic {delta_pct(curr.organic_pct, prev.organic_pct):>8}")
    if roas_up and tacos_up:
        print("    ⚠  CANNIBALIZATION SIGNAL: ROAS up AND TACoS up together — "
              "ads are likely capturing already-organic sales.")
    elif tacos_up and not roas_up:
        print("    ⚠  TACoS rising while ROAS not improving — ad efficiency leaking.")
    else:
        print("    ✓  No cannibalization signal this week.")

    # Reconciliation against the live dashboard's own snapshot.
    print(f"\n  RECONCILIATION — {RECON_LABEL}")
    snap = snapshot_march(SNAP_LINE)
    recon = b["recon"]
    if snap:
        print(f"    {'metric':<10}{'computed':>16}{'snapshot':>16}{'delta':>10}")
        print(f"    {'ad spend':<10}{inr(recon.ad_spend):>16}{inr(snap['adspend']):>16}{delta_pct(recon.ad_spend, snap['adspend']):>10}   ads_daily")
        print(f"    {'revenue':<10}{inr(recon.revenue):>16}{inr(snap['revenue']):>16}{delta_pct(recon.revenue, snap['revenue']):>10}   br_history{' (incl. organic-only via master)' if MASTER else ' (advertised only)'}")
        print(f"    {'TACoS':<10}{pct(recon.tacos):>16}{pct(snap['tacos_computed']):>16}{delta_pct(recon.tacos, snap['tacos_computed']):>10}   spend/revenue")
        def ok(a, b):
            return bool(b) and abs(a - b) / b < 0.01
        spend_ok = ok(recon.ad_spend, snap["adspend"])
        rev_ok = ok(recon.revenue, snap["revenue"])
        if spend_ok and rev_ok:
            print("\n    VERDICT: FULL reconciliation to the live dashboard (<1% on spend AND revenue).\n"
                  "    The raw-data pipeline reads Amazon identically to your snapshot, via the SKU Master.")
        elif spend_ok:
            print("\n    VERDICT: ad spend reconciles (<1%); revenue is undercounted because line\n"
                  "    membership is advertised-ASIN-only. Pass the SKU Master to close the revenue gap.")
        else:
            print("\n    VERDICT: reconciliation FAILS — investigate before trusting these numbers.")
    else:
        print(f"    (no snapshot channel for {SNAP_LINE})")


if __name__ == "__main__":
    main()
