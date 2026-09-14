"""Offline event-market research evidence helpers.

This package is intentionally research-only: no network, broker, router, or runtime
configuration imports belong here.
"""

from .schema import EventMarketReplayRecord, infer_resolution_value, replay_hash

__all__ = ["EventMarketReplayRecord", "infer_resolution_value", "replay_hash"]
