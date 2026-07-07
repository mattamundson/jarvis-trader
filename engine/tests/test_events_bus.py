"""Tests for events bus module."""
from uuid import UUID

import pytest


def test_publish_adds_event_to_deque():
    """Test that publish() adds event to deque."""
    from events import bus

    bus._events.clear()
    bus._last_regime.clear()

    bus.publish('test_type', 'Test message', symbol='MES', severity='info')

    assert len(bus._events) == 1
    event = bus._events[0]
    assert event['type'] == 'test_type'
    assert event['message'] == 'Test message'
    assert event['symbol'] == 'MES'
    assert event['severity'] == 'info'
    assert 'id' in event
    assert 'timestamp' in event

    bus._events.clear()
    bus._last_regime.clear()


def test_get_recent_returns_max_limit():
    """Test that get_recent(5) returns max 5 events newest-first."""
    from events import bus

    bus._events.clear()
    bus._last_regime.clear()

    # Add 10 events
    for i in range(10):
        bus.publish('test', f'Message {i}', symbol=f'SYM{i}')

    # Get recent 5
    recent = bus.get_recent(5)
    assert len(recent) == 5

    # Should be newest first (reverse order)
    assert recent[0]['message'] == 'Message 9'
    assert recent[4]['message'] == 'Message 5'

    bus._events.clear()
    bus._last_regime.clear()


def test_buffer_caps_at_150():
    """Test that buffer caps at 150 events."""
    from events import bus

    bus._events.clear()
    bus._last_regime.clear()

    # Add 160 events
    for i in range(160):
        bus.publish('test', f'Message {i}')

    # Should only have 150 (maxlen=150)
    assert len(bus._events) == 150

    # Should have newest 150, not oldest 150
    all_recent = bus.get_recent(200)
    assert len(all_recent) == 150
    assert 'Message 159' in all_recent[0]['message']  # Newest
    assert 'Message 10' in all_recent[149]['message']  # Oldest in buffer

    bus._events.clear()
    bus._last_regime.clear()


def test_detect_regime_change_first_occurrence():
    """Test detect_regime_change on first occurrence returns None."""
    from events import bus

    bus._events.clear()
    bus._last_regime.clear()

    # First call should return None (no prior regime)
    result = bus.detect_regime_change('MES', 'TRENDING_BULL')
    assert result is None

    # Check it was stored
    assert bus._last_regime['MES'] == 'TRENDING_BULL'

    bus._events.clear()
    bus._last_regime.clear()


def test_detect_regime_change_when_changed():
    """Test detect_regime_change returns old_regime when changed."""
    from events import bus

    bus._events.clear()
    bus._last_regime.clear()

    # Set initial regime
    bus.detect_regime_change('MES', 'TRENDING_BULL')

    # Change regime
    result = bus.detect_regime_change('MES', 'RANGING')
    assert result == 'TRENDING_BULL'
    assert bus._last_regime['MES'] == 'RANGING'

    bus._events.clear()
    bus._last_regime.clear()


def test_detect_regime_change_returns_none_when_same():
    """Test detect_regime_change returns None when regime unchanged."""
    from events import bus

    bus._events.clear()
    bus._last_regime.clear()

    # Set initial regime
    bus.detect_regime_change('MES', 'TRENDING_BULL')

    # Same regime
    result = bus.detect_regime_change('MES', 'TRENDING_BULL')
    assert result is None

    bus._events.clear()
    bus._last_regime.clear()


def test_event_has_required_fields():
    """Test that event dict has all required fields."""
    from events import bus

    bus._events.clear()
    bus._last_regime.clear()

    bus.publish('test', 'msg', symbol='MES', severity='warn')

    event = bus._events[0]
    required_fields = ['id', 'type', 'symbol', 'message', 'severity', 'timestamp']

    for field in required_fields:
        assert field in event, f"Missing field: {field}"

    # Validate field types
    assert isinstance(event['id'], str)
    assert isinstance(event['type'], str)
    assert event['symbol'] is None or isinstance(event['symbol'], str)
    assert isinstance(event['message'], str)
    assert event['severity'] in ('info', 'warn', 'critical')
    assert isinstance(event['timestamp'], str)

    bus._events.clear()
    bus._last_regime.clear()
