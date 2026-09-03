import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Container,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import { getAudit, getBots } from '../utils/api';
import type { AuditEntry } from '../types';

/**
 * Every event type the engine writes, with the colour it gets.
 *
 * Listed explicitly rather than hashed from the string: these are the words
 * that appear when something has gone wrong, and a halt should not be the same
 * colour as a routine hold because a hash function said so.
 */
const EVENT_COLOURS: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'error' | 'info'> = {
  signal: 'default',
  risk_decision: 'info',
  order_submitted: 'primary',
  fill: 'success',
  order_rejected: 'error',
  live_blocked: 'error',
  reconciliation: 'info',
  bot_halted: 'error',
  tick_error: 'error',
  forced_flatten: 'warning',
  kill_switch: 'error',
  session: 'default',
  bot_updated: 'default',
  bot_deleted: 'warning',
  short_blocked: 'warning',
  // Live gating. Everything that touches real money is coloured to stand out.
  approval_requested: 'warning',
  approval_granted: 'success',
  approval_denied: 'default',
  approval_expired: 'warning',
  live_settings_changed: 'error',
};

const EVENT_TYPES = Object.keys(EVENT_COLOURS);

/** The one line that matters, pulled out of the payload per event type. */
function summarise(entry: AuditEntry): string {
  const p = entry.payload ?? {};
  switch (entry.event_type) {
    case 'signal':
      return `${p.action ?? '?'} — ${p.reason ?? ''}`;
    case 'risk_decision':
      return p.allowed
        ? `allowed${p.is_reducing ? ' (exit, limits do not apply)' : ''}`
        : `BLOCKED by ${p.rule}: ${p.detail ?? ''}`;
    case 'order_submitted':
      return `${p.side} ${p.qty} → ${p.status} (${p.broker_order_id ?? 'no id'})`;
    case 'fill':
      return `${p.side} ${p.qty} @ ${p.price} → position ${p.resulting_position_qty}`;
    case 'reconciliation':
      if (p.action === 'adopted_broker_state') return `adopted broker state: ${p.note}`;
      return p.in_sync ? 'in sync' : `DIVERGED: ${JSON.stringify(p.divergences)}`;
    case 'bot_halted':
      return `${p.reason}: ${p.detail ?? ''}`;
    case 'tick_error':
      return p.error ?? '';
    case 'forced_flatten':
      return p.reason ?? '';
    case 'kill_switch':
      return p.engaged ? `ENGAGED: ${p.reason ?? 'no reason'}` : 'released';
    case 'live_blocked':
      return p.reason ?? '';
    case 'short_blocked':
      return p.reason ?? '';
    case 'approval_requested':
      return `${p.side} ${p.qty} ${p.symbol} awaiting a decision — ${p.reason ?? ''}`;
    case 'approval_granted':
      return `APPROVED ${p.side} ${p.qty} ${p.symbol} after ${p.waited_seconds}s${p.note ? ` — ${p.note}` : ''}`;
    case 'approval_denied':
      return `rejected ${p.side} ${p.qty} ${p.symbol}${p.note ? ` — ${p.note}` : ''}`;
    case 'approval_expired':
      return `EXPIRED unapproved after ${p.age_seconds}s (timeout ${p.timeout_seconds}s)`;
    case 'live_settings_changed':
      return `auto_approve ${p.before?.auto_approve} → ${p.after?.auto_approve}, ceiling ${p.before?.max_order_value} → ${p.after?.max_order_value}${p.note ? ` — ${p.note}` : ''}`;
    case 'session':
      return `${p.event} (equity ${p.account_equity})`;
    default:
      return JSON.stringify(p).slice(0, 160);
  }
}

export default function AuditPage() {
  const [botId, setBotId] = useState<string>('');
  const [eventType, setEventType] = useState<string>('');

  const { data: bots } = useQuery({ queryKey: ['bots'], queryFn: () => getBots() });
  const { data: entries, isLoading, error } = useQuery({
    queryKey: ['audit', botId, eventType],
    queryFn: () =>
      getAudit({
        botId: botId === '' ? undefined : Number(botId),
        eventType: eventType === '' ? undefined : eventType,
        limit: 300,
      }),
    refetchInterval: 5000,
  });

  return (
    <Container maxWidth="xl" sx={{ py: 3 }}>
      <Typography variant="h5" gutterBottom>
        Audit log
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Append-only. Every signal, gate decision, order, fill, reconciliation and
        halt, with the inputs that produced it. Holds are recorded too &mdash;
        without them there is no way to tell a bot that was blocked from one that
        never had a signal.
      </Typography>

      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <TextField
          select
          size="small"
          label="Bot"
          value={botId}
          onChange={(e) => setBotId(e.target.value)}
          sx={{ minWidth: 200 }}
        >
          <MenuItem value="">All bots</MenuItem>
          {(bots ?? []).map((bot) => (
            <MenuItem key={bot.id} value={String(bot.id)}>
              {bot.name}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          label="Event type"
          value={eventType}
          onChange={(e) => setEventType(e.target.value)}
          sx={{ minWidth: 220 }}
        >
          <MenuItem value="">All events</MenuItem>
          {EVENT_TYPES.map((type) => (
            <MenuItem key={type} value={type}>
              {type}
            </MenuItem>
          ))}
        </TextField>
      </Stack>

      {error && <Alert severity="error">Could not reach the engine.</Alert>}
      {isLoading && <CircularProgress />}

      {entries && entries.length === 0 && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body1" gutterBottom>
            Nothing recorded yet
          </Typography>
          <Typography variant="body2" color="text.secondary">
            The log fills up once a runner starts ticking. Every bar leaves a row,
            so a quiet session still looks different from a stopped one.
          </Typography>
        </Paper>
      )}

      {entries && entries.length > 0 && (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 170 }}>Time</TableCell>
                <TableCell sx={{ width: 150 }}>Event</TableCell>
                <TableCell sx={{ width: 70 }}>Bot</TableCell>
                <TableCell sx={{ width: 80 }}>Symbol</TableCell>
                <TableCell>Detail</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {entries.map((entry) => (
                <TableRow key={entry.id} hover>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    {new Date(entry.occurred_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={entry.event_type}
                      color={EVENT_COLOURS[entry.event_type] ?? 'default'}
                      variant={
                        EVENT_COLOURS[entry.event_type] === 'default'
                          ? 'outlined'
                          : 'filled'
                      }
                    />
                  </TableCell>
                  <TableCell>{entry.bot_id ?? '—'}</TableCell>
                  <TableCell>{entry.symbol ?? '—'}</TableCell>
                  <TableCell>
                    <Box
                      component="span"
                      sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}
                    >
                      {summarise(entry)}
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Container>
  );
}
