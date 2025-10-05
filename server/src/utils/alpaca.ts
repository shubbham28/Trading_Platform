import Alpaca from '@alpacahq/alpaca-trade-api';
import { Asset, Bar, Account, Position, Order, OrderRequest } from '../types';

class AlpacaClient {
  private client: Alpaca;

  constructor() {
    const apiKey = process.env.ALPACA_API_KEY;
    const apiSecret = process.env.ALPACA_API_SECRET;
    const baseUrl = process.env.ALPACA_BASE_URL || 'https://paper-api.alpaca.markets';

    if (!apiKey || !apiSecret) {
      throw new Error('Alpaca API credentials not configured');
    }

    this.client = new Alpaca({
      keyId: apiKey,
      secretKey: apiSecret,
      baseUrl: baseUrl,
      paper: process.env.TRADING_MODE !== 'live',
    });
  }

  // Asset methods
  async getAssets(status: string = 'active', assetClass?: string): Promise<Asset[]> {
    try {
      const assets = await this.client.getAssets({ status, asset_class: assetClass });
      return assets as Asset[];
    } catch (error) {
      console.error('Error fetching assets:', error);
      throw error;
    }
  }

  async getAsset(symbol: string): Promise<Asset> {
    try {
      const asset = await this.client.getAsset(symbol);
      return asset as Asset;
    } catch (error) {
      console.error(`Error fetching asset ${symbol}:`, error);
      throw error;
    }
  }

  // Market data methods
  async getBars(
    symbol: string,
    timeframe: string,
    start: string,
    end?: string,
    limit?: number
  ): Promise<Bar[]> {
    try {
      const bars = await this.client.getBarsV2(symbol, {
        timeframe,
        start,
        end,
        limit: limit || 1000,
      });

      const result: Bar[] = [];
      for await (const bar of bars) {
        result.push(bar as Bar);
      }
      return result;
    } catch (error) {
      console.error(`Error fetching bars for ${symbol}:`, error);
      throw error;
    }
  }

  async getLatestBar(symbol: string): Promise<Bar> {
    try {
      const bar = await this.client.getLatestBar(symbol);
      return bar as Bar;
    } catch (error) {
      console.error(`Error fetching latest bar for ${symbol}:`, error);
      throw error;
    }
  }

  async getLatestQuote(symbol: string): Promise<any> {
    try {
      const quote = await this.client.getLatestQuote(symbol);
      return quote;
    } catch (error) {
      console.error(`Error fetching latest quote for ${symbol}:`, error);
      throw error;
    }
  }

  // Account methods
  async getAccount(): Promise<Account> {
    try {
      const account = await this.client.getAccount();
      return account as Account;
    } catch (error) {
      console.error('Error fetching account:', error);
      throw error;
    }
  }

  // Position methods
  async getPositions(): Promise<Position[]> {
    try {
      const positions = await this.client.getPositions();
      return positions as Position[];
    } catch (error) {
      console.error('Error fetching positions:', error);
      throw error;
    }
  }

  async getPosition(symbol: string): Promise<Position> {
    try {
      const position = await this.client.getPosition(symbol);
      return position as Position;
    } catch (error) {
      console.error(`Error fetching position for ${symbol}:`, error);
      throw error;
    }
  }

  async closePosition(symbol: string): Promise<Order> {
    try {
      const order = await this.client.closePosition(symbol);
      return order as Order;
    } catch (error) {
      console.error(`Error closing position for ${symbol}:`, error);
      throw error;
    }
  }

  // Order methods
  async createOrder(orderRequest: OrderRequest): Promise<Order> {
    try {
      const order = await this.client.createOrder({
        symbol: orderRequest.symbol,
        qty: orderRequest.qty,
        side: orderRequest.side,
        type: orderRequest.type,
        time_in_force: orderRequest.time_in_force,
        limit_price: orderRequest.limit_price,
        stop_price: orderRequest.stop_price,
        extended_hours: orderRequest.extended_hours || false,
        client_order_id: orderRequest.client_order_id,
      });
      return order as Order;
    } catch (error) {
      console.error('Error creating order:', error);
      throw error;
    }
  }

  async getOrders(status?: string, limit?: number): Promise<Order[]> {
    try {
      const orders = await this.client.getOrders({
        status: status || 'all',
        limit: limit || 100,
      });
      return orders as Order[];
    } catch (error) {
      console.error('Error fetching orders:', error);
      throw error;
    }
  }

  async getOrder(orderId: string): Promise<Order> {
    try {
      const order = await this.client.getOrder(orderId);
      return order as Order;
    } catch (error) {
      console.error(`Error fetching order ${orderId}:`, error);
      throw error;
    }
  }

  async cancelOrder(orderId: string): Promise<void> {
    try {
      await this.client.cancelOrder(orderId);
    } catch (error) {
      console.error(`Error canceling order ${orderId}:`, error);
      throw error;
    }
  }

  async cancelAllOrders(): Promise<void> {
    try {
      await this.client.cancelAllOrders();
    } catch (error) {
      console.error('Error canceling all orders:', error);
      throw error;
    }
  }
}

export default new AlpacaClient();
