"""Static AST validation for uploaded report scripts (never executes user code)."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.py$")

# Calls that should block registration (static heuristic only).
_BLOCKED_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "breakpoint",
}

_BLOCKED_ATTR_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "call"),
    ("subprocess", "run"),
    ("subprocess", "Popen"),
    ("commands", "getoutput"),
}


@dataclass
class AstValidationResult:
    ok: bool
    filename: str
    module_stem: str
    syntax_ok: bool
    has_run: bool
    run_params: List[str] = field(default_factory=list)
    accepts_client: bool = False
    accepts_geos: bool = False
    imports: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "filename": self.filename,
            "module_stem": self.module_stem,
            "syntax_ok": self.syntax_ok,
            "has_run": self.has_run,
            "run_params": self.run_params,
            "accepts_client": self.accepts_client,
            "accepts_geos": self.accepts_geos,
            "imports": self.imports,
            "functions": self.functions,
            "classes": self.classes,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_filename(filename: str) -> Optional[str]:
    name = Path(filename).name
    if not name or name != filename.replace("\\", "/").split("/")[-1]:
        return "Filename must not include path separators"
    if not _SAFE_NAME.match(name):
        return "Filename must be a simple Python module name (letters, digits, underscore) ending in .py"
    if name.startswith("_"):
        return "Filename must not start with underscore"
    return None


def analyze_source(source: str, *, filename: str) -> AstValidationResult:
    stem = Path(filename).stem
    result = AstValidationResult(
        ok=False,
        filename=filename,
        module_stem=stem,
        syntax_ok=False,
        has_run=False,
    )

    name_err = validate_filename(filename)
    if name_err:
        result.errors.append(name_err)
        return result

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        result.errors.append(f"Syntax error: {exc.msg} (line {exc.lineno})")
        return result

    result.syntax_ok = True
    imports: Set[str] = set()
    functions: List[str] = []
    classes: List[str] = []
    blocked: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.col_offset == 0:
                functions.append(node.name)
                if node.name == "run":
                    result.has_run = True
                    params = _function_params(node)
                    result.run_params = params
                    result.accepts_client = "client" in params or _has_varkw(node)
                    result.accepts_geos = "geos" in params or _has_varkw(node)
                    if isinstance(node, ast.AsyncFunctionDef):
                        result.errors.append("run() must be a synchronous function, not async")
        elif isinstance(node, ast.ClassDef) and node.col_offset == 0:
            classes.append(node.name)
        elif isinstance(node, ast.Call):
            hit = _blocked_call(node)
            if hit:
                blocked.append(hit)

    result.imports = sorted(imports)
    result.functions = functions
    result.classes = classes

    if blocked:
        # Soft-block: warn strongly; pipeline reports often use subprocess legitimately.
        # For uploads we treat os.system / eval / exec as hard errors; subprocess as warning.
        hard = [b for b in blocked if b.split(".")[-1] in _BLOCKED_CALLS or b.startswith("os.")]
        soft = [b for b in blocked if b not in hard]
        for b in hard:
            result.errors.append(f"Blocked call detected: {b}")
        for b in soft:
            result.warnings.append(f"Potentially sensitive call: {b} (allowed but review carefully)")

    if not result.has_run:
        result.errors.append("Missing required top-level function: def run(...)")
    else:
        if not result.accepts_client:
            result.errors.append("run() must accept a 'client' parameter or **kwargs")
        if not result.accepts_geos:
            result.warnings.append("run() does not list a 'geos' parameter (ok if using **kwargs)")

    result.ok = result.syntax_ok and result.has_run and result.accepts_client and not result.errors
    # Recompute: errors from blocked calls may have been added after has_run checks
    if result.errors:
        result.ok = False
    elif result.syntax_ok and result.has_run and result.accepts_client:
        result.ok = True
    return result


def analyze_file(path: Path) -> AstValidationResult:
    source = path.read_text(encoding="utf-8")
    return analyze_source(source, filename=path.name)


def _function_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> List[str]:
    args = node.args
    names: List[str] = []
    for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
        names.append(a.arg)
    if args.vararg:
        names.append(f"*{args.vararg.arg}")
    if args.kwarg:
        names.append(f"**{args.kwarg.arg}")
    return names


def _has_varkw(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return node.args.kwarg is not None


def _blocked_call(node: ast.Call) -> Optional[str]:
    func = node.func
    if isinstance(func, ast.Name) and func.id in _BLOCKED_CALLS:
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        pair = (func.value.id, func.attr)
        if pair in _BLOCKED_ATTR_CALLS:
            return f"{pair[0]}.{pair[1]}"
        if func.value.id == "os" and func.attr == "system":
            return "os.system"
    return None
