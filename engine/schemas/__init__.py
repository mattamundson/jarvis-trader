"""Typed schemas for jarvis-trader.

New Pydantic models land here when they describe a contract that crosses
a boundary — router request/response, cross-module payload, or durable
storage row shape. Signal/agent dataclasses stay local to the module
that produces them.
"""
