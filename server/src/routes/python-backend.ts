import { Router, Request, Response } from 'express';
import { proxyToPython } from '../utils/python';

const router = Router();

// List available indicators
router.get('/indicators', async (req: Request, res: Response) => {
  await proxyToPython(req, res, '/indicators');
});

// Calculate indicators
router.post('/indicators/calculate', async (req: Request, res: Response) => {
  await proxyToPython(req, res, '/indicators/calculate');
});

// List strategies
router.get('/strategies', async (req: Request, res: Response) => {
  await proxyToPython(req, res, '/strategy/list');
});

// Get strategy info
router.get('/strategies/:id', async (req: Request, res: Response) => {
  await proxyToPython(req, res, `/strategy/${req.params.id}`);
});

// Run strategy
router.post('/strategies/run', async (req: Request, res: Response) => {
  await proxyToPython(req, res, '/strategy/run');
});

// Run backtest
router.post('/backtest', async (req: Request, res: Response) => {
  await proxyToPython(req, res, '/backtest/run');
});

export default router;
