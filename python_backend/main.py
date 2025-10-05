"""
FastAPI Application
Python backend for trading platform with strategy execution and backtesting
"""
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
from dotenv import load_dotenv

from strategies import get_strategy, list_strategies, STRATEGIES
from indicators import calculate_all_indicators
from app.backtest import BacktestEngine, BacktestConfig, BacktestResult
from app.data_fetcher import DataFetcher

# Load environment variables
load_dotenv()

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

# Initialize data fetcher
data_fetcher = DataFetcher()


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
    """Health check endpoint"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "mode": os.getenv("TRADING_MODE", "paper")
    }


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
        df = data_fetcher.get_bars(
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
        df = data_fetcher.get_bars(
            request.symbol,
            request.start_date,
            request.end_date,
            request.timeframe
        )
        
        if df.empty:
            raise HTTPException(status_code=404, detail="No data available for the given period")
        
        # Generate signals
        signals = []
        for i in range(len(df)):
            signal = strategy.analyze(df, i)
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
        df = data_fetcher.get_bars(
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
            parameters=request.parameters or {}
        )
        
        # Run backtest
        engine = BacktestEngine(config, strategy)
        result = engine.run(df)
        
        return result
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
