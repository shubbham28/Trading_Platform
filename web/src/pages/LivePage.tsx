import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Grid,
  LinearProgress,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import LockIcon from '@mui/icons-material/Lock';
import LockOpenIcon from '@mui/icons-material/LockOpen';
import {
  approveOrder,
  getApprovals,
  getLiveSettings,
  rejectOrder,
  updateLiveSettings,
} from '../utils/api';
import type { PendingApproval } from '../types';

function money(value: number): string {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  });
}

/**
 * How long a request has left, as a bar rather than a number.
 *
 * A request that expires while someone is reading the page is the failure this
 * screen exists to prevent, so the time remaining is the most visually
 * prominent thing in the row.
 */
function ExpiryBar({ approval, timeout }: { approval: PendingApproval; timeout: number }) {
  const remaining = approval.expires_in_seconds ?? 0;
  const fraction = Math.max(0, Math.min(1, remaining / timeout));
  const urgent = remaining < timeout * 0.3;

  return (
    <Box sx={{ minWidth: 120 }}>
      <Typography variant="caption" color={urgent ? 'error.main' : 'text.secondary'}>
        {remaining <= 0 ? 'expiring' : `${Math.round(remaining)}s left`}
      </Typography>
      <LinearProgress
        variant="determinate"
        value={fraction * 100}
        color={urgent ? 'error' : 'primary'}
        sx={{ mt: 0.5 }}
      />
    </Box>
  );
}

