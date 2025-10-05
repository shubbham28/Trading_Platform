import React, { useState } from 'react';
import {
  Container,
  Grid,
  Box,
  CircularProgress,
  Typography,
} from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { format, subMonths } from 'date-fns';
import TickerList from '../components/TickerList';
import QuoteHeader from '../components/QuoteHeader';
import OHLCChart from '../components/OHLCChart';
import OrderTicket from '../components/OrderTicket';
import BacktestPanel from '../components/BacktestPanel';
import { getLatestBar, getBars } from '../utils/api';

const TradingPage: React.FC = () => {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('AAPL');

  const { data: latestBarData, isLoading: latestBarLoading } = useQuery({
    queryKey: ['latestBar', selectedSymbol],
    queryFn: () => getLatestBar(selectedSymbol),
    enabled: !!selectedSymbol,
    refetchInterval: 60000, // Refetch every minute
  });

  const { data: barsData, isLoading: barsLoading } = useQuery({
    queryKey: ['bars', selectedSymbol],
    queryFn: () => getBars(
      selectedSymbol,
      '1Day',
      format(subMonths(new Date(), 6), 'yyyy-MM-dd'),
      format(new Date(), 'yyyy-MM-dd')
    ),
    enabled: !!selectedSymbol,
  });

  return (
    <Container maxWidth="xl" sx={{ py: 3 }}>
      <Grid container spacing={3}>
        {/* Left sidebar - Ticker list */}
        <Grid item xs={12} md={3}>
          <TickerList
            onSelectSymbol={setSelectedSymbol}
            selectedSymbol={selectedSymbol}
          />
        </Grid>

        {/* Main content */}
        <Grid item xs={12} md={9}>
          {selectedSymbol ? (
            <Box>
              {/* Quote Header */}
              <QuoteHeader
                symbol={selectedSymbol}
                latestBar={latestBarData?.bar}
                loading={latestBarLoading}
              />

              {/* Chart */}
              {barsLoading ? (
                <Box display="flex" justifyContent="center" alignItems="center" height={400}>
                  <CircularProgress />
                </Box>
              ) : barsData?.bars && barsData.bars.length > 0 ? (
                <Box mb={3}>
                  <OHLCChart symbol={selectedSymbol} bars={barsData.bars} />
                </Box>
              ) : (
                <Typography>No chart data available</Typography>
              )}

              {/* Order Ticket and Backtest */}
              <Grid container spacing={3}>
                <Grid item xs={12} md={6}>
                  <OrderTicket
                    symbol={selectedSymbol}
                    currentPrice={latestBarData?.bar?.c}
                  />
                </Grid>
                <Grid item xs={12} md={6}>
                  <BacktestPanel symbol={selectedSymbol} />
                </Grid>
              </Grid>
            </Box>
          ) : (
            <Box display="flex" justifyContent="center" alignItems="center" height="60vh">
              <Typography variant="h6" color="text.secondary">
                Select a symbol to start trading
              </Typography>
            </Box>
          )}
        </Grid>
      </Grid>
    </Container>
  );
};

export default TradingPage;
