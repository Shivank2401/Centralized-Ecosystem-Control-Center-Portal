"""
Master CLI for the Inventory Data Pipeline.

Usage:
    python run_pipeline.py
    python run_pipeline.py --client ESH --geo ALL --report ledger,ageing
    python run_pipeline.py --client ESH --geo ALL --stage common

Interactive entry (mode first):
  1) Run a saved sequence
  2) Create / manage sequences  (create, modify, delete)
  3) Classic run (clients → geos → reports)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config_manager.loader import (
    load_clients,
    load_reports,
)
from pipeline_engine.executor import PipelineExecutor
from pipeline_engine.registry import (
    GEO_OPTIONS,
    ConfigRegistry,
    normalize_stage_key,
    slugify_sequence_id,
)


BANNER = """
========================================
    Data & Development Client Pipeline
========================================
"""

_REGISTRY = ConfigRegistry()
_EXECUTOR = PipelineExecutor(registry=_REGISTRY, track_runs=True)


def _normalize_stage_key(stage: str) -> str:
    """Map report.yaml stage labels to report_stages keys (e.g. 'Common' → 'common')."""
    return normalize_stage_key(stage)


def _prompt_choice(title: str, options: List[Tuple[str, str]], allow_all: bool = True) -> List[str]:
    """
    options: list of (code, label). Returns selected codes.
    User may enter index, code, or comma-separated mix; ALL selects everything.
    """
    print(f"\n{title}:")
    for i, (code, label) in enumerate(options, start=1):
        print(f"{i}. {label}")
    if allow_all:
        print(f"{len(options) + 1}. All")

    subject = title.rstrip(":").lower()
    if allow_all:
        print(
            f"(pick one or more: comma-separated indexes/codes, e.g. 1,2 or "
            f"{options[0][0]}"
            f"{',' + options[1][0] if len(options) > 1 else ''} "
            f"| {len(options) + 1} / All = everything)"
        )
    else:
        print("(pick one or more: comma-separated indexes/codes, e.g. 1,3)")

    raw = input(f"\nSelect {subject}: ").strip()
    if not raw:
        raise SystemExit("No selection made.")

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    codes = [c for c, _ in options]
    selected: List[str] = []

    for part in parts:
        upper = part.upper()
        if allow_all and (
            upper == "ALL"
            or part == str(len(options) + 1)
            or upper == "A"
        ):
            return codes
        if part.isdigit():
            idx = int(part)
            if 1 <= idx <= len(options):
                selected.append(codes[idx - 1])
                continue
            if allow_all and idx == len(options) + 1:
                return codes
            raise SystemExit(f"Invalid index: {part}")
        if upper in codes:
            selected.append(upper)
            continue
        matched = [c for c, label in options if label.upper().startswith(upper)]
        if len(matched) == 1:
            selected.append(matched[0])
            continue
        raise SystemExit(f"Invalid choice: {part}")

    seen = set()
    out: List[str] = []
    for c in selected:
        if c not in seen:
            seen.add(c)
            out.append(c)
    if not out:
        raise SystemExit("No valid selection made.")
    return out


def _client_options() -> List[Tuple[str, str]]:
    clients = load_clients()
    return [(c, f"{c} — {cfg.name}") for c, cfg in clients.items()]


def _client_scope(meta: dict) -> Optional[List[str]]:
    """Return uppercase client codes if restricted; None means all clients."""
    raw = meta.get("clients")
    if not raw:
        return None
    return [str(c).strip().upper() for c in raw]


def _matches_clients(meta: dict, selected_clients: Sequence[str]) -> bool:
    scope = _client_scope(meta)
    if scope is None:
        return True
    selected = {c.upper() for c in selected_clients}
    return bool(selected & set(scope))


def _enabled_reports(selected_clients: Optional[Sequence[str]] = None) -> Dict[str, dict]:
    reports_cfg = load_reports().get("reports", {})
    out: Dict[str, dict] = {}
    for code, cfg in reports_cfg.items():
        if not cfg.get("enabled", True):
            continue
        if selected_clients is not None and not _matches_clients(cfg, selected_clients):
            continue
        out[code] = cfg
    return out


def _stage_menu_options(
    selected_clients: Optional[Sequence[str]] = None,
) -> List[Tuple[str, str]]:
    """
    Stages that have at least one enabled report visible for selected clients.
    """
    cfg = load_reports()
    stages_meta = cfg.get("report_stages") or {}
    reports = _enabled_reports(selected_clients)

    used_stages = {
        _normalize_stage_key(meta.get("stage", "common")) for meta in reports.values()
    }

    ordered: List[Tuple[int, str, str]] = []
    for key, meta in stages_meta.items():
        norm_key = _normalize_stage_key(key)
        if norm_key not in used_stages:
            continue
        if selected_clients is not None and not _matches_clients(meta, selected_clients):
            continue
        ordered.append(
            (
                int(meta.get("order", 999)),
                norm_key,
                str(meta.get("label", f"Stage: {norm_key}")),
            )
        )

    known = {k for _, k, _ in ordered}
    for stage_key in sorted(used_stages):
        if stage_key not in known:
            ordered.append((999, stage_key, f"Stage: {stage_key}"))

    ordered.sort(key=lambda item: (item[0], item[1]))
    return [(key, label) for _, key, label in ordered]


def _reports_for_stage(
    stage_key: str,
    selected_clients: Optional[Sequence[str]] = None,
) -> List[Tuple[str, str]]:
    """Enabled reports in a stage (client-filtered), sorted by menu_order."""
    stage_norm = _normalize_stage_key(stage_key)
    items: List[Tuple[int, str, str]] = []
    for code, meta in _enabled_reports(selected_clients).items():
        if _normalize_stage_key(meta.get("stage", "common")) != stage_norm:
            continue
        items.append(
            (
                int(meta.get("menu_order", 999)),
                code,
                str(meta.get("label", code)),
            )
        )
    items.sort(key=lambda item: (item[0], item[2].lower()))
    return [(code, label) for _, code, label in items]


def _report_label(code: str) -> str:
    meta = load_reports().get("reports", {}).get(code) or {}
    return str(meta.get("label", code))


def _expand_letter_tokens(
    tokens: Sequence[str],
    *,
    letter_to_code: Dict[str, str],
    report_opts: Sequence[Tuple[str, str]],
    run_all_letter: str,
    go_back_letter: Optional[str] = None,
) -> Tuple[List[str], bool, bool]:
    """
    Parse letter / digit / range tokens into report codes.

    Returns (picked_codes, run_all, go_back).
    Supports: a | a,c | a-f | 1,2 | all
    """
    picked_codes: List[str] = []
    go_back = False
    run_all = False

    for token in tokens:
        token_norm = token.strip().lower()
        if not token_norm:
            continue

        if token_norm in {"all"}:
            run_all = True
            continue
        if go_back_letter and token_norm in {"back", "go back", go_back_letter}:
            go_back = True
            break
        if token_norm == run_all_letter:
            run_all = True
            continue

        # Letter range: a-f
        if re.fullmatch(r"[a-z]-[a-z]", token_norm):
            start, end = token_norm.split("-")
            if start > end:
                print(f"Invalid range: {token}")
                return [], False, False
            for i in range(ord(start), ord(end) + 1):
                letter = chr(i)
                if letter in letter_to_code:
                    picked_codes.append(letter_to_code[letter])
            continue

        if token_norm in letter_to_code:
            picked_codes.append(letter_to_code[token_norm])
            continue

        if token_norm.isdigit():
            n = int(token_norm)
            if 1 <= n <= len(report_opts):
                picked_codes.append(report_opts[n - 1][0])
                continue
            if n == len(report_opts) + 1:
                run_all = True
                continue
            if go_back_letter and n == len(report_opts) + 2:
                go_back = True
                break

        upper = token_norm.upper()
        matched = [
            code
            for code, label in report_opts
            if code.upper() == upper or label.upper().startswith(upper)
        ]
        if len(matched) == 1:
            picked_codes.append(matched[0])
            continue

        print(f"Invalid choice: {token}")
        return [], False, False

    return picked_codes, run_all, go_back


def prompt_clients() -> List[str]:
    return _prompt_choice("Clients", _client_options(), allow_all=True)


def prompt_geographies() -> List[str]:
    return _prompt_choice("Geographies", GEO_OPTIONS, allow_all=True)


def prompt_reports(selected_clients: Sequence[str]) -> List[str]:
    """
    Two-level menu (filtered by selected clients):
      Reports (stages) → reports within that stage
      with Run All + Go back to stage list.
    """
    stage_opts = _stage_menu_options(selected_clients)
    if not stage_opts:
        raise SystemExit(
            "No enabled reports / stages for selected clients "
            f"{list(selected_clients)} in report.yaml."
        )

    while True:
        print("\nReports:")
        for i, (stage_key, label) in enumerate(stage_opts, start=1):
            print(f"{i}. {label}")

        raw = input("\nSelect stage: ").strip()
        if not raw:
            raise SystemExit("No stage selected.")

        stage_key: Optional[str] = None
        stage_idx = 0
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(stage_opts):
                stage_key = stage_opts[idx - 1][0]
                stage_idx = idx
        else:
            for i, (key, label) in enumerate(stage_opts, start=1):
                if raw.lower() == key.lower() or raw.lower() in label.lower():
                    stage_key = key
                    stage_idx = i
                    break

        if stage_key is None:
            print(f"Invalid stage choice: {raw}")
            continue

        report_opts = _reports_for_stage(stage_key, selected_clients)
        if not report_opts:
            print(f"No enabled reports under stage '{stage_key}' for selected clients.")
            continue

        while True:
            stage_label = next(lbl for k, lbl in stage_opts if k == stage_key)
            print(f"\n{stage_label}")
            report_letters = [
                (chr(ord("a") + j), code, label)
                for j, (code, label) in enumerate(report_opts)
            ]
            letter_to_code = {letter: code for letter, code, _ in report_letters}
            for letter, _code, label in report_letters:
                print(f"{letter}. {label}")
            run_all_letter = chr(ord("a") + len(report_opts))
            go_back_letter = chr(ord("a") + len(report_opts) + 1)
            print(f"{run_all_letter}. Run All")
            print(f"{go_back_letter}. Go back to select stage")

            sub = input(
                f"\nSelect report(s) under stage {stage_idx} "
                f"(e.g. a or a,c or a-f or {run_all_letter}): "
            ).strip()
            if not sub:
                print("No selection made.")
                continue

            tokens = [t.strip() for t in sub.split(",") if t.strip()]
            # Accept legacy "1.2" by mapping right-hand number → letter
            normalized_tokens: List[str] = []
            for token in tokens:
                token_norm = token.strip().lower()
                if "." in token_norm:
                    left, right = token_norm.split(".", 1)
                    if left.isdigit() and int(left) == stage_idx and right.isdigit():
                        n = int(right)
                        token_norm = chr(ord("a") + n - 1) if n >= 1 else token_norm
                    elif right.isdigit() and not left.isdigit():
                        n = int(right)
                        token_norm = chr(ord("a") + n - 1) if n >= 1 else token_norm
                normalized_tokens.append(token_norm)

            picked_codes, run_all, go_back = _expand_letter_tokens(
                normalized_tokens,
                letter_to_code=letter_to_code,
                report_opts=report_opts,
                run_all_letter=run_all_letter,
                go_back_letter=go_back_letter,
            )

            if go_back:
                break

            if run_all:
                return [code for code, _ in report_opts]

            if not picked_codes:
                continue

            seen = set()
            selected: List[str] = []
            for code in picked_codes:
                if code not in seen:
                    seen.add(code)
                    selected.append(code)
            return selected


def _print_sequence(sequence: Sequence[str]) -> None:
    if not sequence:
        print("Current sequence: (empty)")
        return
    print(f"Current sequence ({len(sequence)} steps):")
    for i, code in enumerate(sequence, start=1):
        print(f"  {i}. {_report_label(code)}  [{code}]")
    print("  Order → " + " → ".join(_report_label(c) for c in sequence))


def _parse_stage_report_shortcut(
    raw: str,
    stage_opts: Sequence[Tuple[str, str]],
    selected_clients: Sequence[str],
) -> Optional[List[str]]:
    """
    Quick syntax: <stageIndex>-<letters>

      2-a,b,c     → stage 2 reports a,b,c
      1-a-f       → stage 1 reports a through f
      5-a         → stage 5 report a
    """
    text = raw.strip().lower()
    m = re.fullmatch(r"(\d+)\s*[-:]\s*(.+)", text)
    if not m:
        return None

    stage_idx = int(m.group(1))
    if not (1 <= stage_idx <= len(stage_opts)):
        print(f"Invalid stage index in shortcut: {stage_idx}")
        return None

    stage_key = stage_opts[stage_idx - 1][0]
    report_opts = _reports_for_stage(stage_key, selected_clients)
    if not report_opts:
        print(f"No reports under stage {stage_idx}.")
        return None

    letter_to_code = {
        chr(ord("a") + j): code for j, (code, _label) in enumerate(report_opts)
    }
    run_all_letter = chr(ord("a") + len(report_opts))
    right = m.group(2).strip()
    tokens = [t.strip() for t in right.split(",") if t.strip()]
    picked, run_all, _go_back = _expand_letter_tokens(
        tokens,
        letter_to_code=letter_to_code,
        report_opts=report_opts,
        run_all_letter=run_all_letter,
        go_back_letter=None,
    )
    if run_all:
        return [code for code, _ in report_opts]
    return picked or None


def prompt_report_sequence(
    selected_clients: Sequence[str],
    *,
    initial: Optional[Sequence[str]] = None,
    cancel_returns_none: bool = False,
) -> Optional[List[str]]:
    """
    Build an ordered multi-stage report queue.

    User repeatedly picks a stage, then report letters, appending to the sequence.
    Supports shortcuts like: 2-a,b,c   then later   5-a

    If ``initial`` is set, the builder starts with those reports (modify flow).
    If ``cancel_returns_none`` is True, X/Cancel returns None instead of exiting.
    """
    stage_opts = _stage_menu_options(selected_clients)
    if not stage_opts:
        raise SystemExit(
            "No enabled reports / stages for selected clients "
            f"{list(selected_clients)} in report.yaml."
        )

    sequence: List[str] = [str(c).strip().lower() for c in (initial or []) if str(c).strip()]

    print(
        """
