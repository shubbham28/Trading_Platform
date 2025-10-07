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
- **Python** + FastAPI (Advanced strategies & backtesting)
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
- ✅ Advanced Python-based strategies with technical indicators
- ✅ Support for SMA, EMA, RSI, MACD, Bollinger Bands, VWAP, ATR, Stochastic
- ✅ Unified `Strategy` interface for live and backtest modes
- ✅ Extensible strategy system
- ✅ **NEW: 5 Intraday Trading Strategies**
  - Morning Momentum - Gap up with volume confirmation
  - Opening Range Breakout - Trade 30-min range breaks
  - VWAP Mean Reversion - Trade deviations from VWAP
  - Mean Reversion Intraday - RSI oversold bounces
  - Sector Momentum - Ride leading sector trends

### 4. Backtesting
- ✅ Run strategies on historical data
- ✅ Advanced Python backtesting engine with comprehensive metrics
- ✅ Sharpe ratio, Sortino ratio, max drawdown, profit factor
- ✅ Simulate trades and compute metrics (return %, win rate, avg win/loss)
- ✅ Visualize results with equity curve and trade logs
- ✅ Support for multiple timeframes (1Min, 5Min, 15Min, 1Hour, 1Day)

### 5. News-Based Forward Testing
- ✅ **NEW: Sentiment analysis on news headlines**
  - FinBERT model for financial sentiment
  - Generate trading signals from news
  - Combine sentiment with volume metrics
- ✅ Forward test simulation for upcoming sessions
- ✅ Track cumulative performance
- ✅ REST API endpoints for signal generation and retrieval

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
├── python_backend/         # Python Backend (FastAPI)
│   ├── app/
│   │   ├── backtest.py    # Advanced backtesting engine
│   │   └── data_fetcher.py # Alpaca data integration
│   ├── indicators/        # Technical indicator library
│   ├── strategies/        # Python-based trading strategies
│   │   ├── morning_momentum.py
│   │   ├── opening_range_breakout.py
│   │   ├── vwap_reversion.py
│   │   ├── mean_reversion_intraday.py
│   │   └── sector_momentum.py
│   ├── news_forward_tester.py # News sentiment & forward testing
│   ├── strategy_demo.ipynb    # Interactive examples
│   ├── main.py           # FastAPI application
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── README.md
│   └── INTRADAY_STRATEGIES.md  # Strategy documentation
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
├── ARCHITECTURE.md         # System architecture documentation
├── IMPLEMENTATION_SUMMARY.md  # Feature implementation details
└── README.md
```

## 🚦 Getting Started

### Prerequisites

- Node.js 20+ and npm
- Python 3.11+ and pip
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
PYTHON_BACKEND_URL=http://localhost:8000
```

### 3. Setup Python Backend

```bash
cd python_backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

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

### 4. Setup Frontend

```bash
cd web
npm install
```

### 5. Run Development Servers

**Terminal 1 - Node.js Backend:**
```bash
cd server
npm run dev
```

**Terminal 2 - Python Backend:**
```bash
cd python_backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

**Terminal 3 - Frontend:**
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
- Python backend (port 8000)
- Node.js backend server (port 3001)
- Frontend web app (port 5173)

## 🧩 API Endpoints

### Node.js Backend

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

