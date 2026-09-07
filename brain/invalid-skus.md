# Invalid SKUs (DEFAULT_INVALID_SKUS)

Per-client list of SKUs dropped during SKU cleaning.

## Storage
`config_manager/invalid_skus.json` — keys `ESH`, `KNC`, `EMM` (lists of upper-cased SKUs).

Created/seeded on first load from former hard-coded sets via `config_manager/invalid_skus_store.py`.

## Manager
`report_script/want_to_update/invalid_skus.py`

- Interactive: View / Add / Exit — pick client, paste many SKUs (newlines, spaces, or commas).
- CLI:
  ```bash
  python report_script/want_to_update/invalid_skus.py
  python report_script/want_to_update/invalid_skus.py --view --client ESH
  python report_script/want_to_update/invalid_skus.py --add "BFW-AV,BFW-MT" --client ESH
  ```

Pipeline: Stage **want_to_update** → Invalid SKUs.

## Consumers
- `config_manager/esh_sku_cleaning.py` → `get_invalid_skus("ESH")`
- `config_manager/knc_sku_cleaning.py` → `get_invalid_skus("KNC")`

Do not edit the lists in those Python files; update the JSON via the manager script.
