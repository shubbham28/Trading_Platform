import { Request, Response } from 'express';
import axios from 'axios';

/**
 * Read per call, not once at module load.
 *
 * Captured at import, the value is fixed for the life of the process, which
 * makes it impossible to test the unreachable-engine path and means an
 * environment change needs a restart to take effect.
 */
const engineUrl = (): string =>
  process.env.PYTHON_BACKEND_URL || 'http://localhost:8000';

/**
 * Forward a request to the Python engine.
 *
 * The Python engine owns every strategy and backtest decision. Node used to
 * carry a second implementation of both -- two strategies, its own backtester,
 * a different Strategy interface -- so a result from one was unverifiable in the
 * other and every fix had to be written twice. That copy is gone; this is the
 * only path to strategy logic.
 */
export const proxyToPython = async (
  req: Request,
  res: Response,
  endpoint: string
): Promise<void> => {
  try {
    const response = await axios({
      method: req.method,
      url: `${engineUrl()}${endpoint}`,
      data: req.body,
      params: req.query,
      headers: { 'Content-Type': 'application/json' },
    });

    res.status(response.status).json(response.data);
  } catch (error: any) {
    console.error(`Error proxying to Python backend (${endpoint}):`, error.message);

    if (error.response) {
      res.status(error.response.status).json(error.response.data);
    } else {
      // A dead engine must not look like an empty result. A backtest route that
      // returns 200 with nothing reads as "no trades found".
      res.status(503).json({
        error: 'Python backend unavailable',
        message: error.message,
      });
    }
  }
};

export { engineUrl };
