import React from 'react';
import {
  Card,
  CardContent,
  Typography,
  Grid,
  Box,
  Chip,
} from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import type { Bar } from '../types';

interface QuoteHeaderProps {
  symbol: string;
  latestBar?: Bar;
  loading?: boolean;
}

const QuoteHeader: React.FC<QuoteHeaderProps> = ({ symbol, latestBar, loading }) => {
  if (loading) {
    return (
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="h5">Loading...</Typography>
        </CardContent>
      </Card>
    );
  }

  if (!latestBar) {
    return null;
  }

  const price = latestBar.c;
  const change = latestBar.c - latestBar.o;
  const changePercent = (change / latestBar.o) * 100;
  const isPositive = change >= 0;

  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={4}>
            <Typography variant="h4" component="div">
              {symbol}
            </Typography>
            <Typography variant="h5" color={isPositive ? 'success.main' : 'error.main'}>
              ${price.toFixed(2)}
            </Typography>
          </Grid>
          <Grid item xs={12} md={4}>
            <Box display="flex" alignItems="center" gap={1}>
              {isPositive ? (
                <TrendingUpIcon color="success" />
              ) : (
                <TrendingDownIcon color="error" />
              )}
              <Chip
                label={`${isPositive ? '+' : ''}${change.toFixed(2)} (${isPositive ? '+' : ''}${changePercent.toFixed(2)}%)`}
                color={isPositive ? 'success' : 'error'}
                size="small"
              />
            </Box>
          </Grid>
          <Grid item xs={12} md={4}>
            <Typography variant="body2" color="text.secondary">
              Open: ${latestBar.o.toFixed(2)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              High: ${latestBar.h.toFixed(2)} | Low: ${latestBar.l.toFixed(2)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Volume: {latestBar.v.toLocaleString()}
            </Typography>
          </Grid>
        </Grid>
      </CardContent>
    </Card>
  );
};

export default QuoteHeader;
