export interface Asset {
  id: string;
  class: string;
  exchange: string;
  symbol: string;
  name: string;
  status: string;
  tradable: boolean;
  marginable: boolean;
  shortable: boolean;
  easy_to_borrow: boolean;
  fractionable: boolean;
}

export interface Bar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Quote {
  symbol: string;
  bid_price: number;
  ask_price: number;
  bid_size: number;
  ask_size: number;
  timestamp: string;
}

export interface Order {
  id: string;
  client_order_id: string;
  created_at: string;
  updated_at: string;
  symbol: string;
  qty: string;
  filled_qty: string;
  type: 'market' | 'limit' | 'stop' | 'stop_limit' | 'trailing_stop';
  side: 'buy' | 'sell';
  time_in_force: 'day' | 'gtc' | 'ioc' | 'fok';
  limit_price?: string;
  stop_price?: string;
  status: string;
  extended_hours: boolean;
}

export interface Position {
  asset_id: string;
  symbol: string;
  exchange: string;
  asset_class: string;
  avg_entry_price: string;
  qty: string;
  side: 'long' | 'short';
  market_value: string;
  cost_basis: string;
  unrealized_pl: string;
  unrealized_plpc: string;
  current_price: string;
  change_today: string;
}

export interface Account {
  id: string;
  account_number: string;
  status: string;
  currency: string;
  buying_power: string;
  cash: string;
  portfolio_value: string;
  pattern_day_trader: boolean;
  equity: string;
  last_equity: string;
  long_market_value: string;
  short_market_value: string;
  daytrade_count: number;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  parameters: Record<string, any>;
}

export interface BacktestResult {
  strategy_id: string;
  symbol: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_capital: number;
  total_return: number;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  trades: Trade[];
  equity_curve: EquityPoint[];
}

export interface Trade {
  timestamp: string;
  action: 'buy' | 'sell';
  symbol: string;
  quantity: number;
  price: number;
  value: number;
  reason?: string;
}

export interface EquityPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
}

export interface OrderRequest {
  symbol: string;
  qty: number;
  side: 'buy' | 'sell';
  type: 'market' | 'limit' | 'stop' | 'stop_limit';
  time_in_force: 'day' | 'gtc' | 'ioc' | 'fok';
  limit_price?: number;
  stop_price?: number;
  extended_hours?: boolean;
}

export interface BacktestRequest {
  symbol: string;
  strategyId: string;
  startDate: string;
  endDate: string;
  initialCapital?: number;
  parameters?: Record<string, any>;
  timeframe?: string;
}
