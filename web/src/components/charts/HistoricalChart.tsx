'use client';

import { useEffect, useRef } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts';

export interface OHLCData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface HistoricalChartProps {
  data: OHLCData[];
  type: 'candlestick' | 'line';
}

export function HistoricalChart({ data, type }: HistoricalChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);

  // --- EFFECT 1: Handle Chart Base Lifecycle (Mount/Unmount) ---
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#A1A1AA', // Zinc 400
      },
      grid: {
        vertLines: { color: '#27272A' }, // Zinc 800
        horzLines: { color: '#27272A' },
      },
      crosshair: { mode: 0 },
      width: chartContainerRef.current.clientWidth,
      height: 500,
    });

    chartRef.current = chart;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    // CLEANUP: Completely nullify references to kill React Strict Mode leaks
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null; // CRITICAL: Erases dead series signatures
    };
  }, []);

  // --- EFFECT 2: Handle Dynamic Data & Layout Toggles Safely ---
  useEffect(() => {
    // Guard clause: Do nothing if the chart hasn't mounted or data hasn't arrived
    if (!chartRef.current || !data || data.length === 0) return;

    // Defensively check and strip out the previous series configuration
    if (seriesRef.current) {
      try {
        chartRef.current.removeSeries(seriesRef.current);
      } catch (error) {
        // Catch and suppress transient internal lifecycle mismatch warnings
        console.debug("Stale series reference cleanup bypassed:", error);
      }
      seriesRef.current = null;
    }

    // Initialize the fresh target series configuration
    if (type === 'candlestick') {
      seriesRef.current = chartRef.current.addSeries(CandlestickSeries, {
        upColor: '#10B981', // Emerald 500
        downColor: '#EF4444', // Red 500
        borderVisible: false,
        wickUpColor: '#10B981',
        wickDownColor: '#EF4444',
      });
      seriesRef.current.setData(data);
    } 
    else if (type === 'line') {
      seriesRef.current = chartRef.current.addSeries(LineSeries, {
        color: '#10B981',
        lineWidth: 2,
        crosshairMarkerVisible: true,
      });
      
      // Transform full OHLC data into flat time/value coordinate objects for Line charts
      const lineData = data.map(d => ({ time: d.time, value: d.close }));
      seriesRef.current.setData(lineData);
    }
  }, [data, type]); // Runs smoothly whenever data arrays shift or type is updated

  return <div ref={chartContainerRef} className="w-full h-full" />;
}