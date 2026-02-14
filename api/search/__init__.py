"""
Search execution package.
"""

from .orchestration import deduplicate_results, execute_search

__all__ = ["execute_search", "deduplicate_results"]
