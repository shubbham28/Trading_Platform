"""
Backtesting Engine
Simulates strategy execution on historical data and computes performance metrics
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np
from pydantic import BaseModel

from strategies.base import BaseStrategy, Signal, Trade


class BacktestConfig(BaseModel):
    """Backtest configuration"""
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float = 10000.0
    commission: float = 0.0
    strategy_id: str
    parameters: Dict[str, Any] = {}


class EquityPoint(BaseModel):
    """Equity curve data point"""
    timestamp: datetime
    equity: float
    drawdown: float


class BacktestResult(BaseModel):
    """Backtest results"""
    strategy_id: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    trades: List[Dict[str, Any]]
    equity_curve: List[Dict[str, Any]]


class BacktestEngine:
    """Backtesting engine for strategy evaluation"""
    
    def __init__(self, config: BacktestConfig, strategy: BaseStrategy):
        """
        Initialize backtest engine
        
        Args:
            config: Backtest configuration
            strategy: Strategy instance to test
        """
        self.config = config
        self.strategy = strategy
        self.capital = config.initial_capital
        self.position = 0  # Number of shares held
        self.trades: List[Trade] = []
        self.equity_curve: List[EquityPoint] = []
        self.current_trade: Optional[Trade] = None
    
    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        Run backtest simulation
        
        Args:
            df: DataFrame with OHLCV data
        
        Returns:
            Backtest results
        """
        if df.empty:
            raise ValueError("No data provided for backtest")
        
        peak_equity = self.config.initial_capital
        
        # Simulate trading
        for i in range(len(df)):
            bar = df.iloc[i]
            signal = self.strategy.analyze(df, i)
            
            # Calculate current equity
            current_equity = self.capital + self.position * bar['close']
            
            # Update drawdown
            if current_equity > peak_equity:
                peak_equity = current_equity
            drawdown = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0
            
            # Record equity point
            self.equity_curve.append(EquityPoint(
                timestamp=bar['timestamp'],
                equity=current_equity,
                drawdown=drawdown
            ))
            
            # Execute trades based on signal
            if signal.action == 'buy' and self.position == 0:
                self._execute_buy(bar, signal.reason)
            elif signal.action == 'sell' and self.position > 0:
                self._execute_sell(bar, signal.reason)
        
        # Close any open position at the end
        if self.position > 0:
            final_bar = df.iloc[-1]
            self._execute_sell(final_bar, "End of backtest period")
        
        return self._generate_report()
    
    def _execute_buy(self, bar: pd.Series, reason: str):
        """Execute buy order"""
        # Calculate quantity based on available capital
        price = bar['close']
        max_shares = int(self.capital / price)
        
        if max_shares > 0:
            commission = self.config.commission * max_shares * price
            total_cost = max_shares * price + commission
            
            if total_cost <= self.capital:
                self.capital -= total_cost
                self.position = max_shares
                
                # Record trade entry
                self.current_trade = Trade(
                    entry_time=bar['timestamp'],
                    entry_price=price,
                    quantity=max_shares,
                    side='long',
                    reason=reason
                )
    
    def _execute_sell(self, bar: pd.Series, reason: str):
        """Execute sell order"""
        if self.position > 0 and self.current_trade:
            price = bar['close']
            commission = self.config.commission * self.position * price
            proceeds = self.position * price - commission
            
            self.capital += proceeds
            
            # Complete trade record
            pnl = (price - self.current_trade.entry_price) * self.position - (commission * 2)
            pnl_pct = (price - self.current_trade.entry_price) / self.current_trade.entry_price * 100
            
            completed_trade = Trade(
                entry_time=self.current_trade.entry_time,
                entry_price=self.current_trade.entry_price,
                exit_time=bar['timestamp'],
                exit_price=price,
                quantity=self.position,
                side='long',
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason
            )
            
            self.trades.append(completed_trade)
            self.position = 0
            self.current_trade = None
    
    def _generate_report(self) -> BacktestResult:
        """Generate backtest report with performance metrics"""
        final_equity = self.capital + self.position * self.equity_curve[-1].equity if self.equity_curve else self.capital
        
        # Calculate returns
        total_return = final_equity - self.config.initial_capital
        total_return_pct = (total_return / self.config.initial_capital) * 100
        
        # Trade statistics
        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if t.pnl and t.pnl > 0)
        losing_trades = sum(1 for t in self.trades if t.pnl and t.pnl < 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Average win/loss
        wins = [t.pnl for t in self.trades if t.pnl and t.pnl > 0]
        losses = [abs(t.pnl) for t in self.trades if t.pnl and t.pnl < 0]
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        
        # Profit factor
        total_wins = sum(wins) if wins else 0
        total_losses = sum(losses) if losses else 1
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Calculate Sharpe ratio
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                ret = (self.equity_curve[i].equity - self.equity_curve[i-1].equity) / self.equity_curve[i-1].equity
                returns.append(ret)
            
            if returns:
                sharpe_ratio = (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0
                
                # Sortino ratio (downside deviation)
                downside_returns = [r for r in returns if r < 0]
                downside_std = np.std(downside_returns) if downside_returns else 0
                sortino_ratio = (np.mean(returns) / downside_std) * np.sqrt(252) if downside_std > 0 else 0
            else:
                sharpe_ratio = 0
                sortino_ratio = 0
        else:
            sharpe_ratio = 0
            sortino_ratio = 0
        
        # Max drawdown
        max_drawdown = max([ep.drawdown for ep in self.equity_curve]) if self.equity_curve else 0
        max_drawdown_pct = max_drawdown * 100
        
        return BacktestResult(
            strategy_id=self.config.strategy_id,
            symbol=self.config.symbol,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_capital=self.config.initial_capital,
            final_capital=final_equity,
            total_return=total_return,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            trades=[t.model_dump() for t in self.trades],
            equity_curve=[ep.model_dump() for ep in self.equity_curve]
        )
