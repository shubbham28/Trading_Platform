import { Router, Request, Response } from 'express';
import axios from 'axios';

const router = Router();

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8000';

// Proxy middleware for Python backend
const proxyToPython = async (req: Request, res: Response, endpoint: string) => {
  try {
    const url = `${PYTHON_BACKEND_URL}${endpoint}`;
    const response = await axios({
      method: req.method,
      url,
      data: req.body,
      params: req.query,
      headers: {
        'Content-Type': 'application/json',
      },
    });
    
    res.status(response.status).json(response.data);
  } catch (error: any) {
    console.error(`Error proxying to Python backend (${endpoint}):`, error.message);
    
    if (error.response) {
      res.status(error.response.status).json(error.response.data);
    } else {
      res.status(503).json({
        error: 'Python backend unavailable',
        message: error.message,
      });
    }
  }
};

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
