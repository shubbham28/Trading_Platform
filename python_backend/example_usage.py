#!/usr/bin/env python3
"""
Example: Using Python Backend for Strategy Backtesting
This script demonstrates how to use the Python backend for backtesting trading strategies
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from strategies import (
    SMACrossoverStrategy,
    RSIMeanReversionStrategy,
    MACDTrendFollowStrategy,
    list_strategies
)
from app.backtest import BacktestEngine, BacktestConfig
from indicators import calculate_all_indicators


def create_sample_data(days=200):
    """Create sample OHLCV data for testing"""
    dates = pd.date_range(start='2023-01-01', periods=days, freq='D')
    np.random.seed(42)
    
    # Generate realistic price movement
    returns = np.random.randn(days) * 0.02
    prices = 100 * np.exp(np.cumsum(returns))
    
    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices * (1 + np.random.uniform(-0.01, 0.01, days)),
        'high': prices * (1 + np.random.uniform(0, 0.02, days)),
        'low': prices * (1 - np.random.uniform(0, 0.02, days)),
        'close': prices,
        'volume': np.random.randint(100000, 1000000, days)
    })
    
    return df


def demo_indicators():
    """Demonstrate technical indicator calculations"""
    print("=" * 60)
    print("DEMO 1: Technical Indicators")
    print("=" * 60)
    
    # Create sample data
    df = create_sample_data(100)
    
    # Calculate all indicators
    df_with_indicators = calculate_all_indicators(df)
    
    # Display last 5 rows with selected indicators
    print("\nLast 5 bars with indicators:")
    cols = ['timestamp', 'close', 'sma_10', 'sma_20', 'rsi', 'macd']
    print(df_with_indicators[cols].tail().to_string(index=False))
    print()


def demo_strategy_list():
    """Demonstrate listing available strategies"""
    print("=" * 60)
    print("DEMO 2: Available Strategies")
    print("=" * 60)
    
    strategies = list_strategies()
    
    for i, strat in enumerate(strategies, 1):
        print(f"\n{i}. {strat['name']} ({strat['id']})")
        print(f"   Description: {strat['description']}")
        print(f"   Parameters: {strat['parameters']}")
    print()


def demo_backtest(strategy_class, strategy_name, parameters):
    """Run and display backtest results"""
    print("=" * 60)
    print(f"BACKTEST: {strategy_name}")
    print("=" * 60)
    
    # Create sample data
    df = create_sample_data(200)
    
    # Create strategy
    strategy = strategy_class(parameters)
    
    # Create backtest config
    config = BacktestConfig(
        symbol='SAMPLE',
        start_date='2023-01-01',
        end_date='2023-07-19',
        initial_capital=10000.0,
        commission=0.001,  # 0.1% commission
        strategy_id=strategy_name,
        parameters=parameters
    )
    
    # Run backtest
    engine = BacktestEngine(config, strategy)
    result = engine.run(df)
    
    # Display results
    print(f"\n📊 Backtest Results")
    print(f"{'='*40}")
    print(f"Symbol:              {result.symbol}")
    print(f"Period:              {result.start_date} to {result.end_date}")
    print(f"Initial Capital:     ${result.initial_capital:,.2f}")
    print(f"Final Capital:       ${result.final_capital:,.2f}")
    print(f"Total Return:        ${result.total_return:,.2f} ({result.total_return_pct:.2f}%)")
    print(f"\n📈 Performance Metrics")
    print(f"{'='*40}")
    print(f"Sharpe Ratio:        {result.sharpe_ratio:.3f}")
    print(f"Sortino Ratio:       {result.sortino_ratio:.3f}")
    print(f"Max Drawdown:        {result.max_drawdown_pct:.2f}%")
    print(f"\n📊 Trade Statistics")
    print(f"{'='*40}")
    print(f"Total Trades:        {result.total_trades}")
    print(f"Winning Trades:      {result.winning_trades}")
    print(f"Losing Trades:       {result.losing_trades}")
    print(f"Win Rate:            {result.win_rate:.2f}%")
    print(f"Average Win:         ${result.avg_win:.2f}")
    print(f"Average Loss:        ${result.avg_loss:.2f}")
    print(f"Profit Factor:       {result.profit_factor:.2f}")
    
    # Show first few trades
    if result.trades:
        print(f"\n🔄 First 3 Trades:")
        print(f"{'='*40}")
        for i, trade in enumerate(result.trades[:3], 1):
            print(f"\nTrade {i}:")
            print(f"  Entry: {trade['entry_time']} @ ${trade['entry_price']:.2f}")
            if trade['exit_time']:
                print(f"  Exit:  {trade['exit_time']} @ ${trade['exit_price']:.2f}")
                print(f"  P&L:   ${trade['pnl']:.2f} ({trade['pnl_pct']:.2f}%)")
    
    print("\n" + "="*60 + "\n")
    return result


def main():
    """Run all demos"""
    print("\n" + "="*60)
    print("Python Trading Backend - Demo Script")
    print("="*60 + "\n")
    
    # Demo 1: Show available indicators
    demo_indicators()
    
    # Demo 2: List strategies
    demo_strategy_list()
    
    # Demo 3: Backtest SMA Crossover
    demo_backtest(
        SMACrossoverStrategy,
        "SMA Crossover",
        {'short_period': 10, 'long_period': 30}
    )
    
    # Demo 4: Backtest RSI Mean Reversion
    demo_backtest(
        RSIMeanReversionStrategy,
        "RSI Mean Reversion",
        {'period': 14, 'oversold': 30, 'overbought': 70}
    )
    
    # Demo 5: Backtest MACD Trend Following
    demo_backtest(
        MACDTrendFollowStrategy,
        "MACD Trend Following",
        {'fast_period': 12, 'slow_period': 26, 'signal_period': 9}
    )
    
    print("✅ All demos completed successfully!")
    print("\nTo run the FastAPI server:")
    print("  uvicorn main:app --reload --port 8000")
    print("\nThen visit: http://localhost:8000/docs")


if __name__ == '__main__':
    main()
