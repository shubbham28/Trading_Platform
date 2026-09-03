import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  Chip,
  CircularProgress,
  Container,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { getBacktestRuns } from '../utils/api';
import type { BacktestRunSummary } from '../types';

function num(value: any, digits = 2): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : '—';
}

/**
 * The cost assumptions a run was produced under, shown on every row.
 *
 * A return figure without them is not comparable to the row above it: 40% at
 * zero slippage and 40% at 5bp are different results, and the old engine
 * reported both as simply 40%. Never show one without the other.
 */
function CostChip({ run }: { run: BacktestRunSummary }) {
  const slippage = run.config?.slippage_bps;
  const commission = run.config?.commission;
  const sizing = run.config?.max_position_pct;

  return (
    <Tooltip
      title={
        <>
          slippage {num(slippage, 1)}bp · commission {num(commission, 4)} ·
          position {num(sizing, 0)}% of capital ·
          shorts {run.config?.allow_short ? 'on' : 'off'}
        </>
      }
    >
      <Chip
        size="small"
        variant="outlined"
        label={`${num(slippage, 1)}bp / ${num(sizing, 0)}%`}
      />
    </Tooltip>
  );
}

/**
 * Whatever the engine could not do during the run.
 *
 * An empty audit is a meaningful result. A populated one usually means the
 * reported performance is not the strategy's performance, so it belongs next to
 * the numbers rather than behind a click.
 */
function AuditWarnings({ run }: { run: BacktestRunSummary }) {
  const audit = run.audit ?? {};
  const problems: string[] = [];

  if (audit.intents_unfilled_no_next_bar > 0)
    problems.push(`${audit.intents_unfilled_no_next_bar} intent(s) had no bar to fill against`);
  if (audit.intents_rejected_insufficient_capital > 0)
    problems.push(`${audit.intents_rejected_insufficient_capital} rejected for capital`);
  if (audit.intents_rejected_shorts_disabled > 0)
    problems.push(`${audit.intents_rejected_shorts_disabled} shorts rejected (shorts off)`);
  if (audit.forced_liquidations > 0)
    problems.push(`${audit.forced_liquidations} position(s) closed by end of data, not by the strategy`);
  if ((audit.sessions_with_early_close_risk ?? []).length > 0)
    problems.push(
      `possible unhandled half-day: ${audit.sessions_with_early_close_risk.join(', ')} — flatten-by-close may never have fired`
    );

  if (problems.length === 0) {
    return <Typography variant="body2" color="text.secondary">clean</Typography>;
  }

  return (
    <Tooltip title={problems.join(' · ')}>
      <Chip
        size="small"
        icon={<WarningAmberIcon />}
        color="warning"
        label={problems.length}
      />
    </Tooltip>
  );
}

export default function BacktestsPage() {
  const [sortKey, setSortKey] = useState<'created' | 'return' | 'sharpe'>('created');

  const { data: runs, isLoading, error } = useQuery({
    queryKey: ['backtest-runs'],
    queryFn: () => getBacktestRuns({ limit: 100 }),
  });

  const sorted = [...(runs ?? [])].sort((a, b) => {
    if (sortKey === 'return')
      return (b.metrics?.total_return_pct ?? 0) - (a.metrics?.total_return_pct ?? 0);
    if (sortKey === 'sharpe')
      return (b.metrics?.sharpe_ratio ?? 0) - (a.metrics?.sharpe_ratio ?? 0);
    return b.id - a.id;
  });

  if (isLoading) return <Container sx={{ py: 4 }}><CircularProgress /></Container>;
  if (error)
    return (
      <Container sx={{ py: 4 }}>
        <Alert severity="error">Could not reach the engine.</Alert>
      </Container>
    );

  return (
    <Container maxWidth="xl" sx={{ py: 3 }}>
      <Typography variant="h5" gutterBottom>
        Stored backtests
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Every run keeps the cost assumptions and the execution audit that
        produced it. Two runs are only comparable when you can see what each one
        assumed &mdash; sort by return and the cheapest assumptions win, which is
        exactly the trap this column exists to close.
      </Typography>

      {sorted.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body1" gutterBottom>
            No stored runs
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Run a backtest from the Trading page and it is stored here
            automatically, with its costs and its audit.
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>#</TableCell>
                <TableCell>Strategy</TableCell>
                <TableCell>Symbol</TableCell>
                <TableCell>TF</TableCell>
                <TableCell>Period</TableCell>
                <TableCell
                  align="right"
                  onClick={() => setSortKey('return')}
                  sx={{ cursor: 'pointer', fontWeight: sortKey === 'return' ? 700 : 400 }}
                >
                  Return %
                </TableCell>
                <TableCell
                  align="right"
                  onClick={() => setSortKey('sharpe')}
                  sx={{ cursor: 'pointer', fontWeight: sortKey === 'sharpe' ? 700 : 400 }}
                >
                  Sharpe
                </TableCell>
                <TableCell align="right">Max DD %</TableCell>
                <TableCell align="right">Trades</TableCell>
                <TableCell align="right">Win %</TableCell>
                <TableCell align="center">Costs</TableCell>
                <TableCell align="center">Audit</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sorted.map((run) => {
                const returnPct = run.metrics?.total_return_pct ?? 0;
                return (
                  <TableRow key={run.id} hover>
                    <TableCell>{run.id}</TableCell>
                    <TableCell>
                      <Tooltip title={JSON.stringify(run.parameters)}>
                        <span>{run.strategy_id}</span>
                      </Tooltip>
                    </TableCell>
                    <TableCell>{run.symbol}</TableCell>
                    <TableCell>{run.timeframe}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      {run.start_date} → {run.end_date}
                    </TableCell>
                    <TableCell
                      align="right"
                      sx={{
                        fontVariantNumeric: 'tabular-nums',
                        color: returnPct >= 0 ? 'success.main' : 'error.main',
                      }}
                    >
                      {num(returnPct)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {num(run.metrics?.sharpe_ratio)}
                    </TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {num(run.metrics?.max_drawdown_pct)}
                    </TableCell>
                    <TableCell align="right">{run.metrics?.total_trades ?? 0}</TableCell>
                    <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                      {num(run.metrics?.win_rate, 1)}
                    </TableCell>
                    <TableCell align="center">
                      <CostChip run={run} />
                    </TableCell>
                    <TableCell align="center">
                      <AuditWarnings run={run} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Container>
  );
}
