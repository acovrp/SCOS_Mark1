# SleepyCat Raw Data — Ground-Truth Profile

> Generated read-only from `acovrp/Pwa@main/data` (the live dashboard repo, left
> untouched). Reproduce with `python tools/profile_data.py <DATA_DIR>`.
> **This file is the contract.** Parsers must use these EXACT column names.
> Prior sessions broke on guessed headers (`advertised product id (asin)`),
> UTF-16, and case-sensitive joins — none of that is guessed here.

## TL;DR — good news and the three things that bite

- **Good:** every file is clean `utf-8`, comma-delimited, sane headers. No UTF-16.
- **Bite 1 — no targets anywhere.** None of the 9 files contains monthly targets.
  Everything in the PRD that needs a target (achievement %, projected close, gap)
  is **blocked until a target input exists**. The metric Aman says matters most
  (TACoS / cannibalization) needs *no* targets — so we start there.
- **Bite 2 — date windows don't fully overlap.** Pick the window deliberately
  (see below) or you'll compare weeks that don't exist in every source.
- **Bite 3 — no single `internal_sku_id`.** Amazon joins on `asin`, Flipkart on
  `sku`/`fsn`. The product taxonomy lives in `snapshot.json.channels` (17 lines).
  A SKU master / mapping is the first real build dependency.

## Files

| File | Rows | What it is | Key cols | Date range |
|---|---:|---|---|---|
| `ads_daily.csv` | 37,959 | Amazon ads daily | `asin`,`sku`,`ad_type`(SP/SD/SB),`spend`,`sales`,`orders`,`units` | 2026-02-03 → 05-04 |
| `br_history.csv` | 66,654 | Amazon Business Report | `asin`,`sessions`,`units ordered`,`ordered product sales`,`page views`,`buy box percentage` | 2026-01-01 → 04-20 |
| `st_report.csv` | 211,403 | Amazon search-term report | `customer_search_term`,`match_type`,`spend`,`14_day_total_sales`,`campaign_name`,`ad_group_name` | 2026-04-27 → 05-17 |
| `fk_history.csv` | 4,222 | Flipkart daily | `sku`,`asin`,`product`,`category`,`units`,`listing_price`,`clf`,`oiv`,`customer_price` | 2026-03-01 → 05-26 |
| `fk_clf_by_sku_actual.csv` | 297 | Flipkart SKU master + CLF | `listing_id`,`fsn`,`sku`,`vertical`,`mrp`,`ssp`,`flipkart_selling_price`,`clf` | (master) |
| `ba_sqp.json` | 4,875 terms | Brand Analytics Search Query Perf | `terms[].term/rank/by_period`, monthly `periods` | 2026-01 → 05 |
| `inventory.json` | — | Snowflake inventory | `all_skus`, `warehouses_used`(5), `summary` | snapshot 05-27 |
| `snapshot.json` | 17 lines | **Dashboard's own serialized model** | `channels`{17 product lines}, `adSpend`, `weeklyCube`, `keywords` | 05-28 |
| `wow_data.json` | — | Week-over-week cube | `fk`(ads/sov/placement), `az_sessions`, `az_ads` | recent |

### Header gotchas (use verbatim)
- `br_history.csv` headers contain **spaces**: `units ordered`, `ordered product sales`, `buy box percentage`.
- `st_report.csv` revenue col is `14_day_total_sales` (attribution-lagged, not same-day).
- SKU format is structured: `SC-ORIG-K-78x72x8` = brand-product-size-dims; FK uses `SC-F-...`.

## Join model (reality, not the PRD's ideal)

```
Amazon:   ads_daily.asin ── br_history.asin            (organic + paid by ASIN)
Flipkart: fk_history.sku ── fk_clf_by_sku_actual.sku   (OIV = listing_price + clf)
Taxonomy: snapshot.json.channels  ── maps ASIN/SKU → 17 product lines
Bridge:   ads_daily has BOTH asin and sku → the natural ASIN↔SKU rosetta stone
```
There is **no `internal_sku_id` column**; the dashboard's `channels` object is the
de-facto SKU master. First build dependency = derive a clean SKU↔line↔ASIN map
from `ads_daily` + `snapshot.json` and show unmapped rows (never drop silently).

## snapshot.json week bucketing (contract — verified)

`snapshot.json` months are **sequential ISO-week groups, NOT calendar months**:
`jan`=W01–05, `feb`=W06–09, **`mar`=W10–14**, `apr`=W15–18, `may`=W19–22
(`weeklyWeeks` lists W01–W22). Any reconciliation against the live dashboard
must use this bucketing, or it will look ~25% off when it is actually correct.

## Validation result (slice_amazon.py, Original Mattress)

- **Ad spend reconciles to −0.00%** vs `snapshot.originalmatt.amz.adspend.mar`
  → the raw-data pipeline reads ads **identically** to the live dashboard.
- **Revenue is −14.6%** (week-aligned) → entirely the organic-only ASIN coverage
  gap. Confirms the binding dependency: an **ASIN→line master** is required for
  accurate revenue (PRD §29). Pipeline is correct; the input is missing.

## Recommended analysis window

Dense overlap of the daily Amazon sources (`ads_daily` ∩ `br_history`) is
**2026-02-03 → 04-20** (~11 weeks). Use the **last full ISO week before 04-20**
for the first "this week vs last week" slice. `st_report` (Apr 27–May 17) is for
keyword-level drilldown, a later layer.

## What's computable TODAY from real data (no targets needed)

For any ASIN / product line, for a chosen week vs prior week:
- **Revenue** = `br_history.ordered product sales`
- **Ad spend / Ad sales** = `ads_daily.spend` / `ads_daily.sales`
- **TACoS** = ad spend ÷ total revenue  ← *the metric that matters most*
- **ROAS** = ad sales ÷ ad spend
- **Organic %** = (revenue − ad sales) ÷ revenue
- **Cannibalization signal** = ROAS ↑ **and** TACoS ↑ together (the bad signal)
- Split by `ad_type` (SP/SD/SB); intent (branded/generic) needs campaign-name parsing from `st_report`.

This is exactly the weekly flow in `myask.md` — and it needs zero inputs we don't
already have. That's the first vertical slice.
