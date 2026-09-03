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

/**
 * What the Python engine returns. Backtests are no longer run in Node, so this
 * mirrors python_backend/app/backtest.py rather than a TypeScript engine that
 * no longer exists.
 */
export interface BacktestResult {
  strategy_id: string;
  symbol: string;
  start_date: string;
  end_date: string;
  parameters: Record<string, any>;
  initial_capital: number;
  final_capital: number;
  total_return: number;
  total_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  /** null rather than a fake ratio when there were no losing trades. */
  profit_factor: number | null;
  trades: Trade[];
  equity_curve: EquityPoint[];

  // The cost assumptions these numbers were produced under. Quoting a return
  // without them is how two incomparable runs end up side by side.
  timeframe: string;
  commission: number;
  slippage_bps: number;
  max_position_pct: number;
  allow_short: boolean;

  /** What the engine could not do. An empty audit is a meaningful result. */
  audit: ExecutionAudit;

  // Whether the run was stored. A result that was not saved must not look
  // identical to one that was.
  run_id: number | null;
  persisted: boolean;
  persistence_error: string | null;
}

export interface ExecutionAudit {
  intents_unfilled_no_next_bar: number;
  intents_rejected_insufficient_capital: number;
  intents_rejected_shorts_disabled: number;
  forced_liquidations: number;
  bars_skipped_warmup: number;
  /** Sessions whose data ends well before the assumed close: likely half-days. */
  sessions_with_early_close_risk: string[];
}

/** A completed round trip as the Python engine records it. */
export interface Trade {
  entry_time: string;
  entry_price: number;
  exit_time: string | null;
  exit_price: number | null;
  quantity: number;
  side: 'long' | 'short';
  pnl: number | null;
  pnl_pct: number | null;
  commission: number;
  reason: string;
  /**
   * True when the engine closed this at the end of the data rather than because
   * the strategy asked. Not a strategy exit, and should not be read as one.
   */
  forced_liquidation: boolean;
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

/**
 * camelCase is kept deliberately. The Node route normalises these to the
 * snake_case the Python engine speaks, so existing callers keep working; without
 * that mapping the engine would silently fall back to its defaults and run a
 * backtest over the wrong dates with the wrong capital.
 */
export interface BacktestRequest {
  symbol: string;
  strategyId: string;
  startDate: string;
  endDate: string;
  initialCapital?: number;
  parameters?: Record<string, any>;
  timeframe?: string;
}

// -- bots -------------------------------------------------------------------

export interface BotPosition {
  symbol: string;
  qty: number;
  entry_price: number;
  entry_time: string;
}

export interface Bot {
  id: number;
  name: string;
  /** Intent. Whether a runner is attached is `runner_attached`, not this. */
  enabled: boolean;
  strategy_id: string;
  parameters: Record<string, any>;
  symbols: string[];
  timeframe: string;
  capital_budget: number;
  risk_limits: Record<string, any>;
  mode: 'paper' | 'live';
  created_at: string;

  last_activity_at: string | null;
  seconds_since_activity: number | null;
  /**
   * Enabled AND recently active. A bot can be enabled with no runner process
   * running anywhere, so these are separate facts and the UI shows both.
   */
  runner_attached: boolean;
  open_positions: BotPosition[];
  /**
   * null when there is no start-of-day baseline. Not zero: in that state the
   * risk gate blocks every opening order, so it must not read as a flat day.
   */
  daily_pnl: number | null;
  blocked_orders_by_rule: Record<string, number>;
}

export interface BotCreateRequest {
  name: string;
  strategy_id: string;
  symbols: string[];
  timeframe: string;
  capital_budget: number;
  parameters?: Record<string, any>;
  risk_limits?: Record<string, any>;
  mode?: string;
  enabled?: boolean;
}

export interface BotUpdateRequest {
  enabled?: boolean;
  parameters?: Record<string, any>;
  risk_limits?: Record<string, any>;
  capital_budget?: number;
  symbols?: string[];
  timeframe?: string;
}

// -- risk -------------------------------------------------------------------

export interface KillSwitch {
  engaged: boolean;
  reason: string | null;
  engaged_at: string | null;
  updated_at?: string;
}

export interface RiskRule {
  tier: 'account' | 'bot' | 'position';
  name: string;
  description: string;
}

export interface RiskRules {
  account_limits: Record<string, number>;
  rules: RiskRule[];
  note: string;
}

export interface RiskDecision {
  id: number;
  occurred_at: string;
  bot_id: number | null;
  symbol: string | null;
  allowed: boolean;
  rule: string | null;
  tier: string | null;
  detail: string | null;
  is_reducing: boolean;
}

// -- audit ------------------------------------------------------------------

export interface AuditEntry {
  id: number;
  occurred_at: string;
  bot_id: number | null;
  event_type: string;
  symbol: string | null;
  payload: Record<string, any>;
}

// -- reconciliation ---------------------------------------------------------

export interface Divergence {
  symbol: string;
  broker_qty: string;
  local_qty: string;
  difference: string;
  bot_ids: number[];
}

export interface Reconciliation {
  in_sync: boolean;
  summary: string;
  divergences: Divergence[];
}

// -- stored backtests -------------------------------------------------------

export interface BacktestRunSummary {
  id: number;
  strategy_id: string;
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  parameters: Record<string, any>;
  /** The cost assumptions these numbers were produced under. */
  config: Record<string, any>;
  metrics: Record<string, any>;
  audit: Record<string, any>;
  created_at: string;
}

// -- live gating ------------------------------------------------------------

export interface LiveSettings {
  /** When false, every live order waits for a person. */
  auto_approve: boolean;
  auto_approve_note: string | null;
  auto_approve_enabled_at: string | null;
  /** Hard ceiling on one live order. Zero means live trading is off. */
  max_order_value: number;
  approval_timeout_seconds: number;
  updated_at: string;
  /**
   * Stated by the engine rather than inferred here. A UI working out the
   * posture from a flag plus a number is a UI that will eventually get it wrong.
   */
  live_trading_permitted: boolean;
}

export interface PendingApproval {
  order_id: number;
  bot_id: number | null;
  symbol: string;
  side: 'buy' | 'sell';
  qty: number;
  order_type: string;
  reason: string | null;
  bar_timestamp: string | null;
  requested_at: string | null;
  age_seconds: number | null;
  /** Time left before it expires unapproved. Its signal goes stale. */
  expires_in_seconds: number | null;
}

export interface ApprovalQueue {
  count: number;
  approval_timeout_seconds: number;
  auto_approve: boolean;
  approvals: PendingApproval[];
}