export default function LivePage() {
  const queryClient = useQueryClient();
  const [ceiling, setCeiling] = useState<string>('');
  const [timeout_, setTimeout_] = useState<string>('');
  const [autoApproveDialog, setAutoApproveDialog] = useState(false);
  const [autoApproveNote, setAutoApproveNote] = useState('');
  const [error, setError] = useState<string | null>(null);

  const { data: settings, isLoading } = useQuery({
    queryKey: ['live-settings'],
    queryFn: getLiveSettings,
  });

  const { data: queue } = useQuery({
    queryKey: ['approvals'],
    queryFn: getApprovals,
    // Polled hard: every second of staleness is a second closer to a request
    // expiring under the reader's cursor.
    refetchInterval: 2000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['live-settings'] });
    queryClient.invalidateQueries({ queryKey: ['approvals'] });
    queryClient.invalidateQueries({ queryKey: ['bots'] });
  };

  const saveSettings = useMutation({
    mutationFn: (changes: Parameters<typeof updateLiveSettings>[0]) =>
      updateLiveSettings(changes),
    onSuccess: () => {
      invalidate();
      setAutoApproveDialog(false);
      setAutoApproveNote('');
      setError(null);
    },
    onError: (err: any) =>
      setError(err?.response?.data?.detail ?? 'Could not save.'),
  });

  const decide = useMutation({
    mutationFn: ({ orderId, approved }: { orderId: number; approved: boolean }) =>
      approved ? approveOrder(orderId) : rejectOrder(orderId),
    onSuccess: invalidate,
    onError: (err: any) =>
      setError(err?.response?.data?.detail ?? 'Could not act on that order.'),
  });

  if (isLoading || !settings) {
    return <Container sx={{ py: 4 }}><CircularProgress /></Container>;
  }

  const permitted = settings.live_trading_permitted;

  return (
    <Container maxWidth="lg" sx={{ py: 3 }}>
      <Typography variant="h5" gutterBottom>
        Live trading
      </Typography>

      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* The posture, stated before anything else on the page. Someone arriving
          here needs to know whether real money can move before they read a
          single control. */}
      {!permitted ? (
        <Alert severity="info" icon={<LockIcon />} sx={{ mb: 3 }}>
          <AlertTitle>Live trading is off</AlertTitle>
          No live order can be placed, because the order ceiling is zero. That is
          the default, and it is deliberate &mdash; live trading should not begin
          by inheriting a paper configuration. Set a ceiling below to turn it on.
        </Alert>
      ) : (
        <Alert
          severity={settings.auto_approve ? 'error' : 'warning'}
          icon={<LockOpenIcon />}
          sx={{ mb: 3 }}
        >
          <AlertTitle>
            {settings.auto_approve
              ? 'Live trading is on, with no human check'
              : 'Live trading is on, approval required'}
          </AlertTitle>
          {settings.auto_approve ? (
            <>
              Bots place live orders up to {money(settings.max_order_value)} with
              no one approving them. Enabled{' '}
              {settings.auto_approve_enabled_at
                ? new Date(settings.auto_approve_enabled_at).toLocaleString()
                : ''}
              : &ldquo;{settings.auto_approve_note}&rdquo;
            </>
          ) : (
            <>
              Every live order waits for you, and expires after{' '}
              {settings.approval_timeout_seconds}s if you do not act &mdash;
              because approving a stale signal means trading on information the
              strategy would no longer act on.
            </>
          )}
        </Alert>
      )}

      {/* -- the queue, above the settings: it is time-sensitive and they are not -- */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Pending approvals
          </Typography>
          {queue && queue.count > 0 && (
            <Chip label={queue.count} color="warning" />
          )}
        </Stack>

        {!queue || queue.count === 0 ? (
          <Typography variant="body2" color="text.secondary">
            Nothing waiting.{' '}
            {settings.auto_approve
              ? 'Auto-approve is on, so live orders go straight out and never queue here.'
              : 'A live order will appear here the moment a bot wants to place one.'}
          </Typography>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Expires</TableCell>
                  <TableCell>Bot</TableCell>
                  <TableCell>Order</TableCell>
                  <TableCell>Why</TableCell>
                  <TableCell align="right">Decide</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {queue.approvals.map((approval) => (
                  <TableRow key={approval.order_id} hover>
                    <TableCell>
                      <ExpiryBar
                        approval={approval}
                        timeout={queue.approval_timeout_seconds}
                      />
                    </TableCell>
                    <TableCell>{approval.bot_id ?? 'manual'}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={`${approval.side.toUpperCase()} ${approval.qty} ${approval.symbol}`}
                        color={approval.side === 'buy' ? 'primary' : 'secondary'}
                      />
                    </TableCell>
                    <TableCell>
                      <Tooltip title={approval.bar_timestamp ?? ''}>
                        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                          {approval.reason}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell align="right">
                      <Button
                        size="small"
                        variant="contained"
                        color="success"
                        startIcon={<CheckIcon />}
                        disabled={decide.isPending}
                        onClick={() =>
                          decide.mutate({ orderId: approval.order_id, approved: true })
                        }
                        sx={{ mr: 1 }}
                      >
                        Approve
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        color="error"
                        startIcon={<CloseIcon />}
                        disabled={decide.isPending}
                        onClick={() =>
                          decide.mutate({ orderId: approval.order_id, approved: false })
                        }
                      >
                        Reject
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Paper>

      {/* -- settings -- */}
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>
          Settings
        </Typography>

        <Grid container spacing={3} alignItems="flex-start">
          <Grid item xs={12} sm={6}>
            <Stack direction="row" spacing={1}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="Live order ceiling ($)"
                placeholder={String(settings.max_order_value)}
                value={ceiling}
                onChange={(e) => setCeiling(e.target.value)}
                helperText={`Currently ${money(settings.max_order_value)}. A hard cap on one live order, independent of any bot's own limits — those were tuned against paper. Zero turns live trading off.`}
              />
              <Button
                variant="outlined"
                disabled={ceiling === '' || saveSettings.isPending}
                onClick={() =>
                  saveSettings.mutate({ max_order_value: Number(ceiling) })
                }
                sx={{ height: 40 }}
              >
                Set
              </Button>
            </Stack>
          </Grid>

          <Grid item xs={12} sm={6}>
            <Stack direction="row" spacing={1}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="Approval timeout (seconds)"
                placeholder={String(settings.approval_timeout_seconds)}
                value={timeout_}
                onChange={(e) => setTimeout_(e.target.value)}
                helperText={`Currently ${settings.approval_timeout_seconds}s. Past this a request expires unapproved, because its signal is stale.`}
              />
              <Button
                variant="outlined"
                disabled={timeout_ === '' || saveSettings.isPending}
                onClick={() =>
                  saveSettings.mutate({ approval_timeout_seconds: Number(timeout_) })
                }
                sx={{ height: 40 }}
              >
                Set
              </Button>
            </Stack>
          </Grid>

          <Grid item xs={12}>
            <Divider sx={{ mb: 2 }} />
            <Stack direction="row" alignItems="center" spacing={2}>
              <Switch
                checked={settings.auto_approve}
                onChange={(e) => {
                  if (e.target.checked) {
                    // Turning it on needs a reason. Turning it off does not:
                    // restoring a safety check must never be harder than
                    // removing one.
                    setAutoApproveDialog(true);
                  } else {
                    saveSettings.mutate({ auto_approve: false });
                  }
                }}
                color="error"
              />
              <Box>
                <Typography variant="body2">
                  Place live orders without approval
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Removes the only human check on live orders. The ceiling above
                  still applies &mdash; a cap a setting can bypass is not a cap.
                </Typography>
              </Box>
            </Stack>
          </Grid>
        </Grid>
      </Paper>

      <Dialog open={autoApproveDialog} onClose={() => setAutoApproveDialog(false)}>
        <DialogTitle>Let bots place live orders unapproved?</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            This removes the only human check on live orders. Bots will place them
            up to {money(settings.max_order_value)} each, with no one looking
            first. The kill switch and every risk rule still apply.
          </DialogContentText>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={2}
            label="Why"
            placeholder="e.g. ran clean on paper for a month, sizing is small"
            helperText="Required, and recorded. A change this consequential with no reason attached leaves nothing to review later."
            value={autoApproveNote}
            onChange={(e) => setAutoApproveNote(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAutoApproveDialog(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            disabled={autoApproveNote.trim().length < 10 || saveSettings.isPending}
            onClick={() =>
              saveSettings.mutate({
                auto_approve: true,
                note: autoApproveNote.trim(),
              })
            }
          >
            Turn off approval
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