========================================
  Custom report sequence builder
========================================
Add reports from any stage, in the order you want them to run.
Examples:
  - pick stage 1, then a,b,c
  - or shortcut: 1-a,b,c
  - then add stage 5 report a via 5-a
""".rstrip()
    )
    if sequence:
        print("(Starting from the existing sequence — add more, clear, or finish with D.)")

    while True:
        print()
        _print_sequence(sequence)
        print("\nStages:")
        for i, (_key, label) in enumerate(stage_opts, start=1):
            print(f"{i}. {label}")
        print("D. Done — finish this sequence")
        print("C. Clear sequence")
        print("X. Cancel / exit builder")

        raw = input(
            "\nSelect stage #, shortcut (e.g. 2-a,b,c), or D/C/X: "
        ).strip()
        if not raw:
            print("No selection made.")
            continue

        upper = raw.strip().upper()
        if upper in {"D", "DONE"}:
            if not sequence:
                print("Sequence is empty — add at least one report first.")
                continue
            return sequence
        if upper in {"C", "CLEAR"}:
            sequence = []
            print("Sequence cleared.")
            continue
        if upper in {"X", "CANCEL", "Q"}:
            if cancel_returns_none:
                print("Builder cancelled — no report changes applied.")
                return None
            raise SystemExit("Sequence builder cancelled.")

        shortcut_codes = _parse_stage_report_shortcut(raw, stage_opts, selected_clients)
        if shortcut_codes is not None:
            for code in shortcut_codes:
                sequence.append(code)
            print(
                "Added: "
                + ", ".join(_report_label(c) for c in shortcut_codes)
            )
            continue

        stage_key: Optional[str] = None
        stage_idx = 0
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(stage_opts):
                stage_key = stage_opts[idx - 1][0]
                stage_idx = idx
        else:
            for i, (key, label) in enumerate(stage_opts, start=1):
                if raw.lower() == key.lower() or raw.lower() in label.lower():
                    stage_key = key
                    stage_idx = i
                    break

        if stage_key is None:
            print(f"Invalid choice: {raw}")
            continue

        report_opts = _reports_for_stage(stage_key, selected_clients)
        if not report_opts:
            print(f"No enabled reports under stage '{stage_key}'.")
            continue

        stage_label = next(lbl for k, lbl in stage_opts if k == stage_key)
        print(f"\n{stage_label}  (add to sequence)")
        report_letters = [
            (chr(ord("a") + j), code, label)
            for j, (code, label) in enumerate(report_opts)
        ]
        letter_to_code = {letter: code for letter, code, _ in report_letters}
        for letter, _code, label in report_letters:
            print(f"{letter}. {label}")
        run_all_letter = chr(ord("a") + len(report_opts))
        go_back_letter = chr(ord("a") + len(report_opts) + 1)
        print(f"{run_all_letter}. Add ALL from this stage")
        print(f"{go_back_letter}. Back (don't add)")

        sub = input(
            f"\nReports to add from stage {stage_idx} "
            f"(e.g. a,b,c or a-f or {run_all_letter}): "
        ).strip()
        if not sub:
            print("Nothing added.")
            continue

        tokens = [t.strip() for t in sub.split(",") if t.strip()]
        picked_codes, run_all, go_back = _expand_letter_tokens(
            tokens,
            letter_to_code=letter_to_code,
            report_opts=report_opts,
            run_all_letter=run_all_letter,
            go_back_letter=go_back_letter,
        )
        if go_back:
            continue
        if run_all:
            picked_codes = [code for code, _ in report_opts]
        if not picked_codes:
            continue

        for code in picked_codes:
            sequence.append(code)
        print("Added: " + ", ".join(_report_label(c) for c in picked_codes))

# ---------------------------------------------------------------------------
# Saved sequences (config_manager/run_sequences.yaml)
# ---------------------------------------------------------------------------

def _slugify_sequence_id(name: str) -> str:
    return slugify_sequence_id(name)


def load_saved_sequences() -> Dict[str, dict]:
    return _REGISTRY.load_sequences()


def save_saved_sequences(sequences: Dict[str, dict]) -> None:
    path = _REGISTRY.save_sequences(sequences)
    print(f"Saved sequences → {path}")


def _normalize_saved_selection(
    clients: Sequence[str],
    geos: Sequence[str],
) -> Tuple[List[str], List[str]]:
    """Expand ALL for clients/geos into concrete lists."""
    clients_map = load_clients()
    client_list = [c.strip().upper() for c in clients]
    if len(client_list) == 1 and client_list[0] == "ALL":
        client_list = list(clients_map.keys())

    all_geos = [code for code, _ in GEO_OPTIONS]
    geo_list = [g.strip().upper() for g in geos]
    if len(geo_list) == 1 and geo_list[0] == "ALL":
        geo_list = all_geos
    return client_list, geo_list


def _sequence_summary(seq_id: str, meta: dict) -> str:
    label = str(meta.get("label") or seq_id)
    clients = meta.get("clients") or []
    geos = meta.get("geos") or []
    reports = meta.get("reports") or []
    return (
        f"{label}  | clients={','.join(map(str, clients))} "
        f"| geos={','.join(map(str, geos))} "
        f"| steps={len(reports)}"
    )


def prompt_save_sequence(
    clients: Sequence[str],
    geos: Sequence[str],
    reports: Sequence[str],
) -> Optional[str]:
    """Ask for a name and persist the sequence. Returns sequence id."""
    print("\nSave this as a reusable sequence?")
    name = input("Sequence name (Enter=skip save): ").strip()
    if not name:
        print("Not saved.")
        return None

    seq_id = _slugify_sequence_id(name)
    sequences = load_saved_sequences()
    if seq_id in sequences:
        overwrite = input(
            f"Sequence '{seq_id}' already exists. Overwrite? [y/N]: "
        ).strip().lower()
        if overwrite not in {"y", "yes"}:
            print("Save cancelled.")
            return None

    sequences[seq_id] = {
        "label": name,
        "clients": list(clients),
        "geos": list(geos),
        "reports": list(reports),
    }
    save_saved_sequences(sequences)
    print(f"Sequence saved as '{seq_id}'.")
    return seq_id


def prompt_pick_saved_sequence() -> Optional[Tuple[str, dict]]:
    sequences = load_saved_sequences()
    if not sequences:
        print("\nNo saved sequences yet. Create one first (option 2).")
        return None

    items = sorted(
        sequences.items(),
        key=lambda kv: str(kv[1].get("label") or kv[0]).lower(),
    )
    print("\nSaved sequences:")
    for i, (seq_id, meta) in enumerate(items, start=1):
        print(f"{i}. {_sequence_summary(seq_id, meta)}")
    print(f"{len(items) + 1}. Back")

    raw = input("\nSelect sequence: ").strip()
    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw)
        if idx == len(items) + 1:
            return None
        if 1 <= idx <= len(items):
            return items[idx - 1]
    # match by id / label
    for seq_id, meta in items:
        label = str(meta.get("label") or "")
        if raw.lower() in {seq_id.lower(), label.lower()}:
            return seq_id, meta
    print(f"Invalid choice: {raw}")
    return None


def prompt_modify_sequence() -> Optional[Tuple[List[str], List[str], List[str]]]:
    """
    Edit an existing saved sequence (add scripts, clients, geos, rename).

    Returns selection to run immediately after save, or None to stay in manage menu.
    """
    picked = prompt_pick_saved_sequence()
    if not picked:
        return None

    seq_id, meta = picked
    clients = [str(c).upper() for c in (meta.get("clients") or [])]
    geos = [str(g).upper() for g in (meta.get("geos") or [])]
    reports = [str(r).strip().lower() for r in (meta.get("reports") or [])]
    label = str(meta.get("label") or seq_id)
    dirty = False

    while True:
        print(f"\n--- Modify sequence: {label} [{seq_id}] ---")
        print(f"Clients: {', '.join(clients) if clients else '(none)'}")
        print(f"Geos:    {', '.join(geos) if geos else '(none)'}")
        _print_sequence(reports)
        print(
            """
