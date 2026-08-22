"""
Search execution package.
"""

from api.search.orchestration import deduplicate_results, execute_search

__all__ = ["execute_search", "deduplicate_results"]
