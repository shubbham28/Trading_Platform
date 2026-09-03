import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  ThemeProvider,
  createTheme,
  CssBaseline,
  AppBar,
  Toolbar,
  Typography,
  Box,
  Button,
  Container,
} from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import ShowChartIcon from '@mui/icons-material/ShowChart';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import HistoryIcon from '@mui/icons-material/History';
import ScienceIcon from '@mui/icons-material/Science';
import TradingPage from './pages/TradingPage';
import AccountPage from './pages/AccountPage';
import BotsPage from './pages/BotsPage';
import AuditPage from './pages/AuditPage';
import BacktestsPage from './pages/BacktestsPage';
import LivePage from './pages/LivePage';
import KillSwitchButton from './components/KillSwitchButton';
import ApprovalBadge from './components/ApprovalBadge';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#90caf9',
    },
    secondary: {
      main: '#f48fb1',
    },
    background: {
      default: '#121212',
      paper: '#1e1e1e',
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={darkTheme}>
        <CssBaseline />
        <BrowserRouter>
          <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
            <AppBar position="static">
              <Toolbar>
                <ShowChartIcon sx={{ mr: 2 }} />
                <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
                  Trading Platform
                </Typography>
                {/* The kill switch sits before the navigation on purpose: it is
                    the one control that must be reachable from every screen
                    without hunting for it. */}
                <KillSwitchButton />
                <Button
                  color="inherit"
                  component={RouterLink}
                  to="/bots"
                  startIcon={<SmartToyIcon />}
                >
                  Bots
                </Button>
                <Button
                  color="inherit"
                  component={RouterLink}
                  to="/trading"
                  startIcon={<ShowChartIcon />}
                >
                  Trading
                </Button>
                <Button
                  color="inherit"
                  component={RouterLink}
                  to="/backtests"
                  startIcon={<ScienceIcon />}
                >
                  Backtests
                </Button>
                {/* Beside the kill switch, and carrying a count: an approval
                    request expires, so a queue you have to go looking for is a
                    queue that times out while you are elsewhere. */}
                <ApprovalBadge />
                <Button
                  color="inherit"
                  component={RouterLink}
                  to="/audit"
                  startIcon={<HistoryIcon />}
                >
                  Audit
                </Button>
                <Button
                  color="inherit"
                  component={RouterLink}
                  to="/account"
                  startIcon={<AccountBalanceIcon />}
                >
                  Account
                </Button>
              </Toolbar>
            </AppBar>

            <Box component="main" sx={{ flexGrow: 1, bgcolor: 'background.default' }}>
              <Routes>
                {/* Bots is the landing page: it is what the platform is for. */}
                <Route path="/" element={<Navigate to="/bots" replace />} />
                <Route path="/bots" element={<BotsPage />} />
                <Route path="/trading" element={<TradingPage />} />
                <Route path="/backtests" element={<BacktestsPage />} />
                <Route path="/live" element={<LivePage />} />
                <Route path="/audit" element={<AuditPage />} />
                <Route path="/account" element={<AccountPage />} />
              </Routes>
            </Box>

            <Box
              component="footer"
              sx={{
                py: 2,
                px: 2,
                mt: 'auto',
                backgroundColor: 'background.paper',
              }}
            >
              <Container maxWidth="xl">
                <Typography variant="body2" color="text.secondary" align="center">
                  Paper trading. Live orders are refused by the router until the
                  approval queue exists.
                </Typography>
              </Container>
            </Box>
          </Box>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