1. Add / edit reports
2. Change clients
3. Change geographies
4. Rename label
5. Save changes
6. Cancel (discard unsaved changes)
""".rstrip()
        )
        raw = input("\nSelect [1-6]: ").strip() or "6"

        if raw in {"6", "c", "C", "cancel", "x", "X"}:
            if dirty:
                print("Changes discarded.")
            return None

        if raw == "1":
            if not clients:
                print("Set clients first (option 2).")
                continue
            updated = prompt_report_sequence(
                clients,
                initial=reports,
                cancel_returns_none=True,
            )
            if updated is not None:
                reports = updated
                dirty = True
            continue

        if raw == "2":
            clients = prompt_clients()
            dirty = True
            continue

        if raw == "3":
            geos = prompt_geographies()
            dirty = True
            continue

        if raw == "4":
            new_label = input(f"New label [{label}]: ").strip()
            if new_label:
                label = new_label
                dirty = True
            else:
                print("Label unchanged.")
            continue

        if raw == "5":
            if not clients or not geos or not reports:
                print("Sequence incomplete — need clients, geos, and at least one report.")
                continue
            sequences = load_saved_sequences()
            sequences[seq_id] = {
                "label": label,
                "clients": list(clients),
                "geos": list(geos),
                "reports": list(reports),
            }
            save_saved_sequences(sequences)
            print(f"Updated sequence '{seq_id}' saved.")
            dirty = False

            run_now = input("\nRun this sequence now? [y/N]: ").strip().lower()
            if run_now in {"y", "yes"}:
                clients, geos = _normalize_saved_selection(clients, geos)
                return list(clients), list(geos), list(reports)
            return None

        print(f"Invalid choice: {raw}")


def prompt_manage_sequences() -> Optional[Tuple[List[str], List[str], List[str]]]:
    """
    Create / modify / delete saved sequences.

    Returns a selection to run immediately, or None to return to top menu.
    """
    while True:
        sequences = load_saved_sequences()
        print(
            """
