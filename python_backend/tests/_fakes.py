"""
A simulated broker that keeps books.

`FakeBroker` in test_interfaces.py checks the interface contract; this one
maintains positions, cash and fills, so "the bot's end-of-day position matches
the broker's exactly" is a real comparison rather than two numbers that were
never independently derived.

Fills are immediate and at a price the test controls. That is not realistic --
a real broker fills at whatever the market gives -- but the runner is what is
under test here, and an unpredictable fill price would make every assertion
about position and equity approximate.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from brokers.base import (
    BrokerAccount, BrokerAdapter, BrokerError, BrokerOrder, BrokerPosition,
)


class SimBroker(BrokerAdapter):
    """An in-memory broker with books."""

    def __init__(
        self,
        mode: str = 'paper',
        cash: str = '100000',
        price: str = '100',
        fail_next_submit: bool = False,
        accept_before_failing: bool = False,
    ):
        self.mode = mode
        self.cash = Decimal(cash)
        self._prices: dict = {}
        self._default_price = Decimal(price)
        self._positions: dict = {}          # symbol -> [qty, avg_entry]
        self._orders: dict = {}
        self._by_client_id: dict = {}
        self._counter = 0
        self.submitted: list = []

        # Failure injection for the timeout path: raise from submit_order, but
        # optionally record the order first, which is exactly the ambiguous case
        # the router has to survive.
        self.fail_next_submit = fail_next_submit
        self.accept_before_failing = accept_before_failing

    # -- test controls -----------------------------------------------------

    def set_price(self, symbol: str, price) -> None:
        self._prices[symbol] = Decimal(str(price))

    def price_for(self, symbol: str) -> Decimal:
        return self._prices.get(symbol, self._default_price)

    def seed_position(self, symbol: str, qty, entry_price) -> None:
        """Give the broker a position we did not create, e.g. a manual trade."""
        self._positions[symbol] = [Decimal(str(qty)), Decimal(str(entry_price))]

    # -- BrokerAdapter -----------------------------------------------------

    def get_account(self) -> BrokerAccount:
        market_value = sum(
            (qty * self.price_for(symbol)
             for symbol, (qty, _) in self._positions.items()),
            Decimal('0'),
        )
        equity = self.cash + market_value
        return BrokerAccount(
            equity=equity, cash=self.cash, buying_power=equity * 2,
        )

    def get_positions(self) -> list:
        out = []
        for symbol, (qty, entry) in sorted(self._positions.items()):
            if qty == 0:
                continue
            out.append(BrokerPosition(
                symbol=symbol, qty=qty, avg_entry_price=entry,
                market_value=qty * self.price_for(symbol),
            ))
        return out

    def submit_order(
        self, symbol, qty, side, order_type='market', time_in_force='day',
        limit_price=None, stop_price=None, client_order_id=None,
    ) -> BrokerOrder:
        if qty <= 0:
            raise ValueError(f'qty must be positive, got {qty}')

        # Idempotency: the same key returns the same order, never a second one.
        if client_order_id and client_order_id in self._by_client_id:
            return self._orders[self._by_client_id[client_order_id]]

        if self.fail_next_submit:
            self.fail_next_submit = False
            if self.accept_before_failing:
                self._fill(symbol, qty, side, client_order_id)
            raise BrokerError('simulated network failure after submission')

        return self._fill(symbol, qty, side, client_order_id)

    def _fill(self, symbol, qty, side, client_order_id) -> BrokerOrder:
        price = self.price_for(symbol)
        signed = Decimal(qty) if side == 'buy' else -Decimal(qty)

        held, entry = self._positions.get(symbol, [Decimal('0'), Decimal('0')])
        new_qty = held + signed

        if new_qty == 0:
            self._positions.pop(symbol, None)
        elif held == 0 or (held > 0) != (new_qty > 0):
            self._positions[symbol] = [new_qty, price]
        elif abs(new_qty) > abs(held):
            total = abs(held) * entry + abs(signed) * price
            self._positions[symbol] = [new_qty, total / abs(new_qty)]
        else:
            self._positions[symbol] = [new_qty, entry]

        self.cash -= signed * price

        self._counter += 1
        broker_id = f'sim-{self._counter}'
        key = client_order_id or broker_id
        order = BrokerOrder(
            broker_order_id=broker_id, client_order_id=key, symbol=symbol,
            side=side, qty=Decimal(qty), filled_qty=Decimal(qty),
            status='filled', order_type='market',
            submitted_at=datetime.now(timezone.utc), filled_avg_price=price,
        )
        self._orders[broker_id] = order
        self._by_client_id[key] = broker_id
        self.submitted.append((symbol, side, Decimal(qty), price))
        return order

    def cancel_order(self, broker_order_id: str) -> None:
        if broker_order_id not in self._orders:
            raise BrokerError(f'unknown order {broker_order_id}')
        del self._orders[broker_order_id]

    def get_order(self, broker_order_id: str) -> Optional[BrokerOrder]:
        return self._orders.get(broker_order_id)

    def get_order_by_client_id(self, client_order_id: str) -> Optional[BrokerOrder]:
        broker_id = self._by_client_id.get(client_order_id)
        return self._orders.get(broker_id) if broker_id else None
