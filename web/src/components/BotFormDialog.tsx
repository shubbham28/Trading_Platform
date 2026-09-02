import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  Grid,
  MenuItem,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { cloneBot, createBot, getStrategies, updateBot } from '../utils/api';
import type { Bot } from '../types';

const TIMEFRAMES = ['1Min', '5Min', '15Min', '1Hour', '1Day'];

/**
 * The risk limits a bot carries, with what each one actually prevents.
 *
 * Spelled out in the form rather than left to documentation. These numbers are
 * what stands between a strategy bug and the account, and a field labelled only
 * "max_position_pct" gets filled in by guesswork.
 */
const RISK_FIELDS: Array<{ key: string; label: string; help: string }> = [
  {
    key: 'max_position_pct',
    label: 'Max position (% of budget)',
    help: 'Largest single position. Measured on the resulting position, so adding to a holding counts.',
  },
  {
    key: 'max_order_value',
    label: 'Max order value ($)',
    help: 'Absolute backstop against a sizing bug. The percentage limits scale with the budget; this does not.',
  },
  {
    key: 'max_daily_loss',
    label: 'Max daily loss ($)',
    help: 'Once down this much today the bot stops opening. It can still close.',
  },
  {
    key: 'max_open_positions',
    label: 'Max open positions',
    help: 'How many symbols this bot may hold at once.',
  },
];

/**
 * Booleans, separated because they are switches rather than numbers.
 *
 * `allow_short` defaults off and matches the backtester's own default. That
 * matching is the point: without it the backtester refused a sell-with-no-
 * position while the live runner opened a short from the same signal.
 */
const RISK_FLAGS: Array<{ key: string; label: string; help: string; fallback: boolean }> = [
  {
    key: 'flat_by_close',
    label: 'Flatten before the close',
    help: 'Exit any open position on the session\u2019s last bar. Turn off for a swing bot that holds overnight on purpose.',
    fallback: true,
  },
  {
    key: 'allow_short',
    label: 'Allow shorts',
    help: 'Let a sell with no position open a short. Off by default, matching the backtester, so live and backtest agree.',
    fallback: false,
  },
];

type Mode = 'create' | 'edit' | 'clone';

interface Props {
  open: boolean;
  mode: Mode;
  bot?: Bot;
  onClose: () => void;
}

