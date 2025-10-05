import { BaseStrategy } from './base';
import { Bar, StrategySignal } from '../types';

export class RSIStrategy extends BaseStrategy {
  name = 'RSI Strategy';
  description = 'Relative Strength Index strategy - buy when oversold, sell when overbought';
  
  parameters = {
    period: 14,
    oversoldLevel: 30,
    overboughtLevel: 70,
  };

  constructor(
    period: number = 14,
    oversoldLevel: number = 30,
    overboughtLevel: number = 70
  ) {
    super();
    this.parameters.period = period;
    this.parameters.oversoldLevel = oversoldLevel;
    this.parameters.overboughtLevel = overboughtLevel;
  }

  analyze(bars: Bar[], currentIndex: number): StrategySignal {
    const { period, oversoldLevel, overboughtLevel } = this.parameters;

    // Need enough data to calculate RSI
    if (currentIndex < period + 1) {
      return {
        timestamp: bars[currentIndex].t,
        action: 'hold',
        confidence: 0,
        reason: 'Insufficient data for RSI calculation',
      };
    }

    const currentRSI = this.calculateRSI(bars, period, currentIndex);
    const previousRSI = this.calculateRSI(bars, period, currentIndex - 1);

    // Oversold condition: RSI crosses above oversold level
    if (previousRSI <= oversoldLevel && currentRSI > oversoldLevel) {
      const confidence = (oversoldLevel - previousRSI) / oversoldLevel;
      return {
        timestamp: bars[currentIndex].t,
        action: 'buy',
        confidence,
        reason: `RSI crossed above oversold level (${currentRSI.toFixed(2)})`,
      };
    }

    // Overbought condition: RSI crosses below overbought level
    if (previousRSI >= overboughtLevel && currentRSI < overboughtLevel) {
      const confidence = (previousRSI - overboughtLevel) / (100 - overboughtLevel);
      return {
        timestamp: bars[currentIndex].t,
        action: 'sell',
        confidence,
        reason: `RSI crossed below overbought level (${currentRSI.toFixed(2)})`,
      };
    }

    // Strong oversold
    if (currentRSI < oversoldLevel) {
      return {
        timestamp: bars[currentIndex].t,
        action: 'buy',
        confidence: (oversoldLevel - currentRSI) / oversoldLevel,
        reason: `RSI is oversold (${currentRSI.toFixed(2)})`,
      };
    }

    // Strong overbought
    if (currentRSI > overboughtLevel) {
      return {
        timestamp: bars[currentIndex].t,
        action: 'sell',
        confidence: (currentRSI - overboughtLevel) / (100 - overboughtLevel),
        reason: `RSI is overbought (${currentRSI.toFixed(2)})`,
      };
    }

    return {
      timestamp: bars[currentIndex].t,
      action: 'hold',
      confidence: 0,
      reason: `RSI is neutral (${currentRSI.toFixed(2)})`,
    };
  }
}
