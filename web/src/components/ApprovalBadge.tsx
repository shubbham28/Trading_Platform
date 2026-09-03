import { useQuery } from '@tanstack/react-query';
import { Badge, Button, Tooltip } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import GavelIcon from '@mui/icons-material/Gavel';
import { getApprovals } from '../utils/api';

/**
 * A count of live orders waiting for a decision, in the app bar.
 *
 * In the app bar rather than only on the Live page because an approval request
 * expires. A queue you have to navigate to in order to discover is a queue that
 * quietly times out while you are looking at something else, and the bot's
 * order silently never happens.
 */
export default function ApprovalBadge() {
  const { data: queue } = useQuery({
    queryKey: ['approvals'],
    queryFn: getApprovals,
    refetchInterval: 2000,
  });

  const waiting = queue?.count ?? 0;

  return (
    <Tooltip
      title={
        waiting > 0
          ? `${waiting} live order(s) waiting for you. They expire after ${queue?.approval_timeout_seconds}s.`
          : 'Live trading settings and approval queue'
      }
    >
      <Button
        color="inherit"
        component={RouterLink}
        to="/live"
        startIcon={
          <Badge badgeContent={waiting} color="error">
            <GavelIcon />
          </Badge>
        }
      >
        Live
      </Button>
    </Tooltip>
  );
}