Manage sequences:
1. Create new sequence
2. Modify a saved sequence
3. Delete a saved sequence
4. Back to main menu
""".rstrip()
        )
        if sequences:
            print("Currently saved:")
            for seq_id, meta in sorted(sequences.items()):
                print(f"  - {_sequence_summary(seq_id, meta)}")
        else:
            print("(none saved yet)")

        raw = input("\nSelect [1-4]: ").strip() or "4"
        if raw in {"4", "b", "B", "back"}:
            return None

        if raw == "3":
            picked = prompt_pick_saved_sequence()
            if not picked:
                continue
            seq_id, meta = picked
            confirm = input(
                f"Delete '{meta.get('label', seq_id)}'? [y/N]: "
            ).strip().lower()
            if confirm in {"y", "yes"}:
                sequences = load_saved_sequences()
                sequences.pop(seq_id, None)
                save_saved_sequences(sequences)
                print(f"Deleted '{seq_id}'.")
            continue

        if raw == "2":
            if not sequences:
                print("No saved sequences yet. Create one first (option 1).")
                continue
            selection = prompt_modify_sequence()
            if selection is not None:
                return selection
            continue

        if raw != "1":
            print(f"Invalid choice: {raw}")
            continue

        # Create new sequence: clients → geos → report sequence builder → save
        print("\n--- Create sequence ---")
        clients = prompt_clients()
        geos = prompt_geographies()
        reports = prompt_report_sequence(clients, cancel_returns_none=True)
        if not reports:
            print("Create cancelled.")
            continue
        _print_sequence(reports)
        prompt_save_sequence(clients, geos, reports)

        run_now = input(
            "\nRun this sequence now? [y/N]: "
        ).strip().lower()
        if run_now in {"y", "yes"}:
            return list(clients), list(geos), list(reports)
        # stay in manage menu


def prompt_run_saved_sequence() -> Optional[Tuple[List[str], List[str], List[str]]]:
    picked = prompt_pick_saved_sequence()
    if not picked:
        return None
    seq_id, meta = picked
    clients = [str(c).upper() for c in (meta.get("clients") or [])]
    geos = [str(g).upper() for g in (meta.get("geos") or [])]
    reports = [str(r).strip().lower() for r in (meta.get("reports") or [])]
    if not clients or not geos or not reports:
        print(f"Sequence '{seq_id}' is incomplete (need clients, geos, reports).")
        return None
    clients, geos = _normalize_saved_selection(clients, geos)
    print(f"\nLoaded sequence: {_sequence_summary(seq_id, meta)}")
    _print_sequence(reports)
    return clients, geos, reports


def interactive_classic_menu() -> Tuple[List[str], List[str], List[str]]:
    """Previous flow: clients → geos → single-stage report pick."""
    print("\n--- Classic run ---")
    clients = prompt_clients()
    geos = prompt_geographies()
    reports = prompt_reports(clients)
    return clients, geos, reports


def prompt_top_mode() -> str:
    """
    First screen after banner.

    Returns: run_saved | create | classic | exit
    """
    sequences = load_saved_sequences()
    saved_count = len(sequences)
    print(
        f"""
