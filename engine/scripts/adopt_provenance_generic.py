"""Third-pass provenance adoption: generalize the read anchor.

Batches 1 and 2 keyed on exact anchors (`data_file`, and the one literal write call). The remaining
real verdict writers differ only in *variable names* — `df = pd.read_csv(data_file | path | cand)` —
so this pass matches them by pattern instead of by name.

Only files with BOTH a frame read and a JSON verdict write are touched, `df` must be provably bound
at the write site (AST), injected lines match their anchor's indentation, and every change is
compiled with automatic rollback. Same three safeguards as before, because a hard-coded indent once
broke 39 files in one go.

Deliberately NOT touched: the ~14 remaining ledger entries that are analysis/report tools
(`scoreboard.py`, `regime_report.py`, `audit_verdict_artifacts.py`, `verdict_lifecycle.py`, ...).
They reference the verdict store but do not *produce* verdict artifacts, so counting them as verdict
writers inflates the backlog metric. Reclassifying them is a separate, deliberate change to the
guard's definition — not something to slip in here.
"""

from __future__ import annotations

import ast
import glob
import py_compile
import re
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent  # engine/
READ_RE = re.compile(r"^(\s*)df = pd\.read_csv\((\w+)\)")
WRITE_RE = re.compile(r"^(\s*)([\w.]+)\.write_text\(json\.dumps\((\w+)")
ADOPTED_MARKERS = ("cache_provenance", "inject_cache_provenance")


def _loader_block(indent: str, cache_var: str) -> str:
    return (
        f"{indent}# Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).\n"
        f"{indent}from backtest._gate_v2_helpers import cache_provenance as _cp  # noqa: E402\n"
        f'{indent}df.attrs["cache_provenance"] = _cp({cache_var})\n'
    )


def _write_block(indent: str, payload_var: str) -> str:
    """Payload name differs per file (`doc`, `data`, `metrics`, `out`, `verdict`, ...) — capture it
    rather than assuming `verdict_doc`, or every file but one gets skipped."""
    return (
        f"{indent}# Record the provenance carried on the frame (see loader).\n"
        f"{indent}from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402\n"
        f"{indent}{payload_var} = _ip({payload_var}, df=df)\n"
    )


def _df_bound_at_write_site(src: str) -> bool:
    """Is `df` bound in the function that performs the verdict write?"""
    tree = ast.parse(src)
    body_all = src
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(src, node) or ""
            if not any(WRITE_RE.match(ln) for ln in seg.splitlines()):
                continue
            names = {
                a.targets[0].id
                for a in ast.walk(node)
                if isinstance(a, ast.Assign) and a.targets and isinstance(a.targets[0], ast.Name)
            }
            names |= {x.arg for x in node.args.args}
            return "df" in names
    return False


def main() -> int:
    adopted, rolled, skipped = [], [], []
    originals: dict[str, str] = {}

    for f in sorted(glob.glob(str(ENGINE / "backtest" / "*.py"))):
        p = Path(f)
        src = p.read_text(encoding="utf-8", errors="replace")
        if "gate_v2_verdicts" not in src or any(m in src for m in ADOPTED_MARKERS):
            continue

        read_line = next((ln for ln in src.splitlines() if READ_RE.match(ln)), None)
        if read_line is None:
            continue  # not a backtest runner with a frame read; leave the ledger alone
        cache_var = READ_RE.match(read_line).group(2)

        write_line = next((ln for ln in src.splitlines() if WRITE_RE.match(ln)), None)
        if write_line is None:
            skipped.append((p.name, "no json.dumps write"))
            continue
        wm = WRITE_RE.match(write_line)
        if not _df_bound_at_write_site(src):
            skipped.append((p.name, "df not bound at write site"))
            continue

        step1 = src.replace(read_line, read_line + _loader_block(READ_RE.match(read_line).group(1), cache_var), 1)
        step2 = step1.replace(
            write_line,
            _write_block(wm.group(1), wm.group(3)) + write_line,
            1,
        )
        if step2 == src:
            skipped.append((p.name, "no change produced"))
            continue

        p.write_text(step2, encoding="utf-8")
        originals[p.name] = src
        adopted.append(p.name)

    for name in list(adopted):
        try:
            py_compile.compile(str(ENGINE / "backtest" / name), doraise=True)
        except py_compile.PyCompileError as exc:
            (ENGINE / "backtest" / name).write_text(originals[name], encoding="utf-8")
            adopted.remove(name)
            rolled.append(name)
            print(f"ROLLED BACK {name}: {str(exc).splitlines()[-1][:80]}")

    print(f"adopted (generic read anchor) : {len(adopted)}")
    for n in adopted:
        print("   ", n)
    print(f"rolled back : {len(rolled)}")
    print(f"skipped     : {len(skipped)}")
    for n, why in skipped:
        print(f"    {n}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())