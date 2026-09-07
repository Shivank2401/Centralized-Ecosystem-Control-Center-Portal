# Project location

**Canonical project root (this copy):**

```text
C:\Developer data\Centralized Ecosystem Portal
```

This is a working copy of the inventory ETL repo (formerly developed under `client_pipeline`).

- Code resolves the project root via `Path(__file__)` — no hardcoded `client_pipeline` paths in Python.
- Machine-specific paths live only in `.env` (e.g. `PINCODE_DATA_DIR`).
- Docs use the folder name **Centralized Ecosystem Portal** in tree diagrams.

Do not point local config at `C:\Developer data\client_pipeline` unless you intentionally still use that tree.