### Python Backend (via `/api/python/*`)

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/python/indicators` | GET | List available indicators |
| `/api/python/indicators/calculate` | POST | Calculate indicators for symbol |
| `/api/python/strategies` | GET | List Python strategies |
| `/api/python/strategies/:id` | GET | Get strategy details |
| `/api/python/strategies/run` | POST | Execute strategy |
| `/api/python/backtest` | POST | Run advanced backtest |
| `/api/python/forward/news/signals` | POST | Generate news-based signals |
| `/api/python/forward/news/signals` | GET | Get latest news signals |
| `/api/python/forward/news/results` | GET | Get forward test results |
| `/api/python/forward/news/simulate` | POST | Simulate news-based trades |

## 📊 UI Components

- **TickerList** – Searchable list of assets (stocks/crypto)
- **QuoteHeader** – Current price & % change display
- **OHLCChart** – Interactive candlestick chart with Lightweight Charts
- **OrderTicket** – Form to place trades (market, limit, stop orders)
- **BacktestPanel** – Run backtests and display results
- **AccountPage** – View account balance and positions

## 🧠 Available Strategies

### Node.js Strategies

#### 1. SMA Crossover
Buy when short-period SMA crosses above long-period SMA, sell when it crosses below.

**Parameters:**
- `shortPeriod` (default: 10)
- `longPeriod` (default: 30)

#### 2. RSI Strategy
Buy when RSI crosses above oversold level, sell when it crosses below overbought level.

**Parameters:**
- `period` (default: 14)
- `oversoldLevel` (default: 30)
- `overboughtLevel` (default: 70)

### Python Advanced Strategies

#### 1. SMA Crossover (`sma_crossover`)
Simple Moving Average crossover with configurable periods.

**Parameters:**
- `short_period` (default: 10)
- `long_period` (default: 30)

#### 2. RSI Mean Reversion (`rsi_mean_revert`)
Mean reversion strategy based on RSI oversold/overbought levels.

**Parameters:**
- `period` (default: 14)
- `oversold` (default: 30)
- `overbought` (default: 70)

#### 3. MACD Trend Following (`macd_trend_follow`)
Trend following strategy using MACD crossovers.

**Parameters:**
- `fast_period` (default: 12)
- `slow_period` (default: 26)
- `signal_period` (default: 9)

#### 4. Morning Momentum (`morning_momentum`) 🆕
Gap up strategy with RSI and volume filters for intraday trading.

**Parameters:**
- `gap_threshold` (default: 2.0) - Minimum gap percentage
- `rsi_period` (default: 5)
- `rsi_max` (default: 70)
- `volume_ratio_min` (default: 2.0)

#### 5. Opening Range Breakout (`opening_range_breakout`) 🆕
Trades breakouts from the first 30-minute range.

**Parameters:**
- `range_period` (default: 30) - Opening range period in bars
- `stop_loss_pct` (default: 1.5)
- `take_profit_pct` (default: 3.0)

#### 6. VWAP Mean Reversion (`vwap_reversion`) 🆕
Mean reversion around VWAP in trending markets.

**Parameters:**
- `ema_fast` (default: 20)
- `ema_slow` (default: 50)
- `vwap_deviation_pct` (default: 0.5)

#### 7. Mean Reversion Intraday (`mean_reversion_intraday`) 🆕
RSI-based oversold bounce strategy.

**Parameters:**
- `rsi_period` (default: 5)
- `rsi_oversold` (default: 25)
- `rsi_target` (default: 50)

#### 8. Sector Momentum (`sector_momentum`) 🆕
Trades leading stocks in trending sectors.

**Parameters:**
- `rsi_period` (default: 14)
- `rsi_min` (default: 50)
- `rsi_max` (default: 75)
- `volume_surge_threshold` (default: 2.0)

> 📖 For detailed strategy documentation, see [INTRADAY_STRATEGIES.md](python_backend/INTRADAY_STRATEGIES.md)

## 📊 Technical Indicators (Python Backend)

The Python backend provides comprehensive technical indicators:

- **SMA** - Simple Moving Average
- **EMA** - Exponential Moving Average
- **RSI** - Relative Strength Index
- **MACD** - Moving Average Convergence Divergence
- **Bollinger Bands** - Volatility bands
- **VWAP** - Volume Weighted Average Price
- **ATR** - Average True Range
- **Stochastic** - Stochastic Oscillator

All indicators are modular and can be combined to create custom strategies.

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

## 📚 Additional Documentation

- **[INTRADAY_STRATEGIES.md](python_backend/INTRADAY_STRATEGIES.md)** - Detailed guide to intraday trading strategies
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture and data flow diagrams
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Complete implementation overview
- **[strategy_demo.ipynb](python_backend/strategy_demo.ipynb)** - Interactive Jupyter notebook with examples

## 📄 License

MIT

## 🤝 Contributing

This is a personal project, but feel free to fork and extend it for your own use!

## ⚠️ Disclaimer

This software is for educational purposes only. Trading stocks and cryptocurrencies involves substantial risk of loss. The authors are not responsible for any financial losses incurred through the use of this platform.
