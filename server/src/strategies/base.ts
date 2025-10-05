import { Bar, StrategySignal } from '../types';

export interface IStrategy {
  name: string;
  description: string;
  parameters: Record<string, any>;
  analyze(bars: Bar[], currentIndex: number): StrategySignal;
  initialize?(): void;
}

export abstract class BaseStrategy implements IStrategy {
  abstract name: string;
  abstract description: string;
  abstract parameters: Record<string, any>;

  abstract analyze(bars: Bar[], currentIndex: number): StrategySignal;

  initialize?(): void {
    // Optional initialization logic
  }

  // Helper methods for technical indicators
  protected calculateSMA(bars: Bar[], period: number, endIndex: number): number {
    if (endIndex < period - 1) {
      return 0;
    }

    let sum = 0;
    for (let i = endIndex - period + 1; i <= endIndex; i++) {
      sum += bars[i].c;
    }
    return sum / period;
  }

  protected calculateEMA(bars: Bar[], period: number, endIndex: number): number {
    if (endIndex < period - 1) {
      return 0;
    }

    const multiplier = 2 / (period + 1);
    
    // Calculate initial SMA for the first EMA value
    if (endIndex === period - 1) {
      return this.calculateSMA(bars, period, endIndex);
    }

    const previousEMA = this.calculateEMA(bars, period, endIndex - 1);
    return (bars[endIndex].c - previousEMA) * multiplier + previousEMA;
  }

  protected calculateRSI(bars: Bar[], period: number, endIndex: number): number {
    if (endIndex < period) {
      return 50; // Neutral RSI
    }

    let gains = 0;
    let losses = 0;

    for (let i = endIndex - period + 1; i <= endIndex; i++) {
      const change = bars[i].c - bars[i - 1].c;
      if (change > 0) {
        gains += change;
      } else {
        losses += Math.abs(change);
      }
    }

    const avgGain = gains / period;
    const avgLoss = losses / period;

    if (avgLoss === 0) {
      return 100;
    }

    const rs = avgGain / avgLoss;
    return 100 - (100 / (1 + rs));
  }

  protected getHighest(bars: Bar[], period: number, endIndex: number): number {
    let highest = bars[endIndex].h;
    for (let i = Math.max(0, endIndex - period + 1); i <= endIndex; i++) {
      highest = Math.max(highest, bars[i].h);
    }
    return highest;
  }

  protected getLowest(bars: Bar[], period: number, endIndex: number): number {
    let lowest = bars[endIndex].l;
    for (let i = Math.max(0, endIndex - period + 1); i <= endIndex; i++) {
      lowest = Math.min(lowest, bars[i].l);
    }
    return lowest;
  }
}
