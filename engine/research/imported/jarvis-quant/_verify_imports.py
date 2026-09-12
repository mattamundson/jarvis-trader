"""Verify the sandbox venv has every package the guide expects."""
import ib_async, pandas, numpy, scipy, matplotlib, yfinance, yaml, requests, dotenv, schedule

print("ALL IMPORTS OK")
print("ib_async    ", ib_async.__version__)
print("pandas      ", pandas.__version__)
print("numpy       ", numpy.__version__)
print("scipy       ", scipy.__version__)
print("matplotlib  ", matplotlib.__version__)
print("yfinance    ", yfinance.__version__)
print("pyyaml      ", yaml.__version__)
print("requests    ", requests.__version__)
print("python-dotenv", getattr(dotenv, "__version__", "unknown"))
print("schedule    ", getattr(schedule, "__version__", "unknown"))
