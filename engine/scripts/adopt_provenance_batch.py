"""Batch-adopt cache provenance in verdict writers — only where it is provably safe.

Context: the 2026-09-17 audit found 0/76 verdict artifacts recorded which cache they ran on, and 74
modules write verdict files with their own loaders (no single hook). tests/test_cache_provenance_
adoption.py enforces that each writer is either adopted or allowlisted.

A blind 74-file edit is how you break 74 runners at once, and a *guarded* injection would let files
claim adoption while recording nothing. So this tool:

  1. finds the FunctionDef that contains the verdict write,
  2. checks whether `data_file` is provably bound in that scope (assignment or parameter) via AST,
  3. injects the real (unguarded) call ONLY where that holds,
  4. leaves everything else alone and reports it.

Idempotent: files already calling inject_cache_provenance are skipped. Compiles every changed file
before finishing so a syntax break is caught immediately.
"""

from __future__ import annotations

import ast
import glob
import py_compile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent  # engine/ (this file lives in engine/scripts/)
WRITE_COMMON = "verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))"

def inject_block(indent: str) -> str:
    """The provenance call, indented to match the line it precedes.

    v1 of this tool hard-coded a 4-space indent and assumed the write line sat at column 0; every
    file it touched came out with an IndentationError because the real line is indented. The compile
    guard caught it, which is why the guard exists.
    """
    return (
        f"{indent}# Provenance (2026-09-17 audit): record which cache produced this verdict.\n"
        f"{indent}from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402\n"
        f"{indent}verdict_doc = _inject_prov(verdict_doc, data_file)\n"
    )


def inject_into(src: str, write_line: str) -> str | None:
    """Insert the provenance call above the verdict write, matching its indentation."""
    for line in src.splitlines(keepends=True):
        if write_line in line:
            indent = line[: len(line) - len(line.lstrip())]
            return src.replace(line, inject_block(indent) + line, 1)
    return None


def data_file_in_scope(src: str, write_line: str) -> bool:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = ast.get_source_segment(src, node) or ""
            if write_line not in body:
                continue
            names = {
                a.targets[0].id
                for a in ast.walk(node)
                if isinstance(a, ast.Assign) and a.targets and isinstance(a.targets[0], ast.Name)
            }
            names |= {x.arg for x in node.args.args}
            return "data_file" in names
    return False


def main() -> int:
    changed, skipped, unsafe = [], [], []
    originals: dict[str, str] = {}
    for f in sorted(glob.glob(str(ENGINE / "backtest" / "run_*.py"))):
        p = Path(f)
        src = p.read_text(encoding="utf-8", errors="replace")
        if "gate_v2_verdicts" not in src or "inject_cache_provenance" in src:
            continue
        if WRITE_COMMON not in src:
            continue
        if not data_file_in_scope(src, WRITE_COMMON):
            unsafe.append(p.name)
            continue
        injected = inject_into(src, WRITE_COMMON)
        if injected is None:
            unsafe.append(p.name)
            continue
        p.write_text(injected, encoding="utf-8")
        changed.append(p.name)
        originals[p.name] = src

    # Compile-check every change and ROLL BACK any file that breaks. v1 aborted on the first
    # failure *after* writing all of them, leaving 39 files broken on disk; a batch tool must not
    # be able to leave the tree worse than it found it.
    rolled_back = []
    for name in list(changed):
        try:
            py_compile.compile(str(ENGINE / "backtest" / name), doraise=True)
        except py_compile.PyCompileError as exc:
            (ENGINE / "backtest" / name).write_text(originals[name], encoding="utf-8")
            rolled_back.append(name)
            changed.remove(name)
            unsafe.append(name)
            print(f"ROLLED BACK {name}: {str(exc).splitlines()[-1][:90]}")

    print(f"adopted (verified in scope + compiles): {len(changed)}")
    print(f"rolled back after compile failure     : {len(rolled_back)}")
    print(f"left alone (no provable scope)        : {len(unsafe)}")
    for n in unsafe:
        print("   ", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())