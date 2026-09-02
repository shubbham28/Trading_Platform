"""
FastAPI Application
Python backend for trading platform with strategy execution and backtesting
"""
import logging
import os
from decimal import Decimal
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
from sqlalchemy import text
from dotenv import load_dotenv

from strategies import get_strategy, list_strategies, STRATEGIES
from indicators import calculate_all_indicators
from app.backtest import BacktestEngine, BacktestConfig, BacktestResult
from app.session import build_contexts
from data.base import DataProvider
from db import repository, session_scope
from db.session import database_url, get_engine
from risk.contracts import AccountRiskLimits
from risk.gate import RULES
from db.models import Order
from risk import approvals
from risk import context as risk_context
from runner.reconcile import qty_str, reconcile
from runner.router import OrderRouter
from news_forward_tester import NewsSignal, ForwardTestResult

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Trading Platform Python Backend",
    description="Advanced technical indicator strategies and backtesting engine",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Both of these are built on first use rather than at import.
#
# The data provider raises without Alpaca credentials and the news tester loads a
# FinBERT model, so constructing either at module scope meant the entire app
# failed to import when credentials were absent -- including the /health endpoint
# whose job is to report that. A backend that cannot start cannot tell you why.
_data_provider: Optional[DataProvider] = None
_broker = None
_news_tester = None


def get_data_provider() -> DataProvider:
    """The configured market data provider.

    Behind the DataProvider interface so the feed can be swapped without
    touching strategy or backtest code. Alpaca's free tier is IEX-only, which is
    roughly 2% of consolidated volume -- see docs and TODOS.md.
    """
    global _data_provider
    if _data_provider is None:
        from data.alpaca import AlpacaDataProvider
        _data_provider = AlpacaDataProvider()
    return _data_provider


def get_broker():
    """The configured broker.

    Lazy, like the data provider: constructing it without credentials raises,
    and doing that at import time would stop the app starting rather than let
    /health report the problem.
    """
    global _broker
    if _broker is None:
        from brokers.alpaca import AlpacaBroker
        _broker = AlpacaBroker()
    return _broker


def get_news_tester():
    global _news_tester
    if _news_tester is None:
        from news_forward_tester import NewsForwardTester
        _news_tester = NewsForwardTester()
    return _news_tester


# Request/Response Models
class StrategyRunRequest(BaseModel):
    """Strategy execution request"""
    symbol: str
    strategy_id: str
    start_date: str
    end_date: str
    parameters: Optional[Dict[str, Any]] = {}
    timeframe: str = "1Day"


class BacktestRequest(BaseModel):
    """Backtest request"""
    symbol: str
    strategy_id: str
    start_date: str
    end_date: str
    initial_capital: float = 10000.0
    commission: float = 0.0
    parameters: Optional[Dict[str, Any]] = {}
    timeframe: str = "1Day"


class IndicatorsRequest(BaseModel):
    """Indicators calculation request"""
    symbol: str
    start_date: str
    end_date: str
    timeframe: str = "1Day"


class NewsItem(BaseModel):
    """News item for sentiment analysis"""
    symbol: str
    headline: str
    timestamp: Optional[str] = None


class NewsSignalsRequest(BaseModel):
    """Request for generating news-based signals"""
    news_items: List[NewsItem]
    symbols: Optional[List[str]] = None
    top_n: int = 5


# API Routes
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Trading Platform Python Backend",
        "version": "1.0.0",
        "status": "online"
    }


@app.get("/health")
async def health_check():
    """Health check.

    Reports the database separately from the process. A backend that is running
    but cannot reach Postgres is not healthy in any useful sense: bots would
    evaluate, decide, and lose every record of having done so. Reporting "ok"
    there is the kind of silent failure this system is built to avoid.
    """
    database = {"configured_url": _redacted_database_url()}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("select 1"))
        database["reachable"] = True
    except Exception as exc:
        database["reachable"] = False
        database["error"] = str(exc)

    return {
        "status": "ok" if database["reachable"] else "degraded",
        "timestamp": datetime.now().isoformat(),
        "mode": os.getenv("TRADING_MODE", "paper"),
        "database": database,
    }


def _redacted_database_url() -> str:
    """The database URL with any password removed.

    A health endpoint is usually the least protected route on a service, and a
    connection string with credentials in it is exactly what should not be
    served from one.
    """
    url = database_url()
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    credentials, _, host = rest.rpartition("@")
    user = credentials.split(":", 1)[0] if credentials else ""
    return f"{scheme}://{user}:***@{host}" if user else f"{scheme}://{host}"


@app.get("/indicators")
async def get_indicators_list():
    """Get list of available technical indicators"""
    return {
        "indicators": [
            {
                "id": "sma",
                "name": "Simple Moving Average",
                "description": "Average price over a specific period",
                "parameters": ["period"]
            },
            {
                "id": "ema",
                "name": "Exponential Moving Average",
                "description": "Weighted average giving more importance to recent prices",
                "parameters": ["period"]
            },
            {
                "id": "rsi",
                "name": "Relative Strength Index",
                "description": "Momentum oscillator measuring speed and magnitude of price changes",
                "parameters": ["period"]
            },
            {
                "id": "macd",
                "name": "MACD",
                "description": "Moving Average Convergence Divergence",
                "parameters": ["fast_period", "slow_period", "signal_period"]
            },
            {
                "id": "bollinger_bands",
                "name": "Bollinger Bands",
                "description": "Volatility bands placed above and below a moving average",
                "parameters": ["period", "std_dev"]
            },
            {
                "id": "vwap",
                "name": "VWAP",
                "description": "Volume Weighted Average Price",
                "parameters": []
            },
            {
                "id": "atr",
                "name": "Average True Range",
                "description": "Measure of market volatility",
                "parameters": ["period"]
            },
            {
                "id": "stochastic",
                "name": "Stochastic Oscillator",
                "description": "Momentum indicator comparing closing price to price range",
                "parameters": ["k_period", "d_period"]
            }
        ]
    }


@app.post("/indicators/calculate")
async def calculate_indicators(request: IndicatorsRequest):
    """Calculate all indicators for given symbol and date range"""
    try:
        # Fetch historical data
        df = get_data_provider().get_bars(
            request.symbol,
            request.start_date,
            request.end_date,
            request.timeframe
        )
        
        if df.empty:
            raise HTTPException(status_code=404, detail="No data available for the given period")
        
        # Calculate indicators
        df_with_indicators = calculate_all_indicators(df)
        
        # Convert to JSON-serializable format
        result = df_with_indicators.to_dict(orient='records')
        
        return {
            "symbol": request.symbol,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "timeframe": request.timeframe,
            "data": result
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/strategy/list")
async def get_strategy_list():
    """Get list of available strategies"""
    strategies = list_strategies()
    return {"strategies": strategies}


@app.get("/strategy/{strategy_id}")
async def get_strategy_info(strategy_id: str):
    """Get information about a specific strategy"""
    if strategy_id not in STRATEGIES:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_id}' not found")
    
    strategy = get_strategy(strategy_id)
    return strategy.get_info()


@app.post("/strategy/run")
async def run_strategy(request: StrategyRunRequest):
    """Execute strategy and return signals"""
    try:
        # Get strategy instance
        strategy = get_strategy(request.strategy_id, request.parameters)
        
        # Fetch historical data
        df = get_data_provider().get_bars(
            request.symbol,
            request.start_date,
            request.end_date,
            request.timeframe
        )
        
        if df.empty:
            raise HTTPException(status_code=404, detail="No data available for the given period")
        
        # Generate signals through the same causal path the backtester uses:
        # windows that end at the current bar, calendar-derived context, and no
        # position state held by the strategy. Driving it any other way would
        # report signals the backtest could not reproduce.
        prepared = strategy.prepare(calculate_all_indicators(df))
        contexts = build_contexts(prepared, request.timeframe)
        warmup = strategy.warmup_bars()

        signals = []
        for i in range(len(prepared)):
            if i < warmup:
                continue
            signal = strategy.analyze(prepared.iloc[:i + 1], contexts[i], None)
            signals.append(signal.model_dump())
        
        return {
            "strategy_id": request.strategy_id,
            "symbol": request.symbol,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "signals": signals,
            "total_signals": len(signals),
            "buy_signals": sum(1 for s in signals if s['action'] == 'buy'),
            "sell_signals": sum(1 for s in signals if s['action'] == 'sell'),
            "hold_signals": sum(1 for s in signals if s['action'] == 'hold')
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/backtest/run")
async def run_backtest(request: BacktestRequest) -> BacktestResult:
    """Run backtest and return performance metrics"""
    try:
        # Validate strategy exists
        if request.strategy_id not in STRATEGIES:
            raise HTTPException(status_code=404, detail=f"Strategy '{request.strategy_id}' not found")
        
        # Get strategy instance
        strategy = get_strategy(request.strategy_id, request.parameters)
        
        # Fetch historical data
        df = get_data_provider().get_bars(
            request.symbol,
            request.start_date,
            request.end_date,
            request.timeframe
        )
        
        if df.empty:
            raise HTTPException(status_code=404, detail="No data available for the given period")
        
        # Create backtest config
        config = BacktestConfig(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            commission=request.commission,
            strategy_id=request.strategy_id,
            parameters=request.parameters or {},
            timeframe=request.timeframe,
        )
        
        # Run backtest
        engine = BacktestEngine(config, strategy)
        result = engine.run(df)

        return _persist_backtest(result)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BotRequest(BaseModel):
    """A bot is a config record, which is what makes a new bot not a code change."""
    name: str
    strategy_id: str
    symbols: List[str]
    timeframe: str = "1Day"
    capital_budget: float
    parameters: Dict[str, Any] = {}
    risk_limits: Dict[str, Any] = {}
    mode: str = "paper"
    enabled: bool = False


def _bot_json(bot) -> dict:
    return {
        "id": bot.id,
        "name": bot.name,
        "enabled": bot.enabled,
        "strategy_id": bot.strategy_id,
        "parameters": bot.parameters,
        "symbols": bot.symbols,
        "timeframe": bot.timeframe,
        "capital_budget": float(bot.capital_budget),
        "risk_limits": bot.risk_limits,
        "mode": bot.mode,
        "created_at": bot.created_at.isoformat(),
    }


@app.get("/bots")
async def list_bots(enabled_only: bool = False):
    try:
        with session_scope() as session:
            return {
                "bots": [
                    _bot_status(session, b)
                    for b in repository.list_bots(session, enabled_only=enabled_only)
                ]
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.post("/bots")
async def create_bot(request: BotRequest):
    """Create a bot.

    Validates the strategy id and its parameters before storing anything. A bot
    row naming a strategy that does not exist, or carrying parameters that
    strategy rejects, is a bot that fails at the first bar of a live session
    rather than here.
    """
    if request.strategy_id not in STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown strategy {request.strategy_id!r}. "
                f"Available: {sorted(STRATEGIES)}"
            ),
        )
    try:
        STRATEGIES[request.strategy_id].validate_parameters(request.parameters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {exc}")

    if not request.symbols:
        raise HTTPException(status_code=400, detail="A bot needs at least one symbol")
    if request.mode not in ("paper", "live"):
        raise HTTPException(status_code=400, detail="mode must be paper or live")

    try:
        with session_scope() as session:
            if repository.get_bot_by_name(session, request.name) is not None:
                raise HTTPException(
                    status_code=409, detail=f"A bot named {request.name!r} exists"
                )
            bot = repository.create_bot(
                session,
                name=request.name,
                strategy_id=request.strategy_id,
                parameters=request.parameters,
                symbols=request.symbols,
                timeframe=request.timeframe,
                capital_budget=Decimal(str(request.capital_budget)),
                risk_limits=request.risk_limits,
                mode=request.mode,
                enabled=request.enabled,
            )
            return _bot_json(bot)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


class BotUpdateRequest(BaseModel):
    """Partial update. Omitted fields are left alone.

    Every field optional on purpose: tuning one parameter must not blank out the
    rest of the record by omission.
    """
    enabled: Optional[bool] = None
    parameters: Optional[Dict[str, Any]] = None
    risk_limits: Optional[Dict[str, Any]] = None
    capital_budget: Optional[float] = None
    symbols: Optional[List[str]] = None
    timeframe: Optional[str] = None


class BotCloneRequest(BaseModel):
    name: str
    parameters: Optional[Dict[str, Any]] = None
    capital_budget: Optional[float] = None
    symbols: Optional[List[str]] = None


# How long without any audit activity before a bot is reported as having no
# runner attached. Generous relative to a one-minute bar, because a bot that
# holds through a quiet stretch still writes a signal row every bar.
RUNNER_STALE_SECONDS = 180


def _bot_status(session, bot) -> dict:
    """A bot's record plus what it is actually doing.

    `enabled` records intent only. A bot can be enabled with no runner process
    running anywhere, and a UI that showed that as "live" would be lying about
    the most important thing on the screen -- so last activity is reported
    alongside it and the two are distinguished.
    """
    from datetime import timezone as _tz

    last_seen = repository.last_activity_at(session, bot.id)
    positions = repository.bot_open_positions(session, bot.id)

    baseline = risk_context.start_of_day_equity(session, bot_id=bot.id)
    latest = risk_context.latest_equity(session, bot_id=bot.id)
    daily_pnl = (
        float(latest - baseline)
        if baseline is not None and latest is not None else None
    )

    age = None
    if last_seen is not None:
        seen = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=_tz.utc)
        age = (datetime.now(_tz.utc) - seen).total_seconds()

    return {
        **_bot_json(bot),
        "last_activity_at": last_seen.isoformat() if last_seen else None,
        "seconds_since_activity": age,
        # Enabled and running are different facts. Reported separately.
        "runner_attached": bool(
            bot.enabled and age is not None and age < RUNNER_STALE_SECONDS
        ),
        "open_positions": [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "entry_price": float(p.entry_price),
                "entry_time": p.entry_time.isoformat(),
            }
            for p in positions
        ],
        # None, not zero, when there is no baseline. The daily-loss rules block
        # every opening order in that state, so it must not look like "flat".
        "daily_pnl": daily_pnl,
        "blocked_orders_by_rule": repository.blocked_order_counts(session, bot.id),
    }


@app.get("/bots/{bot_id}")
async def get_bot(bot_id: int):
    try:
        with session_scope() as session:
            bot = repository.get_bot(session, bot_id)
            if bot is None:
                raise HTTPException(status_code=404, detail="Bot not found")
            return _bot_status(session, bot)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.patch("/bots/{bot_id}")
async def update_bot(bot_id: int, request: BotUpdateRequest):
    """Tune or enable a bot.

    Parameters are validated against the strategy before they are stored, so an
    invalid tuning is refused here rather than at the first bar of the next
    session.
    """
    try:
        with session_scope() as session:
            bot = repository.get_bot(session, bot_id)
            if bot is None:
                raise HTTPException(status_code=404, detail="Bot not found")

            if request.parameters is not None:
                try:
                    STRATEGIES[bot.strategy_id].validate_parameters(request.parameters)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid parameters: {exc}"
                    )

            if request.symbols is not None and not request.symbols:
                raise HTTPException(
                    status_code=400, detail="A bot needs at least one symbol"
                )

            repository.update_bot(
                session, bot,
                enabled=request.enabled,
                parameters=request.parameters,
                risk_limits=request.risk_limits,
                capital_budget=(
                    Decimal(str(request.capital_budget))
                    if request.capital_budget is not None else None
                ),
                symbols=request.symbols,
                timeframe=request.timeframe,
            )
            repository.append_audit(
                session, event_type="bot_updated",
                payload={
                    k: v for k, v in request.model_dump().items() if v is not None
                },
                bot_id=bot.id,
            )
            return _bot_status(session, bot)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.post("/bots/{bot_id}/clone")
async def clone_bot(bot_id: int, request: BotCloneRequest):
    """Copy a bot under a new name so it can be retuned and run alongside.

    The clone comes back disabled whatever the original's state. A clone exists
    to be retuned before it trades; one that started enabled would be trading
    the parent's parameters against the same account before anyone looked.
    """
    try:
        with session_scope() as session:
            bot = repository.get_bot(session, bot_id)
            if bot is None:
                raise HTTPException(status_code=404, detail="Bot not found")
            if repository.get_bot_by_name(session, request.name) is not None:
                raise HTTPException(
                    status_code=409, detail=f"A bot named {request.name!r} exists"
                )

            if request.parameters is not None:
                try:
                    STRATEGIES[bot.strategy_id].validate_parameters(request.parameters)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid parameters: {exc}"
                    )

            clone = repository.clone_bot(
                session, bot, name=request.name,
                parameters=request.parameters,
                symbols=request.symbols,
                capital_budget=(
                    Decimal(str(request.capital_budget))
                    if request.capital_budget is not None else None
                ),
            )
            return _bot_json(clone)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.delete("/bots/{bot_id}")
