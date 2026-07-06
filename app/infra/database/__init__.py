"""Database infrastructure."""
from .connection import Database

# Alias for backward compatibility with main.py
DatabasePool = Database

__all__ = ["Database", "DatabasePool"]
