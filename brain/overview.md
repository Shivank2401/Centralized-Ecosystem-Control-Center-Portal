# Overview

## Clients
| Code | Name | Geos |
|------|------|------|
| ESH | Ecosoul Home | US, UK, DE, AE, CA, IN |
| KNC | Kinetica | UK, DE, AE |

## Pipeline stages
1. **saving_reports** — archive raw downloads datewise
2. **common** — standard dataset (Manage FBA, Reserved, Ageing, Ledger, Order, Inventory Database)
3. **requirement** — instock, total inventory, city/state orders, etc.
4. **sequence** — run 1 → 2 → 3

## Data flow
CONFIGURATION (.env + YAML) → COMMON PIPELINE (SKU/COGS strategy) → STANDARD DATASET → REQUIREMENT REPORTS

Outputs land under `sanity_data/{CLIENT}/{report}/`.
