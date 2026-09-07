# Portal (Inventory Ecosystem Portal)

## Status
**Phase 6 complete** (2026-09-07): Diagnostics enhanced; Outputs / Logs (client + report) / COGS / Pincode explorers.

**Repo root:** `C:\Developer data\Centralized Ecosystem Portal\`

## Run locally
```bash
python portal.py
cd frontend && npm run dev
```

## Phase 6
```text
Data → Outputs   sanity_data/{CLIENT}/{output_subdir}/  (path links, preview, download)
Data → Logs      sanity_data/{CLIENT}/logs/{report}/    (latest.log + history)
Data → COGS      cogs/{client}/
Data → Pincode   PINCODE_DATA_DIR / project pincode/
Developer → Diagnostics  (+ data roots, sanity writable, cogs/pincode)
```

APIs under `/api/explore/*` — path traversal blocked; parquet preview is first N rows only.

## Next
Phase 7 — Documentation synchronization.
