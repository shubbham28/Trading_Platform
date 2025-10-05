import { Bar, BacktestResult, Trade, EquityPoint } from '../types';
import { IStrategy } from '../strategies';

export interface BacktestConfig {
  symbol: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
  strategy: IStrategy;
  commission?: number; // Commission per trade
}

export class BacktestEngine {
  private config: BacktestConfig;
  private capital: number;
  private position: number = 0; // Number of shares held
  private trades: Trade[] = [];
  private equityCurve: EquityPoint[] = [];

  constructor(config: BacktestConfig) {
    this.config = config;
    this.capital = config.initialCapital;
  }

  async run(bars: Bar[]): Promise<BacktestResult> {
    if (bars.length === 0) {
      throw new Error('No bars provided for backtest');
    }

    // Initialize strategy if needed
    if (this.config.strategy.initialize) {
      this.config.strategy.initialize();
    }

    let peakEquity = this.config.initialCapital;
    let maxDrawdown = 0;

    // Simulate trading
    for (let i = 0; i < bars.length; i++) {
      const bar = bars[i];
      const signal = this.config.strategy.analyze(bars, i);

      // Calculate current equity
      const currentEquity = this.capital + this.position * bar.c;
      
      // Update max drawdown
      if (currentEquity > peakEquity) {
        peakEquity = currentEquity;
      }
      const drawdown = (peakEquity - currentEquity) / peakEquity;
      maxDrawdown = Math.max(maxDrawdown, drawdown);

      // Record equity curve
      this.equityCurve.push({
        timestamp: bar.t,
        equity: currentEquity,
        drawdown,
      });

      // Execute trade based on signal
      if (signal.action === 'buy' && this.position === 0 && signal.confidence > 0.5) {
        this.executeBuy(bar);
      } else if (signal.action === 'sell' && this.position > 0 && signal.confidence > 0.5) {
        this.executeSell(bar);
      }
    }

    // Close any remaining position at the end
    if (this.position > 0) {
      const lastBar = bars[bars.length - 1];
      this.executeSell(lastBar, 'End of backtest');
    }

    return this.generateReport();
  }

  private executeBuy(bar: Bar, reason?: string): void {
    const commission = this.config.commission || 0;
    const price = bar.c;
    const quantity = Math.floor((this.capital - commission) / price);

    if (quantity <= 0) {
      return; // Not enough capital to buy
    }

    const totalCost = quantity * price + commission;
    this.capital -= totalCost;
    this.position += quantity;

    this.trades.push({
      timestamp: bar.t,
      action: 'buy',
      symbol: this.config.symbol,
      quantity,
      price,
      value: totalCost,
      reason: reason || 'Strategy signal',
    });
  }

  private executeSell(bar: Bar, reason?: string): void {
    if (this.position <= 0) {
      return;
    }

    const commission = this.config.commission || 0;
    const price = bar.c;
    const quantity = this.position;
    const totalValue = quantity * price - commission;

    this.capital += totalValue;
    this.position = 0;

    this.trades.push({
      timestamp: bar.t,
      action: 'sell',
      symbol: this.config.symbol,
      quantity,
      price,
      value: totalValue,
      reason: reason || 'Strategy signal',
    });
  }

  private generateReport(): BacktestResult {
    const finalEquity = this.capital + this.position * (this.trades[this.trades.length - 1]?.price || 0);
    const totalReturn = finalEquity - this.config.initialCapital;
    const totalReturnPct = (totalReturn / this.config.initialCapital) * 100;

    // Calculate Sharpe ratio (simplified)
    const returns = this.equityCurve.map((point, i) => {
      if (i === 0) return 0;
      return (point.equity - this.equityCurve[i - 1].equity) / this.equityCurve[i - 1].equity;
    });
    const avgReturn = returns.reduce((a, b) => a + b, 0) / returns.length;
    const stdDev = Math.sqrt(
      returns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / returns.length
    );
    const sharpeRatio = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0; // Annualized

    // Calculate win rate
    const buyTrades = this.trades.filter(t => t.action === 'buy');
    const sellTrades = this.trades.filter(t => t.action === 'sell');
    let winningTrades = 0;
    let losingTrades = 0;

    for (let i = 0; i < sellTrades.length; i++) {
      if (buyTrades[i]) {
        const profit = sellTrades[i].value - buyTrades[i].value;
        if (profit > 0) {
          winningTrades++;
        } else {
          losingTrades++;
        }
      }
    }

    const totalTrades = winningTrades + losingTrades;
    const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;

    // Find max drawdown
    const maxDrawdown = Math.max(...this.equityCurve.map(p => p.drawdown));

    return {
      strategy_id: this.config.strategy.name,
      symbol: this.config.symbol,
      start_date: this.config.startDate,
      end_date: this.config.endDate,
      initial_capital: this.config.initialCapital,
      final_capital: finalEquity,
      total_return: totalReturn,
      total_return_pct: totalReturnPct,
      sharpe_ratio: sharpeRatio,
      max_drawdown: maxDrawdown,
      total_trades: this.trades.length,
      winning_trades: winningTrades,
      losing_trades: losingTrades,
      win_rate: winRate,
      trades: this.trades,
      equity_curve: this.equityCurve,
    };
  }
}
