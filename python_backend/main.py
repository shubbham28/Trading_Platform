"""
FastAPI Application
Python backend for trading platform with strategy execution and backtesting
"""
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
from dotenv import load_dotenv

from strategies import get_strategy, list_strategies, STRATEGIES
from indicators import calculate_all_indicators
from app.backtest import BacktestEngine, BacktestConfig, BacktestResult
from app.data_fetcher import DataFetcher
from news_forward_tester import NewsForwardTester, NewsSignal, ForwardTestResult

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

# Initialize news forward tester
news_tester = NewsForwardTester()


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
                    df = data_fetcher.get_bars(symbol, start_date, end_date, "1Day")
                    if not df.empty:
                        market_data[symbol] = df
                except Exception as e:
                    print(f"Could not fetch data for {symbol}: {e}")
        
        # Generate signals
        signals = news_tester.generate_signals(news_data, market_data, request.top_n)
        
        # Save signals
        news_tester.save_signals(signals)
        
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
        signals = news_tester.load_signals(date)
        
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
        result = news_tester.get_latest_results()
        
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
                df = data_fetcher.get_bars(symbol, start_date, end_date, "1Day")
                if not df.empty:
                    market_data[symbol] = df
            except Exception as e:
                print(f"Could not fetch data for {symbol}: {e}")
        
        # Generate signals
        signals = news_tester.generate_signals(news_data, market_data, request.top_n)
        
        # Simulate forward test
        result = news_tester.simulate_forward_test(signals, market_data)
        
        return result.model_dump()
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
