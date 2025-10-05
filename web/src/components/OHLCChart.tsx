import React, { useEffect, useRef } from 'react';
import { Card, CardContent, Typography } from '@mui/material';
import { createChart, ColorType, IChartApi, ISeriesApi } from 'lightweight-charts';
import type { Bar } from '../types';

interface OHLCChartProps {
  symbol: string;
  bars: Bar[];
  height?: number;
}

const OHLCChart: React.FC<OHLCChartProps> = ({ symbol, bars, height = 400 }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current || bars.length === 0) return;

    // Create chart
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#1e1e1e' },
        textColor: '#d1d4dc',
      },
      width: chartContainerRef.current.clientWidth,
      height,
      grid: {
        vertLines: { color: '#2b2b43' },
        horzLines: { color: '#2b2b43' },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartRef.current = chart;

    // Add candlestick series
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });

    seriesRef.current = candlestickSeries;

    // Transform and set data
    const chartData = bars.map(bar => ({
      time: Math.floor(new Date(bar.t).getTime() / 1000) as any,
      open: bar.o,
      high: bar.h,
      low: bar.l,
      close: bar.c,
    }));

    candlestickSeries.setData(chartData);

    // Fit content
    chart.timeScale().fitContent();

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        chartRef.current.remove();
      }
    };
  }, [bars, height]);

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          {symbol} - OHLC Chart
        </Typography>
        <div ref={chartContainerRef} />
      </CardContent>
    </Card>
  );
};

export default OHLCChart;
