import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  IconButton,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteIcon from '@mui/icons-material/Delete';
import TuneIcon from '@mui/icons-material/Tune';
import BlockIcon from '@mui/icons-material/Block';
import { deleteBot, getBots, getReconciliation, updateBot } from '../utils/api';
import type { Bot } from '../types';
import BotFormDialog from '../components/BotFormDialog';

function money(value: number): string {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  });
}

/**
 * Running state, as three distinct facts rather than one green dot.
 *
 * A bot can be enabled with no runner process attached anywhere. Collapsing
 * that into "live" would misreport the single most important thing on this
 * screen, so "off", "no runner" and "running" are shown separately.
 */
function RunStatus({ bot }: { bot: Bot }) {
  if (!bot.enabled) {
    return <Chip size="small" label="off" variant="outlined" />;
  }
  if (!bot.runner_attached) {
    return (
      <Tooltip
        title={
          bot.last_activity_at
            ? `Enabled, but nothing since ${new Date(bot.last_activity_at).toLocaleTimeString()}. Start it with: python -m runner.main --bot-id ${bot.id}`
            : `Enabled, but this bot has never run. Start it with: python -m runner.main --bot-id ${bot.id}`
        }
      >
        <Chip size="small" label="no runner" color="warning" />
      </Tooltip>
    );
  }
  return <Chip size="small" label="running" color="success" />;
}

/** Today's P&L. Unknown is shown as unknown, never as zero. */
function DailyPnl({ bot }: { bot: Bot }) {
  if (bot.daily_pnl === null) {
    return (
      <Tooltip title="No start-of-day equity baseline, so today's P&L cannot be determined. The risk gate blocks every opening order in this state.">
        <Chip size="small" label="unknown" color="warning" variant="outlined" />
      </Tooltip>
    );
  }
  const positive = bot.daily_pnl >= 0;
  return (
    <Typography
      variant="body2"
      color={positive ? 'success.main' : 'error.main'}
      sx={{ fontVariantNumeric: 'tabular-nums' }}
    >
      {positive ? '+' : ''}
      {money(bot.daily_pnl)}
    </Typography>
  );
}

function BlockedChip({ bot }: { bot: Bot }) {
  const total = Object.values(bot.blocked_orders_by_rule).reduce((a, b) => a + b, 0);
  if (total === 0) return <Typography variant="body2" color="text.secondary">&mdash;</Typography>;

  const breakdown = Object.entries(bot.blocked_orders_by_rule)
    .map(([rule, count]) => `${rule}: ${count}`)
    .join('\n');

  return (
    <Tooltip title={<Box sx={{ whiteSpace: 'pre-line' }}>{breakdown}</Box>}>
      <Chip size="small" icon={<BlockIcon />} label={total} color="warning" variant="outlined" />
    </Tooltip>
  );
}

