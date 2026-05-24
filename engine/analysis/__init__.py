# discord_correlation is a standalone script that requires a live DB at import time.
# Import lazily (inside functions) to avoid breaking the test suite.
__all__: list[str] = []