How do you want to run?
1. Run a saved sequence{"  (" + str(saved_count) + " available)" if saved_count else "  (none yet — create one first)"}
2. Create / manage sequences
3. Classic run (clients → geographies → reports)
4. Exit
""".rstrip()
    )
    raw = input("\nSelect [1-4] (Enter=3): ").strip() or "3"
    if raw in {"1"}:
        return "run_saved"
    if raw in {"2"}:
        return "create"
    if raw in {"3"}:
        return "classic"
    if raw in {"4", "q", "Q", "exit", "EXIT"}:
        return "exit"
    print(f"Invalid choice '{raw}' — using classic run.")
    return "classic"


def interactive_menu() -> Optional[Tuple[List[str], List[str], List[str]]]:
    """
    Mode-first entry. Returns selection to run, or None if user exits.
    """
    print(BANNER)
    while True:
        mode = prompt_top_mode()
        if mode == "exit":
            return None
        if mode == "run_saved":
            selection = prompt_run_saved_sequence()
            if selection is not None:
                return selection
            continue
        if mode == "create":
            selection = prompt_manage_sequences()
            if selection is not None:
                return selection
            continue
        # classic
        return interactive_classic_menu()


def _format_selection(
    clients: Sequence[str],
    geos: Sequence[str],
    reports: Sequence[str],
) -> str:
    return (
        f"clients={','.join(clients)} | "
        f"geos={','.join(geos)} | "
        f"sequence({len(reports)})={' → '.join(reports)}"
    )


def prompt_next_action(
    clients: List[str],
    geos: List[str],
    reports: List[str],
) -> Tuple[str, List[str], List[str], List[str]]:
    """
    After a run, ask what to do next.

    Returns (action, clients, geos, reports) where action is:
      run   — execute with returned selection
      exit  — leave the pipeline
    """
    print("\n" + "-" * 40)
    print(f"Current selection: {_format_selection(clients, geos, reports)}")
    _print_sequence(reports)
    print(
        """
