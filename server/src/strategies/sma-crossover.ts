import { BaseStrategy } from './base';
import { Bar, StrategySignal } from '../types';

export class SMACrossoverStrategy extends BaseStrategy {
  name = 'SMA Crossover';
  description = 'Simple Moving Average crossover strategy - buy when short SMA crosses above long SMA';
  
  parameters = {
    shortPeriod: 10,
    longPeriod: 30,
  };

  constructor(shortPeriod: number = 10, longPeriod: number = 30) {
    super();
    this.parameters.shortPeriod = shortPeriod;
    this.parameters.longPeriod = longPeriod;
  }

  analyze(bars: Bar[], currentIndex: number): StrategySignal {
    const { shortPeriod, longPeriod } = this.parameters;

    // Need enough data to calculate both SMAs
    if (currentIndex < longPeriod) {
      return {
        timestamp: bars[currentIndex].t,
        action: 'hold',
        confidence: 0,
        reason: 'Insufficient data for analysis',
      };
    }

    const currentShortSMA = this.calculateSMA(bars, shortPeriod, currentIndex);
    const currentLongSMA = this.calculateSMA(bars, longPeriod, currentIndex);
    const previousShortSMA = this.calculateSMA(bars, shortPeriod, currentIndex - 1);
    const previousLongSMA = this.calculateSMA(bars, longPeriod, currentIndex - 1);

    // Bullish crossover: short SMA crosses above long SMA
    if (previousShortSMA <= previousLongSMA && currentShortSMA > currentLongSMA) {
      const confidence = Math.min(
        ((currentShortSMA - currentLongSMA) / currentLongSMA) * 100,
        1
      );
      return {
        timestamp: bars[currentIndex].t,
        action: 'buy',
        confidence,
        reason: `Bullish crossover: SMA(${shortPeriod}) crossed above SMA(${longPeriod})`,
      };
    }

    // Bearish crossover: short SMA crosses below long SMA
    if (previousShortSMA >= previousLongSMA && currentShortSMA < currentLongSMA) {
      const confidence = Math.min(
        ((currentLongSMA - currentShortSMA) / currentLongSMA) * 100,
        1
      );
      return {
        timestamp: bars[currentIndex].t,
        action: 'sell',
        confidence,
        reason: `Bearish crossover: SMA(${shortPeriod}) crossed below SMA(${longPeriod})`,
      };
    }

    return {
      timestamp: bars[currentIndex].t,
      action: 'hold',
      confidence: 0,
      reason: 'No crossover detected',
    };
  }
}
