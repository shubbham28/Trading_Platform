import React, { useState } from 'react';
import {
  Card,
  CardContent,
  Typography,
  TextField,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Box,
  Chip,
  InputAdornment,
  CircularProgress,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import { useQuery } from '@tanstack/react-query';
import { getAssets } from '../utils/api';
import type { Asset } from '../types';

interface TickerListProps {
  onSelectSymbol: (symbol: string) => void;
  selectedSymbol?: string;
}

const TickerList: React.FC<TickerListProps> = ({ onSelectSymbol, selectedSymbol }) => {
  const [search, setSearch] = useState('');
  const [assetClass, setAssetClass] = useState<'us_equity' | 'crypto'>('us_equity');

  const { data: assets, isLoading } = useQuery({
    queryKey: ['assets', assetClass],
    queryFn: () => getAssets('active', assetClass),
  });

  const filteredAssets = assets?.filter((asset: Asset) => {
    if (!search) return true;
    const searchLower = search.toLowerCase();
    return (
      asset.symbol.toLowerCase().includes(searchLower) ||
      asset.name.toLowerCase().includes(searchLower)
    );
  }).slice(0, 50); // Limit to 50 results

  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <Typography variant="h6" gutterBottom>
          Available Assets
        </Typography>
        
        <Box display="flex" gap={1} mb={2}>
          <Chip
            label="Stocks"
            color={assetClass === 'us_equity' ? 'primary' : 'default'}
            onClick={() => setAssetClass('us_equity')}
            clickable
          />
          <Chip
            label="Crypto"
            color={assetClass === 'crypto' ? 'primary' : 'default'}
            onClick={() => setAssetClass('crypto')}
            clickable
          />
        </Box>

        <TextField
          fullWidth
          size="small"
          placeholder="Search symbol or name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon />
              </InputAdornment>
            ),
          }}
          sx={{ mb: 2 }}
        />

        {isLoading ? (
          <Box display="flex" justifyContent="center" alignItems="center" flex={1}>
            <CircularProgress />
          </Box>
        ) : (
          <List sx={{ flex: 1, overflow: 'auto', py: 0 }}>
            {filteredAssets?.map((asset: Asset) => (
              <ListItem key={asset.id} disablePadding>
                <ListItemButton
                  selected={asset.symbol === selectedSymbol}
                  onClick={() => onSelectSymbol(asset.symbol)}
                >
                  <ListItemText
                    primary={asset.symbol}
                    secondary={asset.name}
                    primaryTypographyProps={{ fontWeight: 'medium' }}
                  />
                </ListItemButton>
              </ListItem>
            ))}
          </List>
        )}
      </CardContent>
    </Card>
  );
};

export default TickerList;
