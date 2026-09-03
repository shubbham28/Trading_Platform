import axios from 'axios';
import type {
  Asset,
  Bar,
  Quote,
  Order,
  Position,
  Account,
  Strategy,
  BacktestResult,
  OrderRequest,
  BacktestRequest,
  Bot,
  BotCreateRequest,
  BotUpdateRequest,
  KillSwitch,
  RiskRules,
  RiskDecision,
  AuditEntry,
  Reconciliation,
  BacktestRunSummary,
  LiveSettings,
  ApprovalQueue,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

// Assets
export const getAssets = async (status = 'active', assetClass?: string): Promise<Asset[]> => {
  const params: any = { status };
  if (assetClass) params.asset_class = assetClass;
  const response = await api.get('/assets', { params });
  return response.data;
};

export const getAsset = async (symbol: string): Promise<Asset> => {
  const response = await api.get(`/assets/${symbol}`);
  return response.data;
};

// Market Data
export const getBars = async (
  symbol: string,
  timeframe: string,
  start: string,
  end?: string,
  limit?: number
): Promise<{ symbol: string; timeframe: string; bars: Bar[] }> => {
  const params: any = { timeframe, start };
  if (end) params.end = end;
  if (limit) params.limit = limit;
  const response = await api.get(`/market-data/${symbol}/bars`, { params });
  return response.data;
};

export const getLatestBar = async (symbol: string): Promise<{ symbol: string; bar: Bar }> => {
  const response = await api.get(`/market-data/${symbol}/latest-bar`);
  return response.data;
};

export const getQuote = async (symbol: string): Promise<{ symbol: string; quote: Quote }> => {
  const response = await api.get(`/market-data/${symbol}/quote`);
  return response.data;
};

// Account
export const getAccount = async (): Promise<Account> => {
  const response = await api.get('/account');
  return response.data;
};

export const getPositions = async (): Promise<Position[]> => {
  const response = await api.get('/account/positions');
  return response.data;
};

export const getPosition = async (symbol: string): Promise<Position> => {
  const response = await api.get(`/account/positions/${symbol}`);
  return response.data;
};

export const closePosition = async (symbol: string): Promise<{ message: string; order: Order }> => {
  const response = await api.delete(`/account/positions/${symbol}`);
  return response.data;
};

// Orders
export const getOrders = async (status?: string, limit?: number): Promise<Order[]> => {
  const params: any = {};
  if (status) params.status = status;
  if (limit) params.limit = limit;
  const response = await api.get('/orders', { params });
  return response.data;
};

export const createOrder = async (orderRequest: OrderRequest): Promise<Order> => {
  const response = await api.post('/orders', orderRequest);
  return response.data;
};

export const getOrder = async (orderId: string): Promise<Order> => {
  const response = await api.get(`/orders/${orderId}`);
  return response.data;
};

export const cancelOrder = async (orderId: string): Promise<{ message: string }> => {
  const response = await api.delete(`/orders/${orderId}`);
  return response.data;
};

export const cancelAllOrders = async (): Promise<{ message: string }> => {
  const response = await api.delete('/orders');
  return response.data;
};

// Strategies
export const getStrategies = async (): Promise<Strategy[]> => {
  const response = await api.get('/strategies');
  // The engine wraps the list. This read `response.data` while Node served a
  // bare array from its own registry; repointing the route to Python in Phase 2
  // changed the shape and the cast hid it, so the strategy dropdown had been
  // empty ever since.
  return response.data.strategies ?? response.data;
};

export const getStrategy = async (strategyId: string): Promise<Strategy> => {
  const response = await api.get(`/strategies/${strategyId}`);
  return response.data;
};

// Backtest
export const runBacktest = async (request: BacktestRequest): Promise<BacktestResult> => {
  const response = await api.post('/backtest', request);
  return response.data;
};

export default api;

// -- bots -------------------------------------------------------------------

export const getBots = async (enabledOnly = false): Promise<Bot[]> => {
  const response = await api.get('/bots', { params: { enabled_only: enabledOnly } });
  return response.data.bots;
};

export const getBot = async (botId: number): Promise<Bot> => {
  const response = await api.get(`/bots/${botId}`);
  return response.data;
};

export const createBot = async (request: BotCreateRequest): Promise<Bot> => {
  const response = await api.post('/bots', request);
  return response.data;
};

export const updateBot = async (
  botId: number,
  request: BotUpdateRequest
): Promise<Bot> => {
  const response = await api.patch(`/bots/${botId}`, request);
  return response.data;
};

export const cloneBot = async (
  botId: number,
  name: string,
  parameters?: Record<string, any>
): Promise<Bot> => {
  const response = await api.post(`/bots/${botId}/clone`, { name, parameters });
  return response.data;
};

export const deleteBot = async (botId: number): Promise<void> => {
  await api.delete(`/bots/${botId}`);
};

// -- risk -------------------------------------------------------------------

export const getKillSwitch = async (): Promise<KillSwitch> => {
  const response = await api.get('/risk/kill-switch');
  return response.data;
};

export const setKillSwitch = async (
  engaged: boolean,
  reason?: string
): Promise<KillSwitch> => {
  const response = await api.post('/risk/kill-switch', { engaged, reason });
  return response.data;
};

export const getRiskRules = async (): Promise<RiskRules> => {
  const response = await api.get('/risk/rules');
  return response.data;
};

export const getRiskDecisions = async (
  botId?: number,
  limit = 100
): Promise<RiskDecision[]> => {
  const response = await api.get('/risk/decisions', {
    params: { bot_id: botId, limit },
  });
  return response.data.decisions;
};

// -- audit ------------------------------------------------------------------

export const getAudit = async (
  filters: { botId?: number; eventType?: string; limit?: number } = {}
): Promise<AuditEntry[]> => {
  const response = await api.get('/audit', {
    params: {
      bot_id: filters.botId,
      event_type: filters.eventType,
      limit: filters.limit ?? 200,
    },
  });
  return response.data.entries;
};

// -- reconciliation ---------------------------------------------------------

export const getReconciliation = async (): Promise<Reconciliation> => {
  const response = await api.get('/reconciliation');
  return response.data;
};

// -- stored backtests -------------------------------------------------------

export const getBacktestRuns = async (
  filters: { strategyId?: string; symbol?: string; limit?: number } = {}
): Promise<BacktestRunSummary[]> => {
  const response = await api.get('/backtest/runs', {
    params: {
      strategy_id: filters.strategyId,
      symbol: filters.symbol,
      limit: filters.limit ?? 50,
    },
  });
  return response.data.runs;
};

// -- live gating ------------------------------------------------------------

export const getLiveSettings = async (): Promise<LiveSettings> => {
  const response = await api.get('/live/settings');
  return response.data;
};

export const updateLiveSettings = async (changes: {
  auto_approve?: boolean;
  max_order_value?: number;
  approval_timeout_seconds?: number;
  note?: string;
}): Promise<LiveSettings> => {
  const response = await api.post('/live/settings', changes);
  return response.data;
};

export const getApprovals = async (): Promise<ApprovalQueue> => {
  const response = await api.get('/approvals');
  return response.data;
};

export const approveOrder = async (orderId: number, note?: string) => {
  const response = await api.post(`/approvals/${orderId}/approve`, { note });
  return response.data;
};

export const rejectOrder = async (orderId: number, note?: string) => {
  const response = await api.post(`/approvals/${orderId}/reject`, { note });
  return response.data;
};
