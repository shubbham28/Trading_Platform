import { Router, Request, Response } from 'express';
import { strategies, getStrategy } from '../strategies';

const router = Router();

// Get all available strategies
router.get('/', async (req: Request, res: Response) => {
  try {
    const strategyList = Object.keys(strategies).map(key => {
      const strategy = strategies[key];
      return {
        id: key,
        name: strategy.name,
        description: strategy.description,
        parameters: strategy.parameters,
      };
    });
    res.json(strategyList);
  } catch (error: any) {
    console.error('Error in GET /api/strategies:', error);
    res.status(500).json({ error: error.message || 'Failed to fetch strategies' });
  }
});

// Get specific strategy
router.get('/:strategyId', async (req: Request, res: Response) => {
  try {
    const { strategyId } = req.params;
    const strategy = getStrategy(strategyId);
    
    if (!strategy) {
      return res.status(404).json({ error: 'Strategy not found' });
    }

    res.json({
      id: strategyId,
      name: strategy.name,
      description: strategy.description,
      parameters: strategy.parameters,
    });
  } catch (error: any) {
    console.error(`Error in GET /api/strategies/${req.params.strategyId}:`, error);
    res.status(500).json({ error: error.message || 'Failed to fetch strategy' });
  }
});

export default router;
