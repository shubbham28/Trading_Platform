# 🚀 Trading Platform MVP

A full-stack personal trading platform that connects to the **Alpaca API** to trade stocks and crypto. View tickers, analyze charts, test trading strategies, and place buy/sell orders.

![Trading Platform](https://img.shields.io/badge/Trading-Platform-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-007ACC?logo=typescript&logoColor=white)
![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)
![Node.js](https://img.shields.io/badge/Node.js-43853D?logo=node.js&logoColor=white)

## 🧱 Tech Stack

### Frontend
- **React** with Vite + TypeScript
- **Material UI** for components
- **React Query** for data fetching
- **Lightweight Charts** for OHLC visualization
- **React Router** for navigation

### Backend
- **Node.js** + Express (TypeScript)
- **Alpaca API** integration (REST + WebSocket)
- PostgreSQL for strategies and backtests
- Redis for caching (optional)

## ⚙️ Features

### 1. Market Data
- ✅ Fetch active tradable stocks and crypto using Alpaca `/v2/assets`
- ✅ Display ticker details (price, volume, OHLC)
- ✅ Fetch and visualize historical bars
- ✅ Interactive OHLC candlestick charts

### 2. Orders
- ✅ Place buy/sell orders via Alpaca `/v2/orders`
- ✅ Support market, limit, stop, and stop-limit order types
- ✅ View account info and current positions
- ✅ Default to **paper trading** with safe toggle to live

### 3. Strategy Engine
- ✅ Implement basic algorithms (SMA crossover, RSI)
- ✅ Unified `Strategy` interface for live and backtest modes
- ✅ Extensible strategy system

### 4. Backtesting
- ✅ Run strategies on historical data
- ✅ Simulate trades and compute metrics (return %, Sharpe, drawdown)
- ✅ Visualize results with equity curve and trade logs

## 📁 Project Structure

```
/
├── server/                 # Backend (Node.js + Express)
│   ├── src/
│   │   ├── routes/        # API route handlers
│   │   ├── strategies/    # Trading strategy implementations
│   │   ├── backtest/      # Backtesting engine
│   │   ├── types/         # TypeScript type definitions
│   │   ├── utils/         # Alpaca client and utilities
│   │   └── index.ts       # Express server entry point
│   ├── package.json
│   ├── tsconfig.json
│   └── .env.example
│
├── web/                    # Frontend (React + Vite)
│   ├── src/
│   │   ├── components/    # React components
│   │   ├── pages/         # Page components
│   │   ├── types/         # TypeScript types
│   │   ├── utils/         # API client
│   │   ├── App.tsx        # Main app component
│   │   └── main.tsx       # Entry point
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── docker-compose.yml      # Docker orchestration
└── README.md
```

## 🚦 Getting Started

### Prerequisites

- Node.js 20+ and npm
- Docker and Docker Compose (optional)
- Alpaca API account (free paper trading account)

### 1. Get Alpaca API Keys

1. Sign up for a free account at [Alpaca](https://alpaca.markets)
2. Navigate to your paper trading dashboard
3. Generate API keys (Key ID and Secret Key)

### 2. Setup Backend

```bash
cd server
npm install

# Copy environment template
cp .env.example .env

# Edit .env and add your Alpaca credentials
nano .env
```

Update `.env` with your Alpaca credentials:
```env
ALPACA_API_KEY=your_paper_api_key_here
ALPACA_API_SECRET=your_paper_api_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_MODE=paper
```

### 3. Setup Frontend

```bash
cd web
npm install
```

### 4. Run Development Servers

**Terminal 1 - Backend:**
```bash
cd server
npm run dev
```

**Terminal 2 - Frontend:**
```bash
cd web
npm run dev
```

The application will be available at:
- Frontend: http://localhost:5173
- Backend API: http://localhost:3001

## 🐳 Docker Deployment

Run the entire stack with Docker Compose:

```bash
# Make sure to configure server/.env first
docker-compose up -d
```

This will start:
- PostgreSQL database (port 5432)
- Redis cache (port 6379)
- Backend server (port 3001)
- Frontend web app (port 5173)

## 🧩 API Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/assets` | GET | List tradable assets |
| `/api/assets/:symbol` | GET | Get specific asset |
| `/api/market-data/:symbol/bars` | GET | Get historical bars |
| `/api/market-data/:symbol/quote` | GET | Get latest quote |
| `/api/account` | GET | Fetch account info |
| `/api/account/positions` | GET | Get all positions |
| `/api/orders` | GET/POST | List/create orders |
| `/api/orders/:id` | GET/DELETE | Get/cancel specific order |
| `/api/strategies` | GET | List available strategies |
| `/api/backtest` | POST | Run backtests |

## 📊 UI Components

- **TickerList** – Searchable list of assets (stocks/crypto)
- **QuoteHeader** – Current price & % change display
- **OHLCChart** – Interactive candlestick chart with Lightweight Charts
- **OrderTicket** – Form to place trades (market, limit, stop orders)
- **BacktestPanel** – Run backtests and display results
- **AccountPage** – View account balance and positions

## 🧠 Available Strategies

### 1. SMA Crossover
Buy when short-period SMA crosses above long-period SMA, sell when it crosses below.

**Parameters:**
- `shortPeriod` (default: 10)
- `longPeriod` (default: 30)

### 2. RSI Strategy
Buy when RSI crosses above oversold level, sell when it crosses below overbought level.

**Parameters:**
- `period` (default: 14)
- `oversoldLevel` (default: 30)
- `overboughtLevel` (default: 70)

## 🔒 Security Notes

- ✅ All API keys are stored server-side only
- ✅ Default mode is **paper trading** (no real money)
- ⚠️ To enable live trading, set `TRADING_MODE=live` in `.env` (use with caution!)
- 🔐 Never commit `.env` files to version control

## 🛠️ Development

### Backend

```bash
cd server

# Development with hot reload
npm run dev

# Build
npm run build

# Production
npm start

# Lint
npm run lint

# Type check
npm run typecheck
```

### Frontend

```bash
cd web

# Development
npm run dev

# Build
npm run build

# Preview production build
npm run preview

# Lint
npm run lint
```

## 📝 Environment Variables

### Server (.env)
```env
ALPACA_API_KEY=your_key
ALPACA_API_SECRET=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_MODE=paper
PORT=3001
NODE_ENV=development
CORS_ORIGIN=http://localhost:5173
```

### Web (.env)
```env
VITE_API_URL=/api  # Uses proxy in dev mode
```

## 🧪 Testing Backtests

Example backtest request:

```json
POST /api/backtest
{
  "symbol": "AAPL",
  "strategyId": "sma-crossover",
  "startDate": "2023-01-01",
  "endDate": "2023-12-31",
  "initialCapital": 10000,
  "timeframe": "1Day"
}
```

## 🚧 Future Enhancements

- [ ] Real-time WebSocket data streaming
- [ ] Advanced charting indicators (Bollinger Bands, MACD)
- [ ] Portfolio analytics and performance tracking
- [ ] AI-driven trade recommendations
- [ ] Risk management features
- [ ] More sophisticated strategy parameters
- [ ] Historical trade journal
- [ ] Notification system for trade alerts

## 📄 License

MIT

## 🤝 Contributing

This is a personal project, but feel free to fork and extend it for your own use!

## ⚠️ Disclaimer

This software is for educational purposes only. Trading stocks and cryptocurrencies involves substantial risk of loss. The authors are not responsible for any financial losses incurred through the use of this platform.
