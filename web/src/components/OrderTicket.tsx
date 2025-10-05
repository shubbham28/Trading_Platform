import React, { useState } from 'react';
import {
  Card,
  CardContent,
  Typography,
  TextField,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Grid,
  Alert,
  Box,
} from '@mui/material';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createOrder } from '../utils/api';
import type { OrderRequest } from '../types';

interface OrderTicketProps {
  symbol: string;
  currentPrice?: number;
}

const OrderTicket: React.FC<OrderTicketProps> = ({ symbol, currentPrice }) => {
  const queryClient = useQueryClient();
  const [formData, setFormData] = useState<OrderRequest>({
    symbol: symbol,
    qty: 1,
    side: 'buy',
    type: 'market',
    time_in_force: 'day',
  });
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: createOrder,
    onSuccess: (data) => {
      setSuccess(`Order placed successfully! Order ID: ${data.id}`);
      setError(null);
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['positions'] });
      queryClient.invalidateQueries({ queryKey: ['account'] });
    },
    onError: (err: any) => {
      setError(err.response?.data?.error || 'Failed to place order');
      setSuccess(null);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    mutation.mutate({ ...formData, symbol });
  };

  const estimatedValue = currentPrice ? currentPrice * formData.qty : 0;

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Order Ticket
        </Typography>
        <form onSubmit={handleSubmit}>
          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth>
                <InputLabel>Side</InputLabel>
                <Select
                  value={formData.side}
                  label="Side"
                  onChange={(e) => setFormData({ ...formData, side: e.target.value as 'buy' | 'sell' })}
                >
                  <MenuItem value="buy">Buy</MenuItem>
                  <MenuItem value="sell">Sell</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth>
                <InputLabel>Order Type</InputLabel>
                <Select
                  value={formData.type}
                  label="Order Type"
                  onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
                >
                  <MenuItem value="market">Market</MenuItem>
                  <MenuItem value="limit">Limit</MenuItem>
                  <MenuItem value="stop">Stop</MenuItem>
                  <MenuItem value="stop_limit">Stop Limit</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                type="number"
                label="Quantity"
                value={formData.qty}
                onChange={(e) => setFormData({ ...formData, qty: parseInt(e.target.value) || 0 })}
                inputProps={{ min: 1 }}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth>
                <InputLabel>Time in Force</InputLabel>
                <Select
                  value={formData.time_in_force}
                  label="Time in Force"
                  onChange={(e) => setFormData({ ...formData, time_in_force: e.target.value as any })}
                >
                  <MenuItem value="day">Day</MenuItem>
                  <MenuItem value="gtc">GTC (Good Till Canceled)</MenuItem>
                  <MenuItem value="ioc">IOC (Immediate or Cancel)</MenuItem>
                  <MenuItem value="fok">FOK (Fill or Kill)</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            {(formData.type === 'limit' || formData.type === 'stop_limit') && (
              <Grid item xs={12} md={6}>
                <TextField
                  fullWidth
                  type="number"
                  label="Limit Price"
                  value={formData.limit_price || ''}
                  onChange={(e) => setFormData({ ...formData, limit_price: parseFloat(e.target.value) || undefined })}
                  inputProps={{ step: 0.01 }}
                />
              </Grid>
            )}
            {(formData.type === 'stop' || formData.type === 'stop_limit') && (
              <Grid item xs={12} md={6}>
                <TextField
                  fullWidth
                  type="number"
                  label="Stop Price"
                  value={formData.stop_price || ''}
                  onChange={(e) => setFormData({ ...formData, stop_price: parseFloat(e.target.value) || undefined })}
                  inputProps={{ step: 0.01 }}
                />
              </Grid>
            )}
          </Grid>

          {currentPrice && (
            <Box mt={2}>
              <Typography variant="body2" color="text.secondary">
                Estimated Value: ${estimatedValue.toFixed(2)}
              </Typography>
            </Box>
          )}

          {error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          )}

          {success && (
            <Alert severity="success" sx={{ mt: 2 }}>
              {success}
            </Alert>
          )}

          <Button
            type="submit"
            variant="contained"
            color={formData.side === 'buy' ? 'success' : 'error'}
            fullWidth
            sx={{ mt: 2 }}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? 'Placing Order...' : `Place ${formData.side.toUpperCase()} Order`}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};

export default OrderTicket;
