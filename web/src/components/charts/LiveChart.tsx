'use client';

import { useEffect, useRef } from 'react';
import { createChart, AreaSeries, ColorType } from 'lightweight-charts';
import { useTradingStore } from '@/store/useTradingStore';

export function LiveChart() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  // Using 'any' here to gracefully bypass TS strict typing differences between v4 and v5
  const seriesRef = useRef<any>(null); 
  
  // Subscribe specifically to netWorth to update the chart
  const netWorth = useTradingStore((state) => state.netWorth);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Initialize the Chart with a Dark Mode aesthetic
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#A1A1AA', // Zinc 400
      },
      grid: {
        vertLines: { color: '#27272A' }, // Zinc 800
        horzLines: { color: '#27272A' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
    });

    // 2. The v5 API signature: addSeries(SeriesType, options)
    const newSeries = chart.addSeries(AreaSeries, {
      lineColor: '#10B981', // Emerald 500
      topColor: 'rgba(16, 185, 129, 0.4)',
      bottomColor: 'rgba(16, 185, 129, 0.0)',
      lineWidth: 2,
    });
    
    seriesRef.current = newSeries;

    // Handle Window Resizing
    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current?.clientWidth ?? 0 });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  // Update the chart whenever new data arrives
  useEffect(() => {
    if (seriesRef.current) {
      // Create a clean timestamp (Seconds, not milliseconds, for Lightweight Charts)
      const time = Math.floor(Date.now() / 1000) as any;
      seriesRef.current.update({ time, value: netWorth });
    }
  }, [netWorth]);

  return <div ref={chartContainerRef} className="w-full h-full" />;
}