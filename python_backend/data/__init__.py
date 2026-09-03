"""Market data providers.

Only the interface is imported here. Concrete providers pull in vendor SDKs, so
importing one must be an explicit choice -- otherwise the test suite cannot load
this package without every vendor library installed.
"""
from data.base import REQUIRED_COLUMNS, DataProvider

__all__ = ['DataProvider', 'REQUIRED_COLUMNS']