export default function BotsPage() {
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<{ mode: 'create' | 'edit' | 'clone'; bot?: Bot } | null>(
    null
  );
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: bots, isLoading, error } = useQuery({
    queryKey: ['bots'],
    queryFn: () => getBots(),
    refetchInterval: 5000,
  });

  const { data: reconciliation } = useQuery({
    queryKey: ['reconciliation'],
    queryFn: getReconciliation,
    refetchInterval: 30000,
    // A broker that is unreachable is not a page-breaking problem here.
    retry: false,
  });

  const toggle = useMutation({
    mutationFn: ({ bot, enabled }: { bot: Bot; enabled: boolean }) =>
      updateBot(bot.id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
    onError: (err: any) =>
      setActionError(err?.response?.data?.detail ?? 'Could not change the bot.'),
  });

  const remove = useMutation({
    mutationFn: (bot: Bot) => deleteBot(bot.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bots'] }),
    onError: (err: any) =>
      setActionError(err?.response?.data?.detail ?? 'Could not delete the bot.'),
  });

  if (isLoading) {
    return (
      <Container sx={{ py: 4, textAlign: 'center' }}>
        <CircularProgress />
      </Container>
    );
  }

  if (error) {
    return (
      <Container sx={{ py: 4 }}>
        <Alert severity="error">
          Could not reach the engine. Bots, their positions and the risk gate all
          live there, so nothing on this page is trustworthy until it is back.
        </Alert>
      </Container>
    );
  }

  return (
    <Container maxWidth="xl" sx={{ py: 3 }}>
      <Stack direction="row" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Bots
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setDialog({ mode: 'create' })}
        >
          New bot
        </Button>
      </Stack>

      {actionError && (
        <Alert severity="error" onClose={() => setActionError(null)} sx={{ mb: 2 }}>
          {actionError}
        </Alert>
      )}

      {reconciliation && !reconciliation.in_sync && (
        <Alert severity="error" sx={{ mb: 2 }}>
          <strong>Positions disagree with the broker.</strong> {reconciliation.summary}
          <br />
          Affected bots have been disabled. The broker is the authority; nothing is
          adopted automatically, because the reason for the drift matters more than
          making the numbers agree.
        </Alert>
      )}

      {(bots ?? []).length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="h6" gutterBottom>
            No bots yet
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            A bot is a strategy plus its parameters, symbols, budget and risk
            limits. Creating one is a record, not a code change &mdash; so you can
            clone and retune without touching the engine.
          </Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialog({ mode: 'create' })}>
            Create the first one
          </Button>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Bot</TableCell>
                <TableCell>Strategy</TableCell>
                <TableCell>Symbols</TableCell>
                <TableCell>TF</TableCell>
                <TableCell align="right">Budget</TableCell>
                <TableCell align="right">Today</TableCell>
                <TableCell>Positions</TableCell>
                <TableCell align="center">Blocked</TableCell>
                <TableCell align="center">Status</TableCell>
                <TableCell align="center">Enabled</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(bots ?? []).map((bot) => (
                <TableRow key={bot.id} hover>
                  <TableCell>
                    <Typography variant="body2">{bot.name}</Typography>
                    {bot.mode === 'live' && (
                      <Chip size="small" label="LIVE" color="error" sx={{ mt: 0.5 }} />
                    )}
                  </TableCell>
                  <TableCell>
                    <Tooltip title={JSON.stringify(bot.parameters)}>
                      <Typography variant="body2" color="text.secondary">
                        {bot.strategy_id}
                      </Typography>
                    </Tooltip>
                  </TableCell>
                  <TableCell>{bot.symbols.join(', ')}</TableCell>
                  <TableCell>{bot.timeframe}</TableCell>
                  <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {money(bot.capital_budget)}
                  </TableCell>
                  <TableCell align="right">
                    <DailyPnl bot={bot} />
                  </TableCell>
                  <TableCell>
                    {bot.open_positions.length === 0 ? (
                      <Typography variant="body2" color="text.secondary">
                        flat
                      </Typography>
                    ) : (
                      bot.open_positions.map((p) => (
                        <Chip
                          key={p.symbol}
                          size="small"
                          label={`${p.qty > 0 ? '+' : ''}${p.qty} ${p.symbol}`}
                          color={p.qty > 0 ? 'primary' : 'secondary'}
                          sx={{ mr: 0.5 }}
                        />
                      ))
                    )}
                  </TableCell>
                  <TableCell align="center">
                    <BlockedChip bot={bot} />
                  </TableCell>
                  <TableCell align="center">
                    <RunStatus bot={bot} />
                  </TableCell>
                  <TableCell align="center">
                    <Switch
                      checked={bot.enabled}
                      onChange={(e) => toggle.mutate({ bot, enabled: e.target.checked })}
                      disabled={toggle.isPending}
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Tooltip title="Tune parameters and risk limits">
                      <IconButton size="small" onClick={() => setDialog({ mode: 'edit', bot })}>
                        <TuneIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Clone into a new bot">
                      <IconButton size="small" onClick={() => setDialog({ mode: 'clone', bot })}>
                        <ContentCopyIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip
                      title={
                        bot.open_positions.length > 0
                          ? 'Cannot delete while it holds a position'
                          : 'Delete'
                      }
                    >
                      <IconButton
                        size="small"
                        color="error"
                        disabled={bot.open_positions.length > 0}
                        onClick={() => remove.mutate(bot)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
        Enabling a bot records intent. A runner process has to be attached for it
        to actually trade: <code>python -m runner.main --bot-id N</code>, one
        process per symbol.
      </Typography>

      {dialog && (
        <BotFormDialog
          open
          mode={dialog.mode}
          bot={dialog.bot}
          onClose={() => setDialog(null)}
        />
      )}
    </Container>
  );
}
