"""
Runner entrypoint.

    python -m runner.main --bot-id 1
    python -m runner.main --bot-id 1 --symbol AAPL --max-ticks 5
    python -m runner.main --list

ONE BOT, ONE SYMBOL, ONE PROCESS.

A bot configured for several symbols needs one process per symbol. That falls out
of the synchronous loop: interleaving symbols in one thread would mean a slow
data call for one symbol delaying decisions for another, and the failure would be
invisible -- a bar quietly acted on late rather than an error.

Process-per-pair is also the easier thing to supervise: systemd, a container
restart policy, or `docker compose` all already know how to keep a process alive,
and a crash takes down one symbol rather than the whole book. Noted in TODOS.md
as the reason there is no multiplexing clock.

Paper only. `OrderRouter` refuses live intents until Phase 6 builds the approval
queue, so `--mode live` is rejected here rather than at the last moment.
"""
import argparse
import logging
import sys
from typing import Optional

from sqlalchemy.orm import sessionmaker

from db import repository
from db.session import get_engine
from risk.contracts import AccountRiskLimits, BotRiskLimits
from risk.gate import RiskGate
from runner.clock import PollingClock
from runner.loop import BotRunner
from runner.router import OrderRouter

logger = logging.getLogger('runner')


def list_bots() -> int:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        bots = repository.list_bots(session)

    if not bots:
        print('No bots configured. Create one via POST /bots.')
        return 0

    print(f"{'id':>4}  {'name':22s} {'strategy':24s} {'tf':6s} "
          f"{'mode':6s} {'on':3s} symbols")
    for bot in bots:
        print(
            f'{bot.id:>4}  {bot.name:22.22s} {bot.strategy_id:24.24s} '
            f'{bot.timeframe:6s} {bot.mode:6s} '
            f"{'yes' if bot.enabled else 'no':3s} {','.join(bot.symbols)}"
        )
    return 0


def run(bot_id: int, symbol: Optional[str], max_ticks: Optional[int]) -> int:
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)

    with factory() as session:
        bot = repository.get_bot(session, bot_id)
        if bot is None:
            print(f'error: bot {bot_id} does not exist', file=sys.stderr)
            return 2
        if not bot.enabled:
            print(f'error: bot {bot_id} ({bot.name}) is disabled', file=sys.stderr)
            return 2
        if bot.mode != 'paper':
            print(
                f'error: bot {bot_id} is in {bot.mode!r} mode. Live trading is '
                'gated behind the Phase 6 approval queue, which does not exist '
                'yet.',
                file=sys.stderr,
            )
            return 2

        target = symbol or (bot.symbols[0] if bot.symbols else None)
        if target is None:
            print(f'error: bot {bot_id} has no symbols', file=sys.stderr)
            return 2
        if target not in bot.symbols:
            print(
                f'error: {target} is not one of bot {bot_id}\'s symbols '
                f'({", ".join(bot.symbols)})',
                file=sys.stderr,
            )
            return 2

        limits = BotRiskLimits.from_bot(bot)
        timeframe = bot.timeframe
        name = bot.name

    # Imported here, not at module scope. These pull in the Alpaca SDK and
    # raise without credentials, and `--list` and `--help` have to work on a
    # machine that has neither -- `--list` is how you find out what is
    # configured in the first place.
    from brokers.alpaca import AlpacaBroker
    from data.alpaca import AlpacaDataProvider

    broker = AlpacaBroker(mode='paper')
    provider = AlpacaDataProvider()

    runner = BotRunner(
        factory, broker, bot_id,
        gate=RiskGate(AccountRiskLimits.from_env(), limits),
        router=OrderRouter(broker, allow_live=False),
    )
    clock = PollingClock(
        target, provider, timeframe, max_ticks=max_ticks
    )

    logger.info(
        'starting bot %s (%s) on %s %s via %s',
        bot_id, name, target, timeframe, provider.name,
    )
    result = runner.run_session(clock)

    print(
        f'bars={result.bars_seen} orders={result.orders_placed} '
        f'blocked={result.orders_blocked} errors={result.errors} '
        f'halted={result.halted}'
    )
    if result.halted:
        print(f'halt reason: {result.halt_reason}', file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog='runner', description='Run one bot over one symbol.'
    )
    parser.add_argument('--bot-id', type=int, help='bot to run')
    parser.add_argument(
        '--symbol',
        help="symbol to trade; defaults to the bot's first configured symbol",
    )
    parser.add_argument(
        '--max-ticks', type=int,
        help='stop after this many bars. Omit to run until stopped.',
    )
    parser.add_argument('--list', action='store_true', help='list configured bots')
    parser.add_argument('--verbose', action='store_true')

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )

    if args.list:
        return list_bots()
    if args.bot_id is None:
        parser.error('one of --bot-id or --list is required')
    return run(args.bot_id, args.symbol, args.max_ticks)


if __name__ == '__main__':
    sys.exit(main())
