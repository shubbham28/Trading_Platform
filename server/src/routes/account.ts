import { Router, Request, Response } from 'express';
import alpacaClient from '../utils/alpaca';

const router = Router();

// Get account information
router.get('/', async (req: Request, res: Response) => {
  try {
    const account = await alpacaClient.getAccount();
    res.json(account);
  } catch (error: any) {
    console.error('Error in GET /api/account:', error);
    res.status(500).json({ error: error.message || 'Failed to fetch account' });
  }
});

// Get all positions
router.get('/positions', async (req: Request, res: Response) => {
  try {
    const positions = await alpacaClient.getPositions();
    res.json(positions);
  } catch (error: any) {
    console.error('Error in GET /api/account/positions:', error);
    res.status(500).json({ error: error.message || 'Failed to fetch positions' });
  }
});

// Get position for a specific symbol
router.get('/positions/:symbol', async (req: Request, res: Response) => {
  try {
    const { symbol } = req.params;
    const position = await alpacaClient.getPosition(symbol.toUpperCase());
    res.json(position);
  } catch (error: any) {
    console.error(`Error in GET /api/account/positions/${req.params.symbol}:`, error);
    res.status(404).json({ error: error.message || 'Position not found' });
  }
});

// Close position for a specific symbol
router.delete('/positions/:symbol', async (req: Request, res: Response) => {
  try {
    const { symbol } = req.params;
    const order = await alpacaClient.closePosition(symbol.toUpperCase());
    res.json({ message: 'Position closed', order });
  } catch (error: any) {
    console.error(`Error in DELETE /api/account/positions/${req.params.symbol}:`, error);
    res.status(500).json({ error: error.message || 'Failed to close position' });
  }
});

export default router;
