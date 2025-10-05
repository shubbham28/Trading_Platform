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
import TradingPage from './pages/TradingPage';
import AccountPage from './pages/AccountPage';

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
                  to="/account"
                  startIcon={<AccountBalanceIcon />}
                >
                  Account
                </Button>
              </Toolbar>
            </AppBar>

            <Box component="main" sx={{ flexGrow: 1, bgcolor: 'background.default' }}>
              <Routes>
                <Route path="/" element={<Navigate to="/trading" replace />} />
                <Route path="/trading" element={<TradingPage />} />
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
                  Trading Platform MVP - Paper Trading Mode
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
