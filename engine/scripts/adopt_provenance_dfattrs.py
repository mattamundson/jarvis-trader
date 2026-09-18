"""Second-pass provenance adoption: the `df.attrs` seam.

The first pass (`adopt_provenance_batch.py`) covered 40 writers where `data_file` is provably bound
at the verdict write site. The remaining ones share a different shape: `data_file` is local to
`_load_*_data(...)`, which returns only the DataFrame, so the write site has `df` but no
`data_file`.

The honest seam for those is the one already proven on `run_mes_trend_vix_pctile_rank1.py`:

    1. in the loader, right after the frame is read:
           df.attrs["cache_provenance"] = cache_provenance(data_file)
    2. at the verdict write site:
           verdict_doc = inject_cache_provenance(verdict_doc, df=df)

Both are real, not a guarded no-op: the value flows from the actual cache path the loader selected.
A file is only touched when `df` is provably bound at the write site (AST), the injected lines match
each anchor line's own indentation, and every changed file is compiled afterwards with automatic
rollback on failure — the three lessons from the first pass, where a hard-coded indent broke 39 files.
"""

from __future__ import annotations

import ast
import glob
import py_compile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent  # engine/
READ_ANCHOR = "df = pd.read_csv(data_file)"
CLEANUP_KEYS = ("cache_provenance", "inject_cache_provenance")


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _insert_after(src: str, anchor_substr: str, block_fn) -> str | None:
    for line in src.splitlines(keepends=True):
        if anchor_substr in line:
            indent = _indent_of(line)
            return src.replace(line, line + block_fn(indent), 1)
    return None


def _insert_before(src: str, anchor_substr: str, block_fn) -> str | None:
    for line in src.splitlines(keepends=True):
        if anchor_substr in line:
            indent = _indent_of(line)
            return src.replace(line, block_fn(indent) + line, 1)
    return None


def loader_block(indent: str) -> str:
    return (
        f"{indent}# Cache provenance (2026-09-17 audit: 0/76 verdicts recorded which cache they ran on).\n"
        f"{indent}from backtest._gate_v2_helpers import cache_provenance as _cp  # noqa: E402\n"
        f'{indent}df.attrs["cache_provenance"] = _cp(data_file)\n'
    )


def write_block(indent: str) -> str:
    return (
        f"{indent}# Record the provenance carried on the frame (see loader).\n"
        f"{indent}from backtest._gate_v2_helpers import inject_cache_provenance as _ip  # noqa: E402\n"
        f"{indent}verdict_doc = _ip(verdict_doc, df=df)\n"
    )


def df_in_scope(src: str, write_line: str) -> bool:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if write_line not in (ast.get_source_segment(src, node) or ""):
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

    for f in sorted(glob.glob(str(ENGINE / "backtest" / "run_*.py"))):
        p = Path(f)
        src = p.read_text(encoding="utf-8", errors="replace")
        if "gate_v2_verdicts" not in src:
            continue
        if any(k in src for k in CLEANUP_KEYS):
            continue  # already adopted; never double-inject
        if READ_ANCHOR not in src:
            skipped.append((p.name, "no loader read anchor"))
            continue

        write_anchor = next(
            (ln.strip() for ln in src.splitlines() if "write_text(json.dumps(verdict_doc" in ln), None
        )
        if write_anchor is None:
            skipped.append((p.name, "no verdict write anchor"))
            continue
        if not df_in_scope(src, write_anchor):
            skipped.append((p.name, "df not provably bound at write site"))
            continue

        step1 = _insert_after(src, READ_ANCHOR, loader_block)
        if step1 is None:
            skipped.append((p.name, "loader insert failed"))
            continue
        step2 = _insert_before(step1, write_anchor, write_block)
        if step2 is None:
            skipped.append((p.name, "write insert failed"))
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

    print(f"adopted via df.attrs : {len(adopted)}")
    print(f"rolled back          : {len(rolled)}")
    print(f"skipped              : {len(skipped)}")
    for n, why in skipped:
        print(f"    {n}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())