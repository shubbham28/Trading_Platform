import express, { Express, Request, Response, NextFunction } from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import assetsRouter from './routes/assets';
import marketDataRouter from './routes/market-data';
import accountRouter from './routes/account';
import ordersRouter from './routes/orders';
import strategiesRouter from './routes/strategies';
import backtestRouter from './routes/backtest';
import pythonBackendRouter from './routes/python-backend';

// Load environment variables
dotenv.config();

const app: Express = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors({
  origin: process.env.CORS_ORIGIN || 'http://localhost:5173',
  credentials: true,
}));
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Request logging middleware
app.use((req: Request, res: Response, next: NextFunction) => {
  console.log(`${new Date().toISOString()} - ${req.method} ${req.path}`);
  next();
});

// Health check
app.get('/health', (req: Request, res: Response) => {
  res.json({ 
    status: 'ok', 
    timestamp: new Date().toISOString(),
    mode: process.env.TRADING_MODE || 'paper',
  });
});

// API Routes
app.use('/api/assets', assetsRouter);
app.use('/api/market-data', marketDataRouter);
app.use('/api/account', accountRouter);
app.use('/api/orders', ordersRouter);
app.use('/api/strategies', strategiesRouter);
app.use('/api/backtest', backtestRouter);
app.use('/api/python', pythonBackendRouter);

// 404 handler
app.use((req: Request, res: Response) => {
  res.status(404).json({ error: 'Route not found' });
});

// Error handler
app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error('Error:', err);
  res.status(500).json({ 
    error: err.message || 'Internal server error',
    ...(process.env.NODE_ENV === 'development' && { stack: err.stack }),
  });
});

// Start server
app.listen(PORT, () => {
  console.log(`🚀 Trading Platform Server running on port ${PORT}`);
  console.log(`📊 Trading Mode: ${process.env.TRADING_MODE || 'paper'}`);
  console.log(`🌐 CORS enabled for: ${process.env.CORS_ORIGIN || 'http://localhost:5173'}`);
});

export default app;
