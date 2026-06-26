"""Test-only env bootstrap for the factory.

`Backtester` imports `config.TradingConfig`, which fail-fasts unless `API_KEY`
is set. Tests never touch the live API, so supply a throwaway value here (set at
collection time, before `config` is imported). The real pilot/scale runs load the
engine's actual `.env`.
"""

import os

os.environ.setdefault("API_KEY", "factory-test-dummy-key")
