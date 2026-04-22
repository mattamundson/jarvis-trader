# IB Gateway Paper E2E Test Guide

Manual-run tests for the full IB Gateway paper pipeline round-trip.
File: `engine/tests/test_ibkr_e2e_paper.py`

---

## WARNING — Port 4001 is permanently blocked

**Never enable live trading (port 4001).** The `IBGatewayConfig` dataclass
rejects port 4001 at construction time with `ValueError`. This codebase
supports paper trading (port 4002) only. The production live-trading path
is intentionally unimplemented.

---

## Prerequisites

### 1. Start IB Gateway (paper account)

1. Launch **IB Gateway** (not TWS — both work, but Gateway is lighter).
2. Log in with your paper trading credentials (account prefix `DU...`, e.g. `DUP662235`).
3. In IB Gateway: **Configure → API → Settings**
   - Check **Enable ActiveX and Socket Clients**
   - Set **Socket port** to `4002`
   - Uncheck **Read-Only API** (orders must be writable)
   - Click **OK / Apply**
4. Confirm the Gateway status bar shows **Paper Trading** mode.

### 2. Verify ib_async is installed

```powershell
engine\.venv\Scripts\python -c "import ib_async; print('ib_async OK')"
```

If that fails:

```powershell
engine\.venv\Scripts\pip install "ib_async>=0.9.86"
```

---

## Running the tests

From the repo root:

```powershell
cd engine
.\.venv\Scripts\python -m pytest tests/test_ibkr_e2e_paper.py -m manual -v
```

Or from outside the `engine/` directory, with full path:

```powershell
.\.venv\Scripts\python -m pytest engine/tests/test_ibkr_e2e_paper.py -m manual -v
```

---

## Expected output (all tests pass, market open)

```
tests/test_ibkr_e2e_paper.py::test_ibkr_gateway_reachable PASSED
tests/test_ibkr_e2e_paper.py::test_mes_front_month_subscribe_ticks PASSED
tests/test_ibkr_e2e_paper.py::test_paper_order_dry_run PASSED
```

Log output (with `-v`) will include lines like:

```
IB Gateway reachable — paper port=4002 server_version=176
MES qualified: conId=495512572
MES tick received: price=5312.50
MES dry-run order placed: order_id=1
order_id=1 confirmed in open orders
Cancel sent for order_id=1
order_id=1 confirmed removed from open orders — dry-run PASSED
```

## Expected output (market closed / outside Globex hours)

`test_mes_front_month_subscribe_ticks` passes with a WARNING instead of a
price assertion, because IB returns zeros for bid/ask/last when the market is
closed and snapshot data is not cached. This is not a failure:

```
WARNING  root:test_ibkr_e2e_paper.py:... MES contract qualified (conId=...) but
         no price data received within 30 s. This is expected outside CME Globex
         trading hours ...
PASSED
```

---

## CI / default run behaviour

The `manual` marker is excluded from the default `pytest` run. The tests will
NOT be collected unless you pass `-m manual` explicitly:

```powershell
# Default run — manual tests are NOT collected (safe for CI)
.\.venv\Scripts\python -m pytest tests/ -v

# Manual run — only manual tests
.\.venv\Scripts\python -m pytest tests/ -m manual -v

# Collect-only check (lists without running)
.\.venv\Scripts\python -m pytest tests/test_ibkr_e2e_paper.py --collect-only -q
```

The `--collect-only` command should list exactly 3 tests:
```
tests/test_ibkr_e2e_paper.py::test_ibkr_gateway_reachable
tests/test_ibkr_e2e_paper.py::test_mes_front_month_subscribe_ticks
tests/test_ibkr_e2e_paper.py::test_paper_order_dry_run
```

---

## Test descriptions

| Test | What it validates |
|------|-------------------|
| `test_ibkr_gateway_reachable` | TCP handshake to port 4002 succeeds; IB server version > 0 |
| `test_mes_front_month_subscribe_ticks` | Front-month MES contract qualifies; snapshot tick received; price in 4 000–10 000 range |
| `test_paper_order_dry_run` | LMT order placed (price=1.00, won't fill), IB returns positive order ID, cancel succeeds, order leaves open-orders list within 5 s |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `SKIPPED — IB Gateway not started` | Gateway not running or API not enabled | Start Gateway, enable API socket on port 4002 |
| `SKIPPED — ib_async / ib_insync not installed` | Library missing from venv | `pip install ib_async>=0.9.86` |
| `AssertionError: MES price ... outside 4000–10000` | Wrong contract qualified or data feed issue | Check MES market data subscription in IB Account Management |
| `AssertionError: order_id ... still in open orders after cancel` | IB cancel ACK slow | Increase the 5 s polling window in the test; usually transient |
| Server version = 0 | Partial connection; Gateway not fully started | Wait 10 s after Gateway shows "Connected", retry |

---

## IBKR connector library used

`ib_async >= 0.9.86` (successor to `ib_insync`, drop-in compatible API).
Import path: `from ib_async import IB, Future, LimitOrder, ...`
Fallback: `from ib_insync import ...` if `ib_async` is absent.
Controlled by `IB_INSYNC_AVAILABLE` sentinel in `engine/execution/ib_gateway.py`.
