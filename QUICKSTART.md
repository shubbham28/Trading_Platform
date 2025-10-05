# Quick Start Guide - Trading Platform MVP

## 🎯 5-Minute Setup

### Step 1: Get Alpaca API Keys
1. Go to [Alpaca Markets](https://alpaca.markets)
2. Sign up for a FREE paper trading account
3. Navigate to Dashboard → Paper Trading
4. Generate API keys (save both Key ID and Secret Key)

### Step 2: Configure Backend
```bash
cd server
cp .env.example .env
```

Edit `server/.env` and add your keys:
```env
ALPACA_API_KEY=PK...your_key_here
ALPACA_API_SECRET=...your_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
TRADING_MODE=paper
```

### Step 3: Choose Your Setup

#### Option A: Docker (Recommended)
```bash
docker-compose up -d
```
✅ Opens at: http://localhost:5173

#### Option B: Development Mode
**Terminal 1 - Backend:**
```bash
cd server
npm install
npm run dev
```

**Terminal 2 - Frontend:**
```bash
cd web
npm install
npm run dev
```
✅ Opens at: http://localhost:5173

## 🎮 Using the Platform

### Trading Page (Main)
1. **Select a Ticker**: Click on any stock/crypto from the left sidebar
2. **View Chart**: See OHLC candlestick chart with price history
3. **Place Order**: Use the order ticket to buy/sell
4. **Backtest**: Test a strategy on historical data

### Account Page
- View your account balance and buying power
- See all open positions
- Track profit/loss (P&L)

## 📊 Available Strategies

### SMA Crossover
- **When it trades**: Buy when short SMA crosses above long SMA
- **Parameters**: Short period (10), Long period (30)
- **Good for**: Trend following

### RSI Strategy
- **When it trades**: Buy when oversold, sell when overbought
- **Parameters**: Period (14), Oversold (30), Overbought (70)
- **Good for**: Mean reversion

## 🧪 Testing Backtests

1. Select a ticker (e.g., AAPL)
2. Click "Backtest Strategy" panel
3. Choose a strategy
4. Set date range (e.g., last 6 months)
5. Set initial capital (e.g., $10,000)
6. Click "Run Backtest"

Results show:
- Total return and %
- Sharpe ratio
- Max drawdown
- Win rate
- Total trades

## 📡 API Endpoints Reference

### Market Data
```bash
# Get all stocks
GET http://localhost:3001/api/assets?asset_class=us_equity

# Get historical bars
GET http://localhost:3001/api/market-data/AAPL/bars?timeframe=1Day&start=2024-01-01

# Get latest quote
GET http://localhost:3001/api/market-data/AAPL/quote
```

### Trading
```bash
# Get account info
GET http://localhost:3001/api/account

# Place market order
POST http://localhost:3001/api/orders
{
  "symbol": "AAPL",
  "qty": 10,
  "side": "buy",
  "type": "market",
  "time_in_force": "day"
}

# Get positions
GET http://localhost:3001/api/account/positions
```

### Strategies
```bash
# List strategies
GET http://localhost:3001/api/strategies

# Run backtest
POST http://localhost:3001/api/backtest
{
  "symbol": "AAPL",
  "strategyId": "sma-crossover",
  "startDate": "2024-01-01",
  "endDate": "2024-10-01",
  "initialCapital": 10000
}
```

## 🛠️ Development Commands

### Backend
```bash
npm run dev        # Start dev server with hot reload
npm run build      # Build for production
npm start          # Run production build
npm run lint       # Lint code
npm run typecheck  # Type check without emit
```

### Frontend
```bash
npm run dev        # Start dev server
npm run build      # Build for production
npm run preview    # Preview production build
npm run lint       # Lint code
```

## 🐛 Troubleshooting

### "Alpaca API credentials not configured"
- Make sure `server/.env` exists and has valid API keys
- Restart the server after updating `.env`

### "Failed to fetch assets"
- Check that your Alpaca API keys are correct
- Verify you're using paper trading keys (not live)
- Check that `ALPACA_BASE_URL` is set correctly

### CORS errors
- Make sure backend is running on port 3001
- Check `CORS_ORIGIN` in `server/.env` matches frontend URL

### Port already in use
```bash
# Find and kill process on port 3001
lsof -ti:3001 | xargs kill -9

# Find and kill process on port 5173
lsof -ti:5173 | xargs kill -9
```

## 🔒 Security Reminders

⚠️ **IMPORTANT:**
- This platform defaults to **PAPER TRADING** (fake money)
- Never commit `.env` files to git
- Keep your API keys secret
- To enable live trading, change `TRADING_MODE=live` (use with extreme caution!)

## 📚 Next Steps

### Extend the Platform
- Add more strategies (MACD, Bollinger Bands, etc.)
- Implement WebSocket for real-time data
- Add portfolio analytics
- Create custom indicators
- Add AI-based trade recommendations

### Learn More
- [Alpaca API Docs](https://alpaca.markets/docs/)
- [Material UI](https://mui.com/)
- [Lightweight Charts](https://tradingview.github.io/lightweight-charts/)
- [React Query](https://tanstack.com/query/latest)

## 🎉 You're Ready!

Start trading on your personal platform:
1. Select a ticker from the sidebar
2. View the chart and current price
3. Place your first order
4. Test strategies with backtesting

Happy Trading! 🚀📈