What next?
1. Rerun last selection
2. Classic: change reports only (same clients + geos)
3. Classic: change geographies (keep clients)
4. Save current selection as a sequence
5. Back to main menu (saved sequences / create / classic)
6. Exit
""".rstrip()
    )

    raw = input("\nSelect next action [1-6] (Enter=Exit): ").strip()
    if not raw or raw in {"6", "q", "Q", "exit", "EXIT"}:
        return "exit", clients, geos, reports

    if raw == "1":
        return "run", clients, geos, reports

    if raw == "2":
        new_reports = prompt_reports(clients)
        return "run", clients, geos, new_reports

    if raw == "3":
        new_geos = prompt_geographies()
        new_reports = prompt_reports(clients)
        return "run", clients, new_geos, new_reports

    if raw == "4":
        prompt_save_sequence(clients, geos, reports)
        return "run", clients, geos, reports

    if raw == "5":
        selection = interactive_menu()
        if selection is None:
            return "exit", clients, geos, reports
        return "run", selection[0], selection[1], selection[2]

    print(f"Invalid choice: {raw}. Exiting.")
    return "exit", clients, geos, reports


def _import_and_run(module_path: str, **kwargs) -> None:
    """Backward-compatible helper; prefer PipelineExecutor."""
    _EXECUTOR.import_and_run(module_path, **kwargs)


def run_reports(
    clients: Sequence[str],
    geos: Sequence[str],
    reports: Sequence[str],
) -> None:
    """
    Run reports in the given sequence order.

    Delegates to pipeline_engine.PipelineExecutor (shared with FastAPI).
    """
    _REGISTRY.refresh()
    _EXECUTOR.run_reports(clients, geos, reports)


def execute(
    clients: Sequence[str],
    geos: Sequence[str],
    reports: Sequence[str],
) -> None:
    """
    Run a pipeline selection via the shared PipelineExecutor.

    CLI and portal both call this execution path.
    """
    _REGISTRY.refresh()
    _print_sequence(reports)
    _EXECUTOR.execute(clients, geos, reports, source="cli")


def interactive_session(
    clients: List[str],
    geos: List[str],
    reports: List[str],
) -> None:
    """Run once, then loop on the next-action menu until Exit."""
    while True:
        execute(clients, geos, reports)
        action, clients, geos, reports = prompt_next_action(clients, geos, reports)
        if action == "exit":
            print("\nExiting pipeline. Bye.")
            return


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Inventory Data Pipeline")
    p.add_argument("--client", help="ESH, KNC, or ALL / comma-separated")
    p.add_argument("--geo", help="US,CA,... or ALL")
    p.add_argument("--stage", help="Stage key: saving_reports, common, … (runs all reports in stage)")
    p.add_argument("--report", help="manage_fba,reserved,... or ALL (comma-separated = run order)")
    p.add_argument("--sequence", help="Run a saved sequence id from run_sequences.yaml")
    p.add_argument("--interactive", action="store_true", help="Force interactive menu")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    use_interactive = args.interactive or not any(
        [args.client, args.geo, args.report, args.stage, args.sequence]
    )

    if use_interactive:
        selection = interactive_menu()
        if selection is None:
            print("\nExiting pipeline. Bye.")
            return
        clients, geos, reports = selection
        interactive_session(clients, geos, reports)
        return

    if args.sequence:
        sequences = load_saved_sequences()
        seq_id = _slugify_sequence_id(args.sequence)
        meta = sequences.get(args.sequence) or sequences.get(seq_id)
        if not meta:
            raise SystemExit(
                f"Unknown sequence '{args.sequence}'. "
                f"Known: {list(sequences.keys()) or '(none)'}"
            )
        clients = [str(c).upper() for c in (meta.get("clients") or [])]
        geos = [str(g).upper() for g in (meta.get("geos") or [])]
        reports = [str(r).strip().lower() for r in (meta.get("reports") or [])]
        clients, geos = _normalize_saved_selection(clients, geos)
        execute(clients, geos, reports)
        return

    clients_map = load_clients()
    client_raw = args.client or "ALL"
    if client_raw.upper() == "ALL":
        clients = list(clients_map.keys())
    else:
        clients = [c.strip().upper() for c in client_raw.split(",")]

    geo_raw = (args.geo or "ALL").upper()
    all_geos = [code for code, _ in GEO_OPTIONS]
    geos = all_geos if geo_raw == "ALL" else [g.strip().upper() for g in geo_raw.split(",")]

    reports_cfg = load_reports().get("reports", {})
    if args.stage and not args.report:
        stage_key = args.stage.strip().lower()
        reports = [code for code, _ in _reports_for_stage(stage_key, clients)]
        if not reports:
            raise SystemExit(f"No enabled reports for stage '{stage_key}' / clients {clients}.")
    else:
        report_keys = list(reports_cfg.keys())
        report_raw = args.report or "ALL"
        if report_raw.upper() == "ALL":
            reports = report_keys
        else:
            reports = [r.strip().lower() for r in report_raw.split(",") if r.strip()]

    # One-shot CLI flags: run once and exit (no post-run menu).
    execute(clients, geos, reports)


if __name__ == "__main__":
    main()
