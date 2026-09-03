"""
Market data interface.

Separate from the broker on purpose. Your broker decides what orders you can
place; your data feed decides whether your signals mean anything, and they do not
have to be the same vendor. Alpaca's free tier is IEX-only -- roughly 2% of
consolidated volume -- so a VWAP or opening-range strategy running on it computes
against a tape most of the market never saw. Behind this interface, that becomes
a one-line swap rather than a rewrite of every strategy.
"""
from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

# The column contract every provider must satisfy. The engine and every strategy
# assume exactly these names.
REQUIRED_COLUMNS = ('timestamp', 'open', 'high', 'low', 'close', 'volume')


class DataProvider(ABC):
    """Historical and latest bars for a symbol."""

    #: Human-readable feed identity, e.g. 'alpaca-iex'. Recorded alongside
    #: results so a number can be traced to the tape that produced it.
    name: str = 'unknown'

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = '1Day',
    ) -> pd.DataFrame:
        """Bars for `symbol`, ascending by timestamp.

        Must return the columns in REQUIRED_COLUMNS. An empty DataFrame is a
        valid answer meaning "no data for this window"; raising is for a failure
        to ask.
        """
        raise NotImplementedError

    @abstractmethod
    def get_latest_bar(self, symbol: str, timeframe: str = '1Min') -> Optional[dict]:
        """The most recent completed bar, or None if there is none."""
        raise NotImplementedError

    @staticmethod
    def validate_frame(df: pd.DataFrame) -> pd.DataFrame:
        """Check the column contract.

        Called by implementations before returning. A provider that silently
        omits `volume` would make every volume filter in every strategy evaluate
        to nothing, which is far harder to notice than an exception here.
        """
        if df.empty:
            return df
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(
                f'DataProvider returned a frame missing {missing}. '
                f'Required columns: {list(REQUIRED_COLUMNS)}'
            )
        return df
