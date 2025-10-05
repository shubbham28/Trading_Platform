import { SMACrossoverStrategy } from './sma-crossover';
import { RSIStrategy } from './rsi';
import { IStrategy } from './base';

export const strategies: Record<string, IStrategy> = {
  'sma-crossover': new SMACrossoverStrategy(),
  'rsi': new RSIStrategy(),
};

export function getStrategy(name: string, params?: Record<string, any>): IStrategy | null {
  const strategy = strategies[name];
  if (!strategy) {
    return null;
  }

  // Clone strategy with custom parameters if provided
  if (params) {
    strategy.parameters = { ...strategy.parameters, ...params };
  }

  return strategy;
}

export { SMACrossoverStrategy, RSIStrategy };
export * from './base';
