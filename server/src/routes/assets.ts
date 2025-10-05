import { Router, Request, Response } from 'express';
import alpacaClient from '../utils/alpaca';

const router = Router();

// Get all assets
router.get('/', async (req: Request, res: Response) => {
  try {
    const { status = 'active', asset_class } = req.query;
    const assets = await alpacaClient.getAssets(
      status as string,
      asset_class as string | undefined
    );
    res.json(assets);
  } catch (error: any) {
    console.error('Error in GET /api/assets:', error);
    res.status(500).json({ error: error.message || 'Failed to fetch assets' });
  }
});

// Get specific asset
router.get('/:symbol', async (req: Request, res: Response) => {
  try {
    const { symbol } = req.params;
    const asset = await alpacaClient.getAsset(symbol.toUpperCase());
    res.json(asset);
  } catch (error: any) {
    console.error(`Error in GET /api/assets/${req.params.symbol}:`, error);
    res.status(500).json({ error: error.message || 'Failed to fetch asset' });
  }
});

export default router;
