# HB-1: Broker STP Wiring — Implementation Plan
**Priority:** CRITICAL BLOCKER  
**Status:** DESIGN PHASE  
**ETA:** 6 hours (design + implementation + testing)  
**Target:** Automate child STP submission on entry fill  

---

## The Problem (Trade #135 Symptom)

Currently:
1. Engine places parent **BUY** order @ MKT
2. Parent fills at broker
3. Engine **knows** parent filled (via IB callback)
4. But engine **does NOT** submit child STP order automatically
5. STP sits in local memory only (never reaches IB)
6. If engine crashes: STP is lost, position is OPEN with no stop

**Why this is critical:**
- Live trading requires STP at broker (IB) side, not engine side
- If engine dies, IB must execute STP automatically (broker-side safety)
- Current design violates "broker-side risk management" principle

---

## Solution Architecture

### Current Flow
```
Trader.decide()
  → returns TradeDecision(action="BUY", quantity=1, stop_price=X, target_price=Y)
  → Pipeline.execute_trade()
    → IBGatewayManager.place_paper_order(symbol, "BUY", qty, order_type="MKT")
      → IB.placeOrder(contract, MarketOrder)
      → Returns parent_order_id
    [Stop here: STP never submitted]
```

### Target Flow
```
Trader.decide()
  → TradeDecision(action="BUY", qty=1, stop_price=X, target_price=Y)
  → Pipeline.execute_trade()
    → IBGatewayManager.place_paper_order(symbol, "BUY", qty, order_type="MKT")
      → parent_order_id = IB.placeOrder(contract, MarketOrder)
      → [FILL CALLBACK triggered immediately by IB on accept]
        → on_fill_callback(parent_order_id, filled_price)
          → self.place_paper_order(..., parent_order_id=parent_order_id, 
                                   order_type="STP", aux_price=stop_price)
          → child_order_id = IB.placeOrder(contract, StopOrder(parentId=parent_order_id))
          → Log: "Child STP submitted: parent={parent_order_id} child={child_order_id}"
      → Return (parent_order_id, child_order_id) as tuple
    → Update trade journal with both IDs
```

---

## Implementation Steps

### Step 1: Add Fill Callback Handler (ib_gateway.py)

**Location:** `engine/execution/ib_gateway.py` → Add method to IBGatewayManager

```python
async def _on_order_fill(self, trade):
    """
    IB callback triggered when order fills.
    Automatically submits child STP if parent fill is confirmed.
    """
    parent_order_id = trade.order.orderId
    filled_quantity = trade.orderStatus.filled
    fill_price = trade.orderStatus.avgFillPrice
    
    logger.info(f"Order fill detected: parent={parent_order_id} qty={filled_quantity} @ {fill_price}")
    
    # Check if this is a parent order (no parentId set) and fully filled
    if trade.order.parentId == 0 and filled_quantity > 0:
        # Retrieve pending STP data from cache (set during place_paper_order)
        stp_request = self._pending_stps.get(parent_order_id)
        if stp_request:
            logger.info(f"Submitting queued STP for parent {parent_order_id}")
            # Submit child STP
            child_order_id = await self.place_paper_order(
                symbol=stp_request["symbol"],
                action=stp_request["action"],  # Opposite of parent
                quantity=stp_request["quantity"],
                order_type="STP",
                aux_price=stp_request["stop_price"],
                parent_order_id=parent_order_id,
            )
            if child_order_id:
                logger.info(f"Child STP submitted: parent={parent_order_id} child={child_order_id}")
                # Update trade journal with both order IDs
                await self._update_trade_journal(parent_order_id, child_order_id)
            else:
                logger.error(f"Failed to submit child STP for parent {parent_order_id}")
            # Clean up cache
            del self._pending_stps[parent_order_id]
```

### Step 2: Register Callback with IB (ib_gateway.py)

**Location:** `engine/execution/ib_gateway.py` → connect() method

