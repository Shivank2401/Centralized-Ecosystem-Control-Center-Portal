# Return directory (`config_manager/return_directory.yaml`)

Taxonomy for Amazon FBA customer returns — used by `return_database` (notebook now; `.py` later).

## What it manages

1. **`return_reason_mapping`** — Amazon `reason` codes → business groups  
   (same map as `return_database.ipynb` cell “create mapping”).
2. **`customer_comment_groups`** — cleaned/grouped free-text + pipe-structured comments.
3. **`alerts`** — flag anything not already in the directory.

## Customer-comment groups

| Key | Label |
|-----|--------|
| `size_too_small` | Size Too Small |
| `size_too_large` | Size Too Large |
| `wrong_size_ordered` | Wrong Size Ordered |
| `not_as_expected` | Not As Expected |
| `defective_quality` | Defective / Poor Quality |
| `damaged_packaging_or_product` | Damaged Packaging / Product |
| `smell_mold_dirty` | Smell / Mold / Dirty |
| `delivery_late` | Delivery Late |
| `no_longer_needed_changed_mind` | No Longer Needed / Changed Mind |
| `ordered_too_many_or_duplicate` | Ordered Too Many / Duplicate |
| `accidental_unauthorized_purchase` | Accidental / Unauthorized Purchase |
| `event_cancelled_or_plans_changed` | Event Cancelled / Plans Changed |
| `better_price_elsewhere` | Better Price Elsewhere |
| `wrong_item_received` | Wrong Item Received |
| `missing_lids_or_parts` | Missing Lids / Parts |
| `allergy_safety_health` | Allergy / Safety / Health |
| `noise_empty` | Noise / Empty |
| `unmapped` | Unmapped (alert) |

Structured Amazon prefixes (`Incorrect Size|…`, `Delivery Issue|…`, etc.) map via `structured_comment_prefixes`, then refine size direction when the rest of the pipe text says too small/large.

## Cleaning

Before match: HTML unescape (`&#34;`, `&amp;`, …), Unicode NFKC, collapse whitespace, treat `nan` / `n/a` / blank as empty → `noise_empty`.

## Alert behaviour (when report is wired)

```
alerts.enabled: true
alerts.on_unknown_reason: true   -> new Amazon reason code
alerts.on_unknown_comment: true  -> comment hits no alias/prefix/keyword
alerts.collect_unknowns: true    -> keep unique unknowns for YAML updates
```

Suggested log lines:

```
ALERT unknown return reason: <REASON_CODE>
ALERT unknown customer comment: <cleaned text>
```

Unknown reason → group `Unmapped Reason`.  
Unknown comment → group `Unmapped`.

**How to extend:** add the cleaned phrase under the right group’s `aliases`, or add a `keywords` regex. Re-run returns and confirm the alert disappears.

## Coverage note (US FBA sample)

Against ~6.8k unique nonempty `customer-comments` from local FBA returns files, keyword rules classify ~80% into a named group; the rest stay `Unmapped` and should surface as alerts for directory updates.

## Related

- Script: `report_script/amazon_reports/return_database.py` (registered in `report.yaml` as `return_database`)
  - Notebook-style steps: load files → `return_directory.yaml` maps → dates → `esh_sku_cleaning` → pivot → local + Azure
  - Local: `sanity_data/ESH/returns/{GEO}_amazon_return_database.parquet|.csv`
  - Azure: `CONTAINER_NAME_ESH/sanity_data/return_report_database/{same parquet}`
- Notebook: `report_script/amazon_reports/return_database.ipynb` (exploratory mirror)
- Config: `config_manager/return_directory.yaml`
