import { Router, Request, Response } from 'express';
import alpacaClient from '../utils/alpaca';

const router = Router();

// Get historical bars for a symbol
router.get('/:symbol/bars', async (req: Request, res: Response) => {
  try {
    const { symbol } = req.params;
    const { timeframe = '1Day', start, end, limit } = req.query;

    if (!start) {
      return res.status(400).json({ error: 'start parameter is required' });
    }

    const bars = await alpacaClient.getBars(
      symbol.toUpperCase(),
      timeframe as string,
      start as string,
      end as string | undefined,
      limit ? parseInt(limit as string) : undefined
    );

    res.json({ symbol, timeframe, bars });
  } catch (error: any) {
    console.error(`Error in GET /api/market-data/${req.params.symbol}/bars:`, error);
    res.status(500).json({ error: error.message || 'Failed to fetch bars' });
  }
});

// Get latest bar for a symbol
router.get('/:symbol/latest-bar', async (req: Request, res: Response) => {
  try {
    const { symbol } = req.params;
    const bar = await alpacaClient.getLatestBar(symbol.toUpperCase());
    res.json({ symbol, bar });
  } catch (error: any) {
    console.error(`Error in GET /api/market-data/${req.params.symbol}/latest-bar:`, error);
    res.status(500).json({ error: error.message || 'Failed to fetch latest bar' });
  }
});

// Get latest quote for a symbol
router.get('/:symbol/quote', async (req: Request, res: Response) => {
  try {
    const { symbol } = req.params;
    const quote = await alpacaClient.getLatestQuote(symbol.toUpperCase());
    res.json({ symbol, quote });
  } catch (error: any) {
    console.error(`Error in GET /api/market-data/${req.params.symbol}/quote:`, error);
    res.status(500).json({ error: error.message || 'Failed to fetch quote' });
  }
});

export default router;