async def delete_bot(bot_id: int):
    """Delete a bot. Refused while it holds a position.

    `positions` cascades on delete, so removing a bot mid-position would drop
    our record of it while the broker carries on holding the real thing --
    a live position nothing in the system knows about. Flatten first.
    """
    try:
        with session_scope() as session:
            bot = repository.get_bot(session, bot_id)
            if bot is None:
                raise HTTPException(status_code=404, detail="Bot not found")

            held = repository.bot_open_positions(session, bot.id)
            if held:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Bot holds "
                        + ", ".join(f"{p.qty} {p.symbol}" for p in held)
                        + ". Deleting it would drop our record while the broker "
                        "keeps the position. Flatten it first."
                    ),
                )

            repository.append_audit(
                session, event_type="bot_deleted",
                payload={"name": bot.name, "strategy_id": bot.strategy_id},
                bot_id=None,
            )
            session.delete(bot)
            return {"deleted": bot_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


class LiveSettingsRequest(BaseModel):
    """Change the live-trading posture. Omitted fields are left alone."""
    auto_approve: Optional[bool] = None
    max_order_value: Optional[float] = None
    approval_timeout_seconds: Optional[int] = None
    note: Optional[str] = None


class ApprovalDecisionRequest(BaseModel):
    note: Optional[str] = None


def _live_settings_json(settings) -> dict:
    return {
        "auto_approve": settings.auto_approve,
        "auto_approve_note": settings.auto_approve_note,
        "auto_approve_enabled_at": (
            settings.auto_approve_enabled_at.isoformat()
            if settings.auto_approve_enabled_at else None
        ),
        "max_order_value": float(settings.max_order_value),
        "approval_timeout_seconds": settings.approval_timeout_seconds,
        "updated_at": settings.updated_at.isoformat(),
        # Spelled out so a UI never has to infer the posture from a flag plus a
        # number. Zero ceiling means live trading is off, whatever the flag says.
        "live_trading_permitted": float(settings.max_order_value) > 0,
    }


def _approval_json(order, timeout_seconds: int) -> dict:
    from datetime import timezone as _tz

    requested = order.approval_requested_at
    age = None
    if requested is not None:
        stamp = requested if requested.tzinfo else requested.replace(tzinfo=_tz.utc)
        age = (datetime.now(_tz.utc) - stamp).total_seconds()

    return {
        "order_id": order.id,
        "bot_id": order.bot_id,
        "symbol": order.symbol,
        "side": order.side,
        "qty": float(order.qty),
        "order_type": order.order_type,
        "reason": order.reason,
        "bar_timestamp": (
            order.bar_timestamp.isoformat() if order.bar_timestamp else None
        ),
        "requested_at": requested.isoformat() if requested else None,
        "age_seconds": age,
        # How long is left before this expires unapproved. Shown because a
        # request nobody can act on in time is not really a request.
        "expires_in_seconds": (
            max(0.0, timeout_seconds - age) if age is not None else None
        ),
    }


@app.get("/live/settings")
async def read_live_settings():
    """The standing posture for live orders.

    Distinct from the kill switch: that is an emergency stop for everything,
    this is whether live orders need a person and how large one may be.
    """
    try:
        with session_scope() as session:
            return _live_settings_json(approvals.get_live_settings(session))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.post("/live/settings")
async def write_live_settings(request: LiveSettingsRequest):
    """Change the live-trading posture.

    Enabling `auto_approve` requires a note, because it removes the only human
    check on live orders. Disabling it does not -- turning a safety check back on
    must never be harder than turning it off.
    """
    try:
        with session_scope() as session:
            try:
                settings = approvals.update_live_settings(
                    session,
                    auto_approve=request.auto_approve,
                    max_order_value=(
                        Decimal(str(request.max_order_value))
                        if request.max_order_value is not None else None
                    ),
                    approval_timeout_seconds=request.approval_timeout_seconds,
                    note=request.note,
                )
            except approvals.ApprovalError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            return _live_settings_json(settings)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.get("/approvals")
async def list_approvals():
    """Live orders waiting for a person, oldest first.

    Stale requests are expired before the list is built, so everything returned
    can actually be approved. A queue showing unapprovable rows invites someone
    to try, and the failure would come at the click rather than on the screen.
    """
    try:
        with session_scope() as session:
            settings = approvals.get_live_settings(session)
            pending = approvals.pending_approvals(session)
            return {
                "count": len(pending),
                "approval_timeout_seconds": settings.approval_timeout_seconds,
                "auto_approve": settings.auto_approve,
                "approvals": [
                    _approval_json(order, settings.approval_timeout_seconds)
                    for order in pending
                ],
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.post("/approvals/{order_id}/approve")
async def approve_order(order_id: int, request: ApprovalDecisionRequest):
    """Approve a live order and put it on the wire.

    The approval is committed before the submission is attempted, so an order
    recorded as approved that the broker then refused is distinguishable from one
    that was never approved at all.
    """
    try:
        broker = get_broker()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Broker unavailable: {exc}")

    try:
        with session_scope() as session:
            try:
                order = approvals.approve(session, order_id, note=request.note)
            except approvals.ApprovalError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            order_id_value = order.id

        with session_scope() as session:
            order = session.get(Order, order_id_value)
            router = OrderRouter(broker, allow_live=True)
            submitted, refusal = router.submit_approved(session, order)
            return {
                "order_id": order_id_value,
                "status": submitted.status if submitted else "unknown",
                "broker_order_id": submitted.broker_order_id if submitted else None,
                "refusal": refusal,
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not submit: {exc}")


@app.post("/approvals/{order_id}/reject")
async def reject_order(order_id: int, request: ApprovalDecisionRequest):
    """Refuse a live order. It never reaches the broker."""
    try:
        with session_scope() as session:
            try:
                order = approvals.deny(session, order_id, note=request.note)
            except approvals.ApprovalError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            return {"order_id": order.id, "status": order.status}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.get("/audit")
async def read_audit(
    limit: int = 200,
    bot_id: Optional[int] = None,
    event_type: Optional[str] = None,
):
    """The audit log, newest first.

    The whole log, not just risk decisions: signals, orders, fills,
    reconciliations, halts and configuration changes all land here, and the
    question "what happened at 10:31?" needs all of them in one place.
    """
    try:
        with session_scope() as session:
            entries = repository.recent_audit(
                session, limit=min(limit, 1000), bot_id=bot_id,
                event_type=event_type,
            )
            return {
                "count": len(entries),
                "entries": [
                    {
                        "id": e.id,
                        "occurred_at": e.occurred_at.isoformat(),
                        "bot_id": e.bot_id,
                        "event_type": e.event_type,
                        "symbol": e.symbol,
                        "payload": e.payload,
                    }
                    for e in entries
                ],
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.get("/reconciliation")
async def read_reconciliation():
    """Compare local positions against the broker's, without acting.

    Read-only: `halt_on_divergence` is off, so checking from a dashboard cannot
    disable a bot as a side effect of someone refreshing a page.
    """
    try:
        broker = get_broker()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Broker unavailable: {exc}")

    try:
        with session_scope() as session:
            result = reconcile(session, broker, halt_on_divergence=False)
            return {
                "in_sync": result.in_sync,
                "summary": result.describe(),
                "divergences": [
                    {
                        "symbol": d.symbol,
                        "broker_qty": qty_str(d.broker_qty),
                        "local_qty": qty_str(d.local_qty),
                        "difference": qty_str(d.difference),
                        "bot_ids": list(d.bot_ids),
                    }
                    for d in result.divergences
                ],
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


class KillSwitchRequest(BaseModel):
    """Engage or release the kill switch."""
    engaged: bool
    reason: Optional[str] = None


@app.get("/risk/kill-switch")
async def read_kill_switch():
    """Current kill switch state.

    Always answers. A missing row is reported as disengaged only because
    `get_kill_switch` creates it that way -- the caller never has to interpret
    an absent record, which is how "we could not tell" becomes "it is fine".
    """
    try:
        with session_scope() as session:
            switch = repository.get_kill_switch(session)
            return {
                "engaged": switch.engaged,
                "reason": switch.reason,
                "engaged_at": (
                    switch.engaged_at.isoformat() if switch.engaged_at else None
                ),
                "updated_at": switch.updated_at.isoformat(),
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.post("/risk/kill-switch")
async def write_kill_switch(request: KillSwitchRequest):
    """Engage or release the kill switch.

    Engaging it stops every bot opening anything, immediately, without a
    restart -- the gate reads this row before every order. Position-reducing
    orders still pass, because the point is for bots to flatten and stop rather
    than to freeze holding whatever they happen to have.

    The change is written to the audit log, because "who turned this off and
    when" is the first question after an incident.
    """
    try:
        with session_scope() as session:
            switch = repository.set_kill_switch(
                session, request.engaged, reason=request.reason
            )
            repository.append_audit(
                session,
                event_type="kill_switch",
                payload={"engaged": request.engaged, "reason": request.reason},
            )
            return {
                "engaged": switch.engaged,
                "reason": switch.reason,
                "engaged_at": (
                    switch.engaged_at.isoformat() if switch.engaged_at else None
                ),
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.get("/risk/rules")
async def read_risk_rules():
    """The rules in force, in the order they are evaluated.

    Order is part of the contract, not a detail: it decides which rule a blocked
    order is attributed to, which is what an operator acts on.
    """
    limits = AccountRiskLimits.from_env()
    return {
        "account_limits": limits.model_dump(),
        "rules": [
            {"tier": tier, "name": name, "description": (fn.__doc__ or "").strip()}
            for tier, name, fn in RULES
        ],
        "note": (
            "Every rule restricts orders that increase exposure. None of them "
            "can block an order that reduces or closes a position."
        ),
    }


@app.get("/risk/decisions")
async def read_risk_decisions(
    limit: int = 100,
    bot_id: Optional[int] = None,
):
    """Recent gate decisions, newest first.

    Includes the passes, not just the refusals. "Why did this bot do nothing all
    afternoon?" is unanswerable from refusals alone -- it cannot distinguish a
    blocked bot from one that never had a signal.
    """
    try:
        with session_scope() as session:
            entries = repository.recent_audit(
                session, limit=min(limit, 500), bot_id=bot_id,
                event_type="risk_decision",
            )
            return {
                "count": len(entries),
                "decisions": [
                    {
                        "id": e.id,
                        "occurred_at": e.occurred_at.isoformat(),
                        "bot_id": e.bot_id,
                        "symbol": e.symbol,
                        "allowed": e.payload.get("allowed"),
                        "rule": e.payload.get("rule"),
                        "tier": e.payload.get("tier"),
                        "detail": e.payload.get("detail"),
                        "is_reducing": e.payload.get("is_reducing"),
                    }
                    for e in entries
                ],
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


def _persist_backtest(result: BacktestResult) -> BacktestResult:
    """Store a completed run and record whether the store succeeded.

    A failed write does not fail the request: the backtest already ran and its
    numbers are valid. But it must not be reported as if it were saved, so the
    outcome travels back with the result rather than only into a log nobody reads.
    """
    try:
        with session_scope() as session:
            run = repository.save_backtest_run(session, result)
            run_id = run.id
        return result.model_copy(update={'run_id': run_id, 'persisted': True})
    except Exception as exc:
        logger.warning('Failed to persist backtest run: %s', exc)
        return result.model_copy(
            update={'persisted': False, 'persistence_error': str(exc)}
        )


@app.get("/backtest/runs")
async def list_backtest_runs(
    strategy_id: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 50,
    before_id: Optional[int] = None,
):
    """Stored runs, newest first.

    Paged by `before_id` rather than an offset so paging stays fast however many
    runs accumulate.
    """
    try:
        with session_scope() as session:
            runs = repository.list_backtest_runs(
                session, strategy_id=strategy_id, symbol=symbol,
                limit=min(limit, 200), before_id=before_id,
            )
            return {
                "runs": [
                    {
                        "id": r.id,
                        "strategy_id": r.strategy_id,
                        "symbol": r.symbol,
                        "timeframe": r.timeframe,
                        "start_date": r.start_date.isoformat(),
                        "end_date": r.end_date.isoformat(),
                        "parameters": r.parameters,
                        # Costs travel with every summary. A return figure
                        # without its slippage and sizing is not comparable to
                        # the run next to it.
                        "config": r.config,
                        "metrics": r.metrics,
                        "audit": r.audit,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in runs
                ],
                "count": len(runs),
                "next_before_id": runs[-1].id if runs else None,
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.get("/backtest/runs/{run_id}")
async def get_backtest_run(run_id: int):
    """One stored run, with its trades. The equity curve has its own endpoint."""
    try:
        with session_scope() as session:
            run = repository.get_backtest_run(session, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="Backtest run not found")
            return {
                "id": run.id,
                "strategy_id": run.strategy_id,
                "symbol": run.symbol,
                "timeframe": run.timeframe,
                "start_date": run.start_date.isoformat(),
                "end_date": run.end_date.isoformat(),
                "parameters": run.parameters,
                "config": run.config,
                "metrics": run.metrics,
                "audit": run.audit,
                "trades": run.trades,
                "created_at": run.created_at.isoformat(),
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.get("/backtest/runs/{run_id}/equity")
async def get_backtest_equity(run_id: int, limit: Optional[int] = None):
    """A run's equity curve.

    Separate from the run itself because a year of one-minute bars is roughly
    98,000 points, and returning that inside every run lookup would make listing
    runs unusable.
    """
    try:
        with session_scope() as session:
            points = repository.equity_curve_for_run(session, run_id, limit=limit)
            return {
                "run_id": run_id,
                "count": len(points),
                "equity_curve": [
                    {
                        "bar_index": p.bar_index,
                        "timestamp": p.timestamp.isoformat(),
                        "equity": float(p.equity),
                        "drawdown": float(p.drawdown),
                    }
                    for p in points
                ],
            }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.post("/forward/news/signals")
async def generate_news_signals(request: NewsSignalsRequest):
    """Generate trading signals based on news sentiment"""
    try:
        # Convert request news items to dict format
        news_data = [item.model_dump() for item in request.news_items]
        
        # Optionally fetch market data for volume analysis
        market_data = {}
        if request.symbols:
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            
            for symbol in request.symbols:
                try:
                    df = get_data_provider().get_bars(symbol, start_date, end_date, "1Day")
                    if not df.empty:
                        market_data[symbol] = df
                except Exception as e:
                    print(f"Could not fetch data for {symbol}: {e}")
        
        # Generate signals
        signals = get_news_tester().generate_signals(news_data, market_data, request.top_n)
        
        # Save signals
        get_news_tester().save_signals(signals)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_signals": len(signals),
            "signals": [s.model_dump() for s in signals]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/forward/news/signals")
async def get_latest_news_signals(date: Optional[str] = None):
    """Get latest news-based trading signals"""
    try:
        signals = get_news_tester().load_signals(date)
        
        if signals is None:
            raise HTTPException(status_code=404, detail="No signals found for the specified date")
        
        return {
            "date": date or datetime.now().strftime('%Y-%m-%d'),
            "total_signals": len(signals),
            "signals": [s.model_dump() for s in signals]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/forward/news/results")
async def get_forward_test_results():
    """Get latest forward test results"""
    try:
        result = get_news_tester().get_latest_results()
        
        if result is None:
            raise HTTPException(status_code=404, detail="No forward test results found")
        
        return result.model_dump()
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/forward/news/simulate")
async def simulate_forward_test(request: NewsSignalsRequest):
    """Simulate forward test based on news signals"""
    try:
        # Generate signals first
        news_data = [item.model_dump() for item in request.news_items]
        
        # Fetch market data
        market_data = {}
        symbols = request.symbols or list(set(item.symbol for item in request.news_items))
        
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        for symbol in symbols:
            try:
                df = get_data_provider().get_bars(symbol, start_date, end_date, "1Day")
                if not df.empty:
                    market_data[symbol] = df
            except Exception as e:
                print(f"Could not fetch data for {symbol}: {e}")
        
        # Generate signals
        signals = get_news_tester().generate_signals(news_data, market_data, request.top_n)
        
        # Simulate forward test
        result = get_news_tester().simulate_forward_test(signals, market_data)
        
        return result.model_dump()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
