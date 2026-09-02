import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  TextField,
  Tooltip,
} from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { getKillSwitch, setKillSwitch } from '../utils/api';

/**
 * The kill switch, in the app bar so it is reachable from every screen.
 *
 * Deliberately the loudest control in the UI when engaged: an engaged switch
 * means no bot can open a position, and someone who does not realise that will
 * spend a long time wondering why nothing is trading.
 *
 * Engaging asks for a reason and releasing asks for confirmation. Both are
 * one-way doors in the moment -- engaging stops the book, releasing lets bots
 * start taking positions again -- and neither should happen on a stray click.
 *
 * Polled rather than assumed: the switch can be engaged by another operator or
 * by a script, and a stale "all clear" is the worst thing this button could show.
 */
export default function KillSwitchButton() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [reason, setReason] = useState('');

  const { data: killSwitch } = useQuery({
    queryKey: ['kill-switch'],
    queryFn: getKillSwitch,
    refetchInterval: 5000,
  });

  const mutation = useMutation({
    mutationFn: ({ engaged, why }: { engaged: boolean; why?: string }) =>
      setKillSwitch(engaged, why),
    onSuccess: () => {
      // Bot rows show what the gate is blocking, so they are stale the moment
      // the switch moves.
      queryClient.invalidateQueries({ queryKey: ['kill-switch'] });
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      setDialogOpen(false);
      setReason('');
    },
  });

  const engaged = killSwitch?.engaged ?? false;

  return (
    <>
      {engaged && (
        <Tooltip title={killSwitch?.reason || 'no reason recorded'}>
          <Chip
            icon={<WarningAmberIcon />}
            label="TRADING HALTED"
            color="error"
            sx={{ mr: 2, fontWeight: 700 }}
          />
        </Tooltip>
      )}
      <Button
        variant={engaged ? 'outlined' : 'contained'}
        color={engaged ? 'success' : 'error'}
        startIcon={engaged ? <PlayArrowIcon /> : <WarningAmberIcon />}
        onClick={() => setDialogOpen(true)}
        sx={{ mr: 2 }}
      >
        {engaged ? 'Resume' : 'Kill switch'}
      </Button>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)}>
        <DialogTitle>
          {engaged ? 'Resume trading?' : 'Halt all trading?'}
        </DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            {engaged ? (
              <>
                Bots will be able to open positions again as soon as this is
                released. Nothing else changes &mdash; a bot that was disabled
                stays disabled.
              </>
            ) : (
              <>
                Every bot stops opening positions immediately, with no restart
                needed. Orders that <strong>reduce or close</strong> a position
                still go through, so bots can flatten rather than being frozen
                holding whatever they have.
              </>
            )}
          </DialogContentText>
          {!engaged && (
            <TextField
              autoFocus
              fullWidth
              label="Reason"
              placeholder="e.g. data feed looks wrong"
              helperText="Recorded in the audit log. The first question after an incident is why."
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            color={engaged ? 'success' : 'error'}
            disabled={mutation.isPending || (!engaged && reason.trim() === '')}
            onClick={() =>
              mutation.mutate({ engaged: !engaged, why: reason.trim() || undefined })
            }
          >
            {engaged ? 'Resume trading' : 'Halt trading'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