```python
async def connect(self):
    """Establish IB connection and register callbacks."""
    if not IB_INSYNC_AVAILABLE:
        logger.error("ib_async not available")
        return False
    
    try:
        # ... existing connect code ...
        
        # Register fill callback
        self._ib.orderStatusEvent += self._on_order_fill
        
        logger.info("Connected to IB Gateway with STP callback registered")
        return True
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        return False
```

### Step 3: Queue STP at Place Time (ib_gateway.py)

**Location:** `engine/execution/ib_gateway.py` → place_paper_order() method

Modify the method signature to accept STP details:

```python
async def place_paper_order(
    self,
    symbol: str,
    action: str,
    quantity: int,
    order_type: str = "MKT",
    limit_price: Optional[float] = None,
    aux_price: Optional[float] = None,
    parent_order_id: Optional[int] = None,
    auto_stop_price: Optional[float] = None,  # NEW: if set, queue STP
    auto_stop_action: Optional[str] = None,   # NEW: opposite of entry
) -> Optional[int]:
    """
    Place order + optionally queue child STP on fill.
    
    If auto_stop_price is provided, STP will be automatically submitted
    when parent order fills (via callback).
    """
    # ... existing validation ...
    
    # If this is a parent entry order with auto-STP, cache the STP request
    if (order_type.upper() == "MKT" and 
        auto_stop_price is not None and 
        parent_order_id is None):  # Only for parent orders
        
        stp_action = "SELL" if action.upper() == "BUY" else "BUY"
        self._pending_stps[None] = {  # Key will be parent_order_id after fill
            "symbol": symbol,
            "action": stp_action,
            "quantity": quantity,
            "stop_price": auto_stop_price,
        }
        logger.info(f"Queued STP for future parent fill: stop=${auto_stop_price}")
    
    # ... rest of place_paper_order ...
```

### Step 4: Update Pipeline to Pass STP Data (pipeline.py)

**Location:** `engine/agents/pipeline.py` → execute_trade()

```python
async def execute_trade(self, trade_decision: TradeDecision) -> dict:
    """
    Execute trade decision via IBGatewayManager.
    Automatically submit child STP on entry fill.
    """
    symbol = trade_decision.symbol
    action = trade_decision.action
    quantity = trade_decision.quantity
    stop_price = trade_decision.stop_price
    
    logger.info(f"Executing: {symbol} {action} {quantity} contracts | stop=${stop_price}")
    
    # Place parent order with auto-STP callback
    parent_order_id = await self.ib_gateway.place_paper_order(
        symbol=symbol,
        action=action,
        quantity=quantity,
        order_type="MKT",
        auto_stop_price=stop_price,  # NEW: triggers STP on fill
        auto_stop_action=("SELL" if action == "BUY" else "BUY"),
    )
    
    if parent_order_id is None:
        logger.error(f"Failed to place parent order for {symbol}")
        return {"status": "failed", "reason": "order_placement_failed"}
    
    logger.info(f"Parent order placed: {symbol} {parent_order_id}")
    
    # Update trade journal (pending child STP submission)
    await self.db_manager.log_trade(
        symbol=symbol,
        action=action,
        quantity=quantity,
        entry_price=None,  # Not filled yet
        stop_price=stop_price,
        target_price=trade_decision.target_price,
        parent_order_id=parent_order_id,
        child_order_id=None,  # Will be updated via callback
    )
    
    return {
        "status": "pending",
        "parent_order_id": parent_order_id,
        "reason": "Waiting for fill confirmation and child STP submission",
    }
```

### Step 5: Add Trade Journal Tracking (trade_journal.py)

**Location:** New file or extend existing journal router

```python
async def log_trade_with_orders(
    self,
    symbol: str,
    action: str,
    quantity: int,
    entry_price: Optional[float],
    stop_price: float,
    target_price: float,
    parent_order_id: int,
    child_order_id: Optional[int] = None,
):
    """Log trade with parent + child order IDs."""
    await self.db.execute("""
        INSERT INTO paper_trades (
            symbol, action, quantity, entry_price, stop_price, target_price,
            parent_order_id, child_order_id, timestamp, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 'pending_fill')
    """, (symbol, action, quantity, entry_price, stop_price, target_price,
          parent_order_id, child_order_id))
```

