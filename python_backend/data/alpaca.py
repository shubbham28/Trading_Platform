"""
Alpaca market data provider.

Imports the Alpaca SDK at module scope, so importing this module is a deliberate
choice. `data/__init__.py` exposes only the interface for that reason.
"""
import os
import re
from datetime import datetime
from typing import Optional

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from data.base import DataProvider

_TIMEFRAME_RE = re.compile(r'^(\d+)(Min|Hour|Day|Week|Month)$')

_UNIT_MAP = {
    'Min': TimeFrame.Unit.Minute,
    'Hour': TimeFrame.Unit.Hour,
    'Day': TimeFrame.Unit.Day,
    'Week': TimeFrame.Unit.Week,
    'Month': TimeFrame.Unit.Month,
}


class AlpacaDataProvider(DataProvider):
    """Historical bars from Alpaca."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        feed: str = 'iex',
    ):
        self.api_key = api_key or os.getenv('ALPACA_API_KEY')
        self.api_secret = api_secret or os.getenv('ALPACA_API_SECRET')

        if not self.api_key or not self.api_secret:
            raise ValueError('Alpaca API credentials not provided')

        # Recorded on results so a number can be traced to its tape. 'iex' is
        # roughly 2% of consolidated volume; 'sip' is the full tape and needs a
        # paid Alpaca plan. Which one produced a backtest is not a detail.
        self.feed = feed
        self.name = f'alpaca-{feed}'
        self.client = StockHistoricalDataClient(self.api_key, self.api_secret)

    def get_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = '1Day',
    ) -> pd.DataFrame:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=parse_timeframe(timeframe),
            start=datetime.fromisoformat(start_date),
            end=datetime.fromisoformat(end_date),
        )
        df = self.client.get_stock_bars(request).df

        if df.empty:
            return df

        df = df.reset_index()
        keep = [
            c for c in
            ('timestamp', 'open', 'high', 'low', 'close', 'volume',
             'trade_count', 'vwap')
            if c in df.columns
        ]
        # Alpaca ships its own `vwap` column. Dropped deliberately: it is a
        # per-bar VWAP, not the session-cumulative line strategies compare
        # against, and leaving it would shadow the correct one computed in
        # indicators.calculate_session_vwap.
        keep = [c for c in keep if c != 'vwap']
        return self.validate_frame(df[keep])

    def get_latest_bar(self, symbol: str, timeframe: str = '1Min') -> Optional[dict]:
        end = datetime.utcnow()
        start = end - pd.Timedelta(days=5)
        df = self.get_bars(
            symbol, start.isoformat(), end.isoformat(), timeframe
        )
        if df.empty:
            return None
        return df.iloc[-1].to_dict()


def parse_timeframe(timeframe: str) -> TimeFrame:
    """Map a timeframe string to an Alpaca TimeFrame.

    Raises on anything unrecognised. The previous implementation defaulted to
    daily, so a typo in a request silently backtested the wrong bar size and
    reported the result as if nothing were wrong.
    """
    match = _TIMEFRAME_RE.match(timeframe)
    if not match:
        raise ValueError(
            f'Unrecognised timeframe {timeframe!r}. '
            "Expected e.g. '1Min', '5Min', '15Min', '1Hour', '1Day'."
        )
    amount, unit = int(match.group(1)), match.group(2)
    return TimeFrame(amount, _UNIT_MAP[unit])
