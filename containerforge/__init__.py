"""
ContainerForge — Containerize anything. Ship everywhere.

Version: 2.1.0
License: Apache 2.0
"""
__version__ = "2.1.0"
__author__ = "ContainerForge Contributors"
__license__ = "Apache-2.0"

# cli is intentionally NOT imported here — it has heavy deps (rich, click).
# The entry_point in pyproject.toml points directly to containerforge.cli:cli
