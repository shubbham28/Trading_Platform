import React from 'react';
import {
  Container,
  Grid,
  Card,
  CardContent,
  Typography,
  Box,
  CircularProgress,
  Chip,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import { getAccount, getPositions } from '../utils/api';

const AccountPage: React.FC = () => {
  const { data: account, isLoading: accountLoading } = useQuery({
    queryKey: ['account'],
    queryFn: getAccount,
  });

  const { data: positions, isLoading: positionsLoading } = useQuery({
    queryKey: ['positions'],
    queryFn: getPositions,
  });

  if (accountLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" height="60vh">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Container maxWidth="xl" sx={{ py: 3 }}>
      <Typography variant="h4" gutterBottom>
        Account Overview
      </Typography>

      {/* Account Summary */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Portfolio Value
              </Typography>
              <Typography variant="h5">
                ${parseFloat(account?.portfolio_value || '0').toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Buying Power
              </Typography>
              <Typography variant="h5">
                ${parseFloat(account?.buying_power || '0').toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Cash
              </Typography>
              <Typography variant="h5">
                ${parseFloat(account?.cash || '0').toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={3}>
          <Card>
            <CardContent>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Status
              </Typography>
              <Chip
                label={account?.status}
                color={account?.status === 'ACTIVE' ? 'success' : 'default'}
                size="small"
              />
              {account?.pattern_day_trader && (
                <Chip label="PDT" color="warning" size="small" sx={{ ml: 1 }} />
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* Positions */}
      <Typography variant="h5" gutterBottom sx={{ mt: 4 }}>
        Open Positions
      </Typography>
      {positionsLoading ? (
        <Box display="flex" justifyContent="center" py={3}>
          <CircularProgress />
        </Box>
      ) : positions && positions.length > 0 ? (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Symbol</TableCell>
                <TableCell align="right">Quantity</TableCell>
                <TableCell align="right">Avg Entry Price</TableCell>
                <TableCell align="right">Current Price</TableCell>
                <TableCell align="right">Market Value</TableCell>
                <TableCell align="right">Unrealized P&L</TableCell>
                <TableCell align="right">Unrealized P&L %</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {positions.map((position) => {
                const isProfit = parseFloat(position.unrealized_pl) >= 0;
                return (
                  <TableRow key={position.symbol}>
                    <TableCell>
                      <Typography fontWeight="medium">{position.symbol}</Typography>
                    </TableCell>
                    <TableCell align="right">{position.qty}</TableCell>
                    <TableCell align="right">
                      ${parseFloat(position.avg_entry_price).toFixed(2)}
                    </TableCell>
                    <TableCell align="right">
                      ${parseFloat(position.current_price).toFixed(2)}
                    </TableCell>
                    <TableCell align="right">
                      ${parseFloat(position.market_value).toFixed(2)}
                    </TableCell>
                    <TableCell align="right">
                      <Box display="flex" alignItems="center" justifyContent="flex-end" gap={0.5}>
                        {isProfit ? <TrendingUpIcon color="success" fontSize="small" /> : <TrendingDownIcon color="error" fontSize="small" />}
                        <Typography color={isProfit ? 'success.main' : 'error.main'}>
                          ${parseFloat(position.unrealized_pl).toFixed(2)}
                        </Typography>
                      </Box>
                    </TableCell>
                    <TableCell align="right">
                      <Typography color={isProfit ? 'success.main' : 'error.main'}>
                        {(parseFloat(position.unrealized_plpc) * 100).toFixed(2)}%
                      </Typography>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Paper sx={{ p: 3, textAlign: 'center' }}>
          <Typography color="text.secondary">No open positions</Typography>
        </Paper>
      )}
    </Container>
  );
};

export default AccountPage;
