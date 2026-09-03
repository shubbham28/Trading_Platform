import { Router, Request, Response } from 'express';
import { proxyToPython } from '../utils/python';

const router = Router();

/**
 * Backtests run in the Python engine.
 *
 * The TypeScript backtester this replaces filled at the signal bar's close,
 * annualised every timeframe as daily, sized every position at 100% of capital,
 * and had no tests. Keeping it as a second opinion was worse than having none:
 * two engines disagreeing about the same strategy means neither can be trusted.
 *
 * Field names are normalised here because the old TypeScript route accepted
 * camelCase while the Python engine speaks snake_case. Without this, existing
 * callers would silently fall back to the engine's defaults -- a backtest
 * quietly run over the wrong dates with the wrong capital.
 */
router.post('/', async (req: Request, res: Response) => {
  const {
    symbol,
    strategyId, strategy_id,
    startDate, start_date,
    endDate, end_date,
    initialCapital, initial_capital,
    parameters,
    timeframe,
    commission,
    slippage_bps,
    max_position_pct,
    allow_short,
  } = req.body ?? {};

  const normalised = {
    symbol: typeof symbol === 'string' ? symbol.toUpperCase() : symbol,
    strategy_id: strategy_id ?? strategyId,
    start_date: start_date ?? startDate,
    end_date: end_date ?? endDate,
    initial_capital: initial_capital ?? initialCapital ?? 10000,
    parameters: parameters ?? {},
    timeframe: timeframe ?? '1Day',
    ...(commission !== undefined && { commission }),
    ...(slippage_bps !== undefined && { slippage_bps }),
    ...(max_position_pct !== undefined && { max_position_pct }),
    ...(allow_short !== undefined && { allow_short }),
  };

  const missing = (['symbol', 'strategy_id', 'start_date', 'end_date'] as const)
    .filter((field) => !normalised[field]);

  if (missing.length > 0) {
    res.status(400).json({
      error: `Missing required fields: ${missing.join(', ')}`,
    });
    return;
  }

  req.body = normalised;
  await proxyToPython(req, res, '/backtest/run');
});

/**
 * Stored runs.
 *
 * These existed in the engine from the moment backtests started being persisted
 * but were never mounted here, so the frontend got a 404 for every one of them.
 * Adding an engine endpoint is not the same as making it reachable, and nothing
 * in this service is tested, so the gap sat unnoticed until a UI tried to use it.
 */
router.get('/runs', async (req: Request, res: Response) => {
  await proxyToPython(req, res, '/backtest/runs');
});

router.get('/runs/:runId', async (req: Request, res: Response) => {
  await proxyToPython(req, res, `/backtest/runs/${req.params.runId}`);
});

router.get('/runs/:runId/equity', async (req: Request, res: Response) => {
  await proxyToPython(req, res, `/backtest/runs/${req.params.runId}/equity`);
});

export default router;
