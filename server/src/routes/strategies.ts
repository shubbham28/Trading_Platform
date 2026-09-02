import { Router, Request, Response } from 'express';
import { proxyToPython } from '../utils/python';

const router = Router();

// Kept at /api/strategies so the frontend's URLs are unchanged, but the
// strategies themselves now come from the Python engine rather than from a
// second, divergent TypeScript registry.
router.get('/', async (req: Request, res: Response) => {
  await proxyToPython(req, res, '/strategy/list');
});

router.get('/:strategyId', async (req: Request, res: Response) => {
  await proxyToPython(req, res, `/strategy/${req.params.strategyId}`);
});

export default router;