### Step 6: Testing Strategy

#### Unit Tests
```python
# test_ib_gateway_stp.py

async def test_auto_stp_callback():
    """Verify STP is queued and submitted on fill."""
    ib_gateway = IBGatewayManager(config)
    await ib_gateway.connect()
    
    # Place BUY order with auto-STP
    parent_id = await ib_gateway.place_paper_order(
        symbol="MES",
        action="BUY",
        quantity=1,
        order_type="MKT",
        auto_stop_price=4500.0,
    )
    
    # Simulate fill callback
    mock_trade = Mock()
    mock_trade.order.orderId = parent_id
    mock_trade.order.parentId = 0
    mock_trade.orderStatus.filled = 1
    
    await ib_gateway._on_order_fill(mock_trade)
    
    # Verify child STP was submitted
    assert parent_id in ib_gateway._submitted_stps
    assert ib_gateway._submitted_stps[parent_id]["stop_price"] == 4500.0

async def test_no_stp_for_non_parent_orders():
    """Verify STP not submitted for child orders."""
    # ... (test code)

async def test_stp_survives_engine_restart():
    """Verify STP persists at broker if engine crashes."""
    # ... (test code)
```

#### Integration Tests
```python
# test_hb1_end_to_end.py

async def test_full_trade_cycle_with_stp():
    """End-to-end: place entry, fill, submit STP, verify in TWS."""
    # 1. Place BUY order with auto-STP
    # 2. Wait for fill in paper account
    # 3. Verify child STP appears in IBKR TWS
    # 4. Verify trade journal records both order IDs
```

---

## Deployment Checklist

- [ ] **Step 1:** Add `_on_order_fill()` callback handler
- [ ] **Step 2:** Register callback in `connect()`
- [ ] **Step 3:** Modify `place_paper_order()` signature + STP queuing
- [ ] **Step 4:** Update `pipeline.execute_trade()` to pass STP data
- [ ] **Step 5:** Add trade journal schema column for `child_order_id`
- [ ] **Step 6:** Unit tests for callback + STP submission
- [ ] **Test in paper account:** Verify STP appears in IBKR TWS
- [ ] **Regression tests:** Ensure no existing order types break
- [ ] **Git commit:** Clean commit message with HB-1 reference
- [ ] **Restart engine** and validate logs

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Callback never fires (IB bug) | Add timeout: if parent fill not detected in 60s, cancel parent and log error |
| Duplicate STP submission | Track submitted pairs: don't re-submit if (parent_id, child_id) already exists |
| Engine crash mid-STP-submit | STP lives at broker, engine restart picks up existing position + STP |
| STP price invalid | Validate stop_price vs entry_price + current price before submit |
| Portfolio tracking issue | Query IBKR positions on restart + reconcile with local journal |

---

## Files to Modify

1. `engine/execution/ib_gateway.py`
   - Add `_pending_stps` dict (cache for queued STPs)
   - Add `_on_order_fill()` callback method
   - Register callback in `connect()`
   - Modify `place_paper_order()` signature

2. `engine/agents/pipeline.py`
   - Modify `execute_trade()` to pass `auto_stop_price`

3. `engine/data/schema.sql` (if needed)
   - Add `child_order_id` column to `paper_trades` table

4. `engine/tests/test_*.py`
   - Add unit + integration tests for STP callback

---

## Success Criteria

✓ Parent order places successfully  
✓ Child STP auto-submits on fill (visible in IBKR TWS)  
✓ Trade journal records both parent + child order IDs  
✓ All regression tests pass  
✓ No modifications to safety_layer or risk_manager (independent feature)  
✓ Code is committable and documented

---

**Next:** Implement Step 1-2, then test callback locally before full deployment.
