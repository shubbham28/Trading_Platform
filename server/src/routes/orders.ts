import { Router, Request, Response } from 'express';
import alpacaClient from '../utils/alpaca';
import { OrderRequest } from '../types';

const router = Router();

// Get all orders
router.get('/', async (req: Request, res: Response) => {
  try {
    const { status, limit } = req.query;
    const orders = await alpacaClient.getOrders(
      status as string | undefined,
      limit ? parseInt(limit as string) : undefined
    );
    res.json(orders);
  } catch (error: any) {
    console.error('Error in GET /api/orders:', error);
    res.status(500).json({ error: error.message || 'Failed to fetch orders' });
  }
});

// Create a new order
router.post('/', async (req: Request, res: Response) => {
  try {
    const orderRequest: OrderRequest = req.body;

    // Validate required fields
    if (!orderRequest.symbol || !orderRequest.qty || !orderRequest.side || !orderRequest.type) {
      return res.status(400).json({ error: 'Missing required fields: symbol, qty, side, type' });
    }

    // Create order
    const order = await alpacaClient.createOrder(orderRequest);
    res.status(201).json(order);
  } catch (error: any) {
    console.error('Error in POST /api/orders:', error);
    res.status(500).json({ error: error.message || 'Failed to create order' });
  }
});

// Get specific order by ID
router.get('/:orderId', async (req: Request, res: Response) => {
  try {
    const { orderId } = req.params;
    const order = await alpacaClient.getOrder(orderId);
    res.json(order);
  } catch (error: any) {
    console.error(`Error in GET /api/orders/${req.params.orderId}:`, error);
    res.status(404).json({ error: error.message || 'Order not found' });
  }
});

// Cancel specific order
router.delete('/:orderId', async (req: Request, res: Response) => {
  try {
    const { orderId } = req.params;
    await alpacaClient.cancelOrder(orderId);
    res.json({ message: 'Order canceled successfully' });
  } catch (error: any) {
    console.error(`Error in DELETE /api/orders/${req.params.orderId}:`, error);
    res.status(500).json({ error: error.message || 'Failed to cancel order' });
  }
});

// Cancel all orders
router.delete('/', async (req: Request, res: Response) => {
  try {
    await alpacaClient.cancelAllOrders();
    res.json({ message: 'All orders canceled successfully' });
  } catch (error: any) {
    console.error('Error in DELETE /api/orders:', error);
    res.status(500).json({ error: error.message || 'Failed to cancel all orders' });
  }
});

export default router;
