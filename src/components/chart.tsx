"use client";

import { useEffect, useRef } from "react";
import { createChart, type IChartApi, AreaSeries, ColorType } from "lightweight-charts";
import { useTheme } from "next-themes";

interface DataPoint {
  time: string; // 'YYYY-MM-DD'
  value: number;
}

interface ChartProps {
  data: DataPoint[];
  height?: number;
  color?: string;
}

export function Chart({ data, height = 300, color = "#818cf8" }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ReturnType<IChartApi["addSeries"]> | null>(null);
  const { resolvedTheme } = useTheme();

  const isDark = resolvedTheme === "dark";

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    const bgColor = isDark ? "#161822" : "#ffffff";
    const textColor = isDark ? "#64748b" : "#94a3b8";
    const gridColor = isDark ? "rgba(30, 32, 48, 0.8)" : "rgba(226, 232, 240, 0.8)";

    if (chartRef.current) {
      chartRef.current.remove();
    }

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: bgColor },
        textColor,
        fontFamily: "Inter, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      rightPriceScale: {
        borderColor: gridColor,
      },
      timeScale: {
        borderColor: gridColor,
        timeVisible: false,
      },
      crosshair: {
        horzLine: { color: textColor, labelBackgroundColor: color },
        vertLine: { color: textColor, labelBackgroundColor: color },
      },
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor: color,
      topColor: `${color}40`,
      bottomColor: `${color}05`,
      lineWidth: 2,
    });

    series.setData(data);
    chart.timeScale().fitContent();

    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };

    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [data, height, color, isDark]);

  return <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />;
}
