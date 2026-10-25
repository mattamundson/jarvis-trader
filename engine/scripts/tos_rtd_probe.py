#!/usr/bin/env python
"""TOS RTD connectivity + quote probe (thinkorswim desktop).

Run with the engine venv from the repo root or ``engine/``::

    engine/.venv/Scripts/python.exe engine/scripts/tos_rtd_probe.py
    engine/.venv/Scripts/python.exe engine/scripts/tos_rtd_probe.py --quick

What it proves, in order:

1. **Transport** — thinkorswim's RTD TCP listener answers on ``127.0.0.1:12001``
   with the verified ``HELLO 1.1`` → ``RTD SERVER`` handshake.
2. **Session** — the registered ``Tos.RTD`` COM server starts, accepts our
   ``IRTDUpdateEvent`` callback, and answers ``Heartbeat`` with ``pfRes=1``.
3. **Quotes** — live ``LAST``/``BID``/``ASK`` for the focused watchlist
   (MES, SPY, QQQ, VIX).
4. **Options** — a live option-chain sample for SPY (nearest weekly expiry).

Exit codes: ``0`` if the transport handshake succeeded, ``1`` otherwise.
Steps 2-4 degrade to ``SKIP``/``FAIL`` without failing the run — the probe is
diagnostic, not a gate.

Read-only: only the RTD *read* API is ever called.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

WATCHLIST = ("MES", "SPY", "QQQ", "VIX")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def _report(step: str, status: str, detail: str = "") -> None:
    print(f"[{status:4s}] {step}" + (f" — {detail}" if detail else ""), flush=True)


def step_transport() -> bool:
    from data.tos_rtd_adapter import RTD_HOST, RTD_PORT, probe_tcp_handshake

    result = probe_tcp_handshake(RTD_HOST, RTD_PORT, timeout_s=3.0)
    if result["ok"]:
        _report(
            f"transport  {RTD_HOST}:{RTD_PORT} handshake",
            PASS,
            f"banner={result['banner']!r}",
        )
        return True
    _report(
        f"transport  {RTD_HOST}:{RTD_PORT} handshake",
        FAIL,
        f"{result['error']} (is thinkorswim running and logged in?)",
    )
    return False


async def main(quick: bool) -> int:
    print("=" * 72)
    print("thinkorswim RTD probe — read-only quote-source diagnostic")
    print("=" * 72)

    transport_ok = step_transport()

    try:
        # Deliberately NOT `import win32com.client` here: importing pywin32's COM
        # layer on the main thread before the adapter's own COM worker thread has
        # initialised can leave the session's ServerStart without a response.
        # A spec lookup is enough to report the dependency.
        import importlib.util

        spec = importlib.util.find_spec("win32com.client")
        if spec is None:
            raise ImportError("win32com.client not importable")

        _report("dependency win32com (pywin32)", PASS)
    except Exception as exc:  # noqa: BLE001
        _report("dependency win32com (pywin32)", FAIL, str(exc))
        return 0 if transport_ok else 1

    from data.tos_rtd_adapter import TOSRTDConnector

    connector = TOSRTDConnector()
    try:
        ok = await connector.connect()
    except Exception as exc:  # noqa: BLE001
        _report("session    Tos.RTD ServerStart + Heartbeat", FAIL, repr(exc))
        return 0 if transport_ok else 1

    if not ok:
        status = connector.status()
        _report(
            "session    Tos.RTD ServerStart + Heartbeat",
            FAIL,
            f"connected=False last_error={status.get('last_error')!r}",
        )
        return 0 if transport_ok else 1

    _report(
        "session    Tos.RTD ServerStart + Heartbeat",
        PASS,
        f"connected=True observed_topics={connector.status()['observed_topics']}",
    )

    print("\n-- quotes --")
    priced = 0
    for symbol in WATCHLIST:
        quote = await connector.get_current_price(symbol)
        last, bid, ask, prev = (
            quote.get("last_price"),
            quote.get("bid"),
            quote.get("ask"),
            quote.get("prev_close"),
        )
        if last is None and bid is None and ask is None:
            _report(f"quote      {symbol:<4}", FAIL, "no value returned")
            continue
        priced += 1
        _report(
            f"quote      {symbol:<4}",
            PASS,
            f"last={last} bid={bid} ask={ask} prev_close={prev} source={quote.get('source')}",
        )

    if not quick:
        print("\n-- options (SPY nearest weekly) --")
        try:
            from data.tos_rtd_adapter import default_weekly_expiry

            expiry = default_weekly_expiry(date.today() + timedelta(days=0))
            chain = await connector.get_options_chain("SPY", expiry=expiry)
            if chain:
                _report(
                    f"options    SPY {expiry.isoformat()}",
                    PASS,
                    f"{len(chain)} contracts quoted (showing up to 4)",
                )
                for row in chain[:4]:
                    print(
                        f"             {row['option_symbol']:<22} right={row['right']:<4} "
                        f"strike={row['strike']:<8} last={row['last']} bid={row['bid']} "
                        f"ask={row['ask']}"
                    )
            else:
                _report(
                    f"options    SPY {expiry.isoformat()}",
                    SKIP,
                    "no contracts quoted (expiry may not be listed yet)",
                )
        except Exception as exc:  # noqa: BLE001
            _report("options    SPY chain", FAIL, repr(exc))

    await connector.close()

    print("\n" + "=" * 72)
    print(f"ticks priced: {priced}/{len(WATCHLIST)}")
    print("status (post-teardown — 'connected: False' here is the expected")
    print("        idle state after ServerTerminate, not a failure):")
    print("       ", connector.status())
    print("=" * 72)
    return 0 if transport_ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip the options step")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.quick)))
