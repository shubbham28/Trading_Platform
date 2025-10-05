import { Router, Request, Response } from 'express';
import { BacktestEngine } from '../backtest';
import { getStrategy } from '../strategies';
import alpacaClient from '../utils/alpaca';

const router = Router();

// Run a backtest
router.post('/', async (req: Request, res: Response) => {
  try {
    const {
      symbol,
      strategyId,
      startDate,
      endDate,
      initialCapital = 10000,
      parameters,
      timeframe = '1Day',
    } = req.body;

    // Validate required fields
    if (!symbol || !strategyId || !startDate || !endDate) {
      return res.status(400).json({
        error: 'Missing required fields: symbol, strategyId, startDate, endDate',
      });
    }

    // Get strategy
    const strategy = getStrategy(strategyId, parameters);
    if (!strategy) {
      return res.status(404).json({ error: 'Strategy not found' });
    }

    // Fetch historical data
    const bars = await alpacaClient.getBars(
      symbol.toUpperCase(),
      timeframe,
      startDate,
      endDate
    );

    if (bars.length === 0) {
      return res.status(400).json({ error: 'No historical data available for the given period' });
    }

    // Run backtest
    const backtestEngine = new BacktestEngine({
      symbol: symbol.toUpperCase(),
      startDate,
      endDate,
      initialCapital,
      strategy,
      commission: 0, // No commission for simplicity
    });

    const result = await backtestEngine.run(bars);
    res.json(result);
  } catch (error: any) {
    console.error('Error in POST /api/backtest:', error);
    res.status(500).json({ error: error.message || 'Failed to run backtest' });
  }
});

export default router;
