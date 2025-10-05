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
  return response.data;
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
