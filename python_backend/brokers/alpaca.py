"""
Alpaca broker adapter.

Imports the Alpaca SDK at module scope. Importing this module is a deliberate
choice; `brokers/__init__.py` exposes only the interface.
"""
import os
from decimal import Decimal
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest, MarketOrderRequest, StopLimitOrderRequest,
    StopOrderRequest,
)

from brokers.base import (
    BrokerAccount, BrokerAdapter, BrokerError, BrokerOrder, BrokerPosition,
)

_SIDES = {'buy': OrderSide.BUY, 'sell': OrderSide.SELL}
_TIF = {
    'day': TimeInForce.DAY, 'gtc': TimeInForce.GTC,
    'ioc': TimeInForce.IOC, 'fok': TimeInForce.FOK,
}


def _dec(value) -> Decimal:
    """Coerce a broker's number into Decimal via str.

    Via str, never via float: Decimal(0.1) carries the float's representation
    error into a column that is supposed to reconcile against a statement.
    """
    return Decimal(str(value if value is not None else 0))


class AlpacaBroker(BrokerAdapter):
    """Order placement and account state via Alpaca."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        mode: Optional[str] = None,
    ):
        # Separate credential names per mode. Deliberately not one pair with a
        # mode flag: with a single pair, flipping one env var points the same
        # keys at a live account, which is exactly the accident to design out.
        resolved_mode = mode or os.getenv('TRADING_MODE', 'paper')
        if resolved_mode not in ('paper', 'live'):
            raise ValueError(
                f"TRADING_MODE must be 'paper' or 'live', got {resolved_mode!r}"
            )
        self.mode = resolved_mode

        if self.mode == 'live':
            key = api_key or os.getenv('ALPACA_LIVE_API_KEY')
            secret = api_secret or os.getenv('ALPACA_LIVE_API_SECRET')
            if not key or not secret:
                raise ValueError(
                    'Live mode requires ALPACA_LIVE_API_KEY and '
                    'ALPACA_LIVE_API_SECRET. Paper credentials are not reused '
                    'for live trading on purpose.'
                )
        else:
            key = api_key or os.getenv('ALPACA_API_KEY')
            secret = api_secret or os.getenv('ALPACA_API_SECRET')
            if not key or not secret:
                raise ValueError('Alpaca API credentials not provided')

        self.client = TradingClient(key, secret, paper=self.mode == 'paper')

    def get_account(self) -> BrokerAccount:
        try:
            account = self.client.get_account()
        except Exception as exc:
            raise BrokerError(f'Failed to fetch account: {exc}') from exc

        return BrokerAccount(
            equity=_dec(account.equity),
            cash=_dec(account.cash),
            buying_power=_dec(account.buying_power),
            currency=getattr(account, 'currency', 'USD') or 'USD',
            trading_blocked=bool(getattr(account, 'trading_blocked', False)),
        )

    def get_positions(self) -> list[BrokerPosition]:
        try:
            positions = self.client.get_all_positions()
        except Exception as exc:
            raise BrokerError(f'Failed to fetch positions: {exc}') from exc

        return [
            BrokerPosition(
                symbol=p.symbol,
                qty=_dec(p.qty),
                avg_entry_price=_dec(p.avg_entry_price),
                market_value=_dec(p.market_value),
            )
            for p in positions
        ]

    def submit_order(
        self,
        symbol: str,
        qty: Decimal,
        side: str,
        order_type: str = 'market',
        time_in_force: str = 'day',
        limit_price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
    ) -> BrokerOrder:
        if side not in _SIDES:
            raise ValueError(f'side must be buy or sell, got {side!r}')
        if time_in_force not in _TIF:
            raise ValueError(f'unsupported time_in_force {time_in_force!r}')
        if qty <= 0:
            raise ValueError(f'qty must be positive, got {qty}')

        common = {
            'symbol': symbol,
            'qty': float(qty),
            'side': _SIDES[side],
            'time_in_force': _TIF[time_in_force],
            'client_order_id': client_order_id,
        }

        if order_type == 'market':
            request = MarketOrderRequest(**common)
        elif order_type == 'limit':
            if limit_price is None:
                raise ValueError('limit orders require limit_price')
            request = LimitOrderRequest(limit_price=float(limit_price), **common)
        elif order_type == 'stop':
            if stop_price is None:
                raise ValueError('stop orders require stop_price')
            request = StopOrderRequest(stop_price=float(stop_price), **common)
        elif order_type == 'stop_limit':
            if limit_price is None or stop_price is None:
                raise ValueError(
                    'stop_limit orders require both limit_price and stop_price'
                )
            request = StopLimitOrderRequest(
                limit_price=float(limit_price), stop_price=float(stop_price),
                **common,
            )
        else:
            raise ValueError(f'unsupported order_type {order_type!r}')

        try:
            order = self.client.submit_order(request)
        except Exception as exc:
            raise BrokerError(f'Order rejected for {symbol}: {exc}') from exc

        return _to_broker_order(order)

    def cancel_order(self, broker_order_id: str) -> None:
        try:
            self.client.cancel_order_by_id(broker_order_id)
        except Exception as exc:
            raise BrokerError(
                f'Failed to cancel {broker_order_id}: {exc}'
            ) from exc

    def get_order(self, broker_order_id: str) -> Optional[BrokerOrder]:
        try:
            order = self.client.get_order_by_id(broker_order_id)
        except Exception:
            return None
        return _to_broker_order(order) if order else None

    def get_order_by_client_id(self, client_order_id: str) -> Optional[BrokerOrder]:
        try:
            order = self.client.get_order_by_client_id(client_order_id)
        except Exception:
            # Not found is the expected answer here, not an error: this is the
            # question "did my order actually land?" after a timeout.
            return None
        return _to_broker_order(order) if order else None


def _to_broker_order(order) -> BrokerOrder:
    return BrokerOrder(
        broker_order_id=str(order.id),
        client_order_id=str(order.client_order_id),
        symbol=order.symbol,
        side=str(getattr(order.side, 'value', order.side)),
        qty=_dec(order.qty),
        filled_qty=_dec(order.filled_qty),
        status=str(getattr(order.status, 'value', order.status)),
        order_type=str(getattr(order.order_type, 'value', order.order_type)),
        submitted_at=getattr(order, 'submitted_at', None),
        filled_avg_price=(
            _dec(order.filled_avg_price)
            if getattr(order, 'filled_avg_price', None) is not None else None
        ),
    )
