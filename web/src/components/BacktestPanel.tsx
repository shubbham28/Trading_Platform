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
  CircularProgress,
} from '@mui/material';
import { useQuery, useMutation } from '@tanstack/react-query';
import { format, subMonths } from 'date-fns';
import { getStrategies, runBacktest } from '../utils/api';
import type { BacktestRequest, BacktestResult } from '../types';

interface BacktestPanelProps {
  symbol: string;
  onResult?: (result: BacktestResult) => void;
}

const BacktestPanel: React.FC<BacktestPanelProps> = ({ symbol, onResult }) => {
  const [formData, setFormData] = useState<BacktestRequest>({
    symbol: symbol,
    strategyId: '',
    startDate: format(subMonths(new Date(), 6), 'yyyy-MM-dd'),
    endDate: format(new Date(), 'yyyy-MM-dd'),
    initialCapital: 10000,
    timeframe: '1Day',
  });
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: strategies, isLoading: strategiesLoading } = useQuery({
    queryKey: ['strategies'],
    queryFn: getStrategies,
  });

  const mutation = useMutation({
    mutationFn: runBacktest,
    onSuccess: (data) => {
      setResult(data);
      setError(null);
      if (onResult) {
        onResult(data);
      }
    },
    onError: (err: any) => {
      setError(err.response?.data?.error || 'Failed to run backtest');
      setResult(null);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    mutation.mutate({ ...formData, symbol });
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Backtest Strategy
        </Typography>
        <form onSubmit={handleSubmit}>
          <Grid container spacing={2}>
            <Grid item xs={12}>
              <FormControl fullWidth disabled={strategiesLoading}>
                <InputLabel>Strategy</InputLabel>
                <Select
                  value={formData.strategyId}
                  label="Strategy"
                  onChange={(e) => setFormData({ ...formData, strategyId: e.target.value })}
                >
                  {strategies?.map((strategy) => (
                    <MenuItem key={strategy.id} value={strategy.id}>
                      {strategy.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                type="date"
                label="Start Date"
                value={formData.startDate}
                onChange={(e) => setFormData({ ...formData, startDate: e.target.value })}
                InputLabelProps={{ shrink: true }}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                type="date"
                label="End Date"
                value={formData.endDate}
                onChange={(e) => setFormData({ ...formData, endDate: e.target.value })}
                InputLabelProps={{ shrink: true }}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                type="number"
                label="Initial Capital"
                value={formData.initialCapital}
                onChange={(e) => setFormData({ ...formData, initialCapital: parseFloat(e.target.value) || 0 })}
                inputProps={{ min: 100, step: 100 }}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth>
                <InputLabel>Timeframe</InputLabel>
                <Select
                  value={formData.timeframe}
                  label="Timeframe"
                  onChange={(e) => setFormData({ ...formData, timeframe: e.target.value })}
                >
                  <MenuItem value="1Min">1 Minute</MenuItem>
                  <MenuItem value="5Min">5 Minutes</MenuItem>
                  <MenuItem value="15Min">15 Minutes</MenuItem>
                  <MenuItem value="1Hour">1 Hour</MenuItem>
                  <MenuItem value="1Day">1 Day</MenuItem>
                </Select>
              </FormControl>
            </Grid>
          </Grid>

          {error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          )}

          {result && (
            <Box mt={2}>
              <Alert severity="success" sx={{ mb: 2 }}>
                Backtest completed successfully!
              </Alert>
              <Grid container spacing={2}>
                <Grid item xs={6} md={4}>
                  <Typography variant="body2" color="text.secondary">
                    Total Return
                  </Typography>
                  <Typography variant="h6" color={result.total_return >= 0 ? 'success.main' : 'error.main'}>
                    ${result.total_return.toFixed(2)} ({result.total_return_pct.toFixed(2)}%)
                  </Typography>
                </Grid>
                <Grid item xs={6} md={4}>
                  <Typography variant="body2" color="text.secondary">
                    Sharpe Ratio
                  </Typography>
                  <Typography variant="h6">{result.sharpe_ratio.toFixed(2)}</Typography>
                </Grid>
                <Grid item xs={6} md={4}>
                  <Typography variant="body2" color="text.secondary">
                    Max Drawdown
                  </Typography>
                  <Typography variant="h6" color="error.main">
                    {(result.max_drawdown * 100).toFixed(2)}%
                  </Typography>
                </Grid>
                <Grid item xs={6} md={4}>
                  <Typography variant="body2" color="text.secondary">
                    Total Trades
                  </Typography>
                  <Typography variant="h6">{result.total_trades}</Typography>
                </Grid>
                <Grid item xs={6} md={4}>
                  <Typography variant="body2" color="text.secondary">
                    Win Rate
                  </Typography>
                  <Typography variant="h6">{result.win_rate.toFixed(2)}%</Typography>
                </Grid>
                <Grid item xs={6} md={4}>
                  <Typography variant="body2" color="text.secondary">
                    Final Capital
                  </Typography>
                  <Typography variant="h6">${result.final_capital.toFixed(2)}</Typography>
                </Grid>
              </Grid>
            </Box>
          )}

          <Button
            type="submit"
            variant="contained"
            color="primary"
            fullWidth
            sx={{ mt: 2 }}
            disabled={mutation.isPending || !formData.strategyId}
            startIcon={mutation.isPending && <CircularProgress size={20} />}
          >
            {mutation.isPending ? 'Running Backtest...' : 'Run Backtest'}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};

export default BacktestPanel;
