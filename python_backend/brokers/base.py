"""
Broker interface.

Everything that can place, cancel or read an order lives behind this. Two
reasons it is an interface rather than a direct SDK call:

Swappability -- the plan keeps execution on Alpaca while allowing the data feed
to move elsewhere, and later possibly the broker too. Strategy and risk code must
not know which broker it is talking to.

Testability -- an order path that can only be tested against a live broker will
not be tested. A fake implementing this interface lets the risk gate and the
runner be tested without a network or an account.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class BrokerAccount:
    """Account state as the broker reports it."""
    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    currency: str = 'USD'
    # True when the broker says this account is restricted from trading. A
    # blocked account must not look like a merely quiet one.
    trading_blocked: bool = False


@dataclass(frozen=True)
class BrokerPosition:
    """A position as the broker reports it.

    This is the authority. Reconciliation corrects local state to match these,
    never the other way round: the broker is where the money actually is.
    """
    symbol: str
    qty: Decimal          # signed; negative is short
    avg_entry_price: Decimal
    market_value: Decimal


@dataclass(frozen=True)
class BrokerOrder:
    """An order as the broker reports it."""
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    qty: Decimal
    filled_qty: Decimal
    status: str
    order_type: str
    submitted_at: Optional[datetime] = None
    filled_avg_price: Optional[Decimal] = None


class BrokerError(RuntimeError):
    """A broker rejected or failed a request.

    Distinct from a local validation error so a caller can tell "we asked badly"
    from "they said no", and so a retry policy can apply to one and not the other.
    """


class BrokerAdapter(ABC):
    """Order placement and account state."""

    #: Which account this talks to. Never inferred from an env var at the call
    #: site -- a paper/live mix-up must be visible on the object.
    mode: str = 'paper'

    @abstractmethod
    def get_account(self) -> BrokerAccount:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        """Every open position. The truth that reconciliation compares against."""
        raise NotImplementedError

    @abstractmethod
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
        """Place an order.

        `client_order_id` is the idempotency key and callers are expected to
        supply one. Resending the same id after a timeout must not create a
        second order -- which is the only safe way to retry a request that may
        already have been accepted.
        """
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_order(self, broker_order_id: str) -> Optional[BrokerOrder]:
        raise NotImplementedError

    @abstractmethod
    def get_order_by_client_id(self, client_order_id: str) -> Optional[BrokerOrder]:
        """Look an order up by our own id.

        The recovery path after a timeout: we do not know whether the order
        landed, and this is how we find out before deciding to resend.
        """
        raise NotImplementedError