export default function BotFormDialog({ open, mode, bot, onClose }: Props) {
  const queryClient = useQueryClient();
  const { data: strategies } = useQuery({
    queryKey: ['strategies'],
    queryFn: getStrategies,
  });

  const [name, setName] = useState('');
  const [strategyId, setStrategyId] = useState('');
  const [symbols, setSymbols] = useState('');
  const [timeframe, setTimeframe] = useState('1Day');
  const [capitalBudget, setCapitalBudget] = useState('10000');
  const [parametersText, setParametersText] = useState('{}');
  const [riskLimits, setRiskLimits] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setFormError(null);

    if (mode === 'create') {
      setName('');
      setStrategyId(strategies?.[0]?.id ?? '');
      setSymbols('');
      setTimeframe('1Day');
      setCapitalBudget('10000');
      setParametersText('{}');
      setRiskLimits({});
      return;
    }

    if (!bot) return;
    // A clone starts from the parent's configuration with a blank name, which is
    // the whole point: change one number and run both.
    setName(mode === 'clone' ? `${bot.name}-copy` : bot.name);
    setStrategyId(bot.strategy_id);
    setSymbols(bot.symbols.join(', '));
    setTimeframe(bot.timeframe);
    setCapitalBudget(String(bot.capital_budget));
    setParametersText(JSON.stringify(bot.parameters ?? {}, null, 2));
    setRiskLimits(
      Object.fromEntries(
        Object.entries(bot.risk_limits ?? {}).map(([k, v]) => [k, String(v)])
      )
    );
  }, [open, mode, bot, strategies]);

  const selectedStrategy = strategies?.find((s) => s.id === strategyId);

  const mutation = useMutation({
    mutationFn: async () => {
      let parameters: Record<string, any>;
      try {
        parameters = JSON.parse(parametersText || '{}');
      } catch {
        throw new Error('Parameters must be valid JSON.');
      }

      // Flags stay booleans. Number('true') is NaN, which would land in the
      // stored record and make the limit unreadable.
      const flagKeys = new Set(RISK_FLAGS.map((f) => f.key));
      const limits: Record<string, number | boolean> = {};
      for (const [key, value] of Object.entries(riskLimits)) {
        if (value === '') continue;
        limits[key] = flagKeys.has(key) ? value === 'true' : Number(value);
      }

      const symbolList = symbols
        .split(',')
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean);

      if (mode === 'clone' && bot) {
        return cloneBot(bot.id, name, parameters);
      }
      if (mode === 'edit' && bot) {
        return updateBot(bot.id, {
          parameters,
          risk_limits: limits,
          capital_budget: Number(capitalBudget),
          symbols: symbolList,
          timeframe,
        });
      }
      return createBot({
        name,
        strategy_id: strategyId,
        symbols: symbolList,
        timeframe,
        capital_budget: Number(capitalBudget),
        parameters,
        risk_limits: limits,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bots'] });
      onClose();
    },
    onError: (error: any) => {
      // Surface the engine's own message. It names the offending parameter,
      // which a generic "something went wrong" would throw away.
      setFormError(
        error?.response?.data?.detail ?? error?.message ?? 'Something went wrong.'
      );
    },
  });

  const title =
    mode === 'create' ? 'New bot' : mode === 'clone' ? `Clone ${bot?.name}` : `Tune ${bot?.name}`;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {formError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {formError}
          </Alert>
        )}
        {mode === 'clone' && (
          <Alert severity="info" sx={{ mb: 2 }}>
            The clone starts <strong>disabled</strong>. Retune it before enabling,
            otherwise it trades the original&apos;s parameters against the same
            account.
          </Alert>
        )}

        <Grid container spacing={2}>
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={mode === 'edit'}
              helperText={mode === 'edit' ? 'Names cannot be changed' : 'Must be unique'}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              select
              fullWidth
              label="Strategy"
              value={strategyId}
              onChange={(e) => {
                setStrategyId(e.target.value);
                setParametersText('{}');
              }}
              disabled={mode !== 'create'}
              helperText={
                mode !== 'create'
                  ? 'Clone into a new bot to change strategy'
                  : selectedStrategy?.description
              }
            >
              {(strategies ?? []).map((s) => (
                <MenuItem key={s.id} value={s.id}>
                  {s.name}
                </MenuItem>
              ))}
            </TextField>
          </Grid>

          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Symbols"
              placeholder="AAPL, MSFT"
              value={symbols}
              onChange={(e) => setSymbols(e.target.value)}
              disabled={mode === 'clone'}
              helperText="Comma separated. One runner process per symbol."
            />
          </Grid>
          <Grid item xs={12} sm={3}>
            <TextField
              select
              fullWidth
              label="Timeframe"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              disabled={mode === 'clone'}
            >
              {TIMEFRAMES.map((tf) => (
                <MenuItem key={tf} value={tf}>
                  {tf}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} sm={3}>
            <TextField
              fullWidth
              type="number"
              label="Capital budget ($)"
              value={capitalBudget}
              onChange={(e) => setCapitalBudget(e.target.value)}
              helperText="This bot's allocation"
            />
          </Grid>

          <Grid item xs={12}>
            <TextField
              fullWidth
              multiline
              minRows={4}
              label="Strategy parameters (JSON)"
              value={parametersText}
              onChange={(e) => setParametersText(e.target.value)}
              helperText={
                selectedStrategy
                  ? `Defaults: ${JSON.stringify(selectedStrategy.parameters ?? {})}`
                  : 'Validated against the strategy before anything is stored'
              }
              sx={{ fontFamily: 'monospace' }}
            />
          </Grid>

          {mode !== 'clone' && (
            <>
              <Grid item xs={12}>
                <Divider sx={{ my: 1 }} />
                <Typography variant="subtitle2" gutterBottom>
                  Risk limits
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Left blank, each falls back to a permissive default. Every one of
                  these restricts only orders that <strong>increase</strong>{' '}
                  exposure &mdash; none of them can block a close.
                </Typography>
              </Grid>
              {RISK_FIELDS.map((field) => (
                <Grid item xs={12} sm={6} key={field.key}>
                  <TextField
                    fullWidth
                    type="number"
                    label={field.label}
                    value={riskLimits[field.key] ?? ''}
                    onChange={(e) =>
                      setRiskLimits({ ...riskLimits, [field.key]: e.target.value })
                    }
                    helperText={field.help}
                  />
                </Grid>
              ))}
              {RISK_FLAGS.map((flag) => (
                <Grid item xs={12} sm={6} key={flag.key}>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={
                          riskLimits[flag.key] === undefined
                            ? flag.fallback
                            : riskLimits[flag.key] === 'true'
                        }
                        onChange={(e) =>
                          setRiskLimits({
                            ...riskLimits,
                            [flag.key]: e.target.checked ? 'true' : 'false',
                          })
                        }
                      />
                    }
                    label={flag.label}
                  />
                  <Typography variant="caption" color="text.secondary" display="block">
                    {flag.help}
                  </Typography>
                </Grid>
              ))}
            </>
          )}
        </Grid>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          disabled={mutation.isPending || !name.trim()}
          onClick={() => {
            setFormError(null);
            mutation.mutate();
          }}
        >
          {mode === 'create' ? 'Create' : mode === 'clone' ? 'Clone' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
