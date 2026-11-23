// Charts follow the data-viz method: categorical slots in fixed order (series 1-3), thin marks
// (2px lines, <=24px bars with 4px rounded data-ends), 2px surface gaps, recessive hairline grid,
// a crosshair tooltip that leads with values, a legend for >=2 series, and a table view for every chart.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Table2, BarChart3 } from "lucide-react";
import { Button, Card, CardHeader } from "@/components/ui";
import { compact, dayLabel } from "@/lib/format";

// ---------------------------------------------------------------- live theme colors
const VARS = ["--series-1", "--series-2", "--series-3", "--series-4", "--grid", "--axis", "--text-3", "--surface", "--text-2"] as const;
type Palette = Record<(typeof VARS)[number], string>;

function readPalette(): Palette {
  const s = getComputedStyle(document.documentElement);
  return Object.fromEntries(VARS.map((v) => [v, s.getPropertyValue(v).trim() || "#888"])) as Palette;
}

export function usePalette(): Palette {
  const [p, setP] = useState<Palette>(readPalette);
  useEffect(() => {
    const update = () => setP(readPalette());
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    return () => {
      mo.disconnect();
      mq.removeEventListener("change", update);
    };
  }, []);
  return p;
}

export interface Series {
  key: string;
  label: string;
  slot: 1 | 2 | 3 | 4;
}

// ---------------------------------------------------------------- card wrapper with table view
export function ChartCard({ title, sub, legend, table, children, action }: { title: string; sub?: ReactNode; legend?: ReactNode; table: ReactNode; children: ReactNode; action?: ReactNode }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <Card className="chart-card">
      <CardHeader
        title={title}
        sub={sub}
        action={
          <div className="row">
            {action}
            <Button
              size="sm"
              variant="ghost"
              icon={asTable ? <BarChart3 /> : <Table2 />}
              onClick={() => setAsTable((v) => !v)}
              aria-label={asTable ? "Show chart" : "Show as table"}
              title={asTable ? "Show chart" : "Show as table"}
            />
          </div>
        }
      />
      <div className="card-body">
        {asTable ? (
          <div className="table-wrap" style={{ maxHeight: 300, overflowY: "auto" }}>
            {table}
          </div>
        ) : (
          <>
            {legend && <div style={{ marginBottom: 12 }}>{legend}</div>}
            {children}
          </>
        )}
      </div>
    </Card>
  );
}

export function Legend({ items, kind = "line" }: { items: { label: string; color: string }[]; kind?: "line" | "rect" }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span className="legend-item" key={i.label}>
          <span className={kind === "line" ? "legend-line" : "legend-swatch"} style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- tooltip (values lead)
interface TipProps {
  active?: boolean;
  label?: string;
  payload?: { dataKey: string; value: number; color?: string; stroke?: string; fill?: string }[];
  series: Series[];
  colors: string[];
  fmt: (v: number) => string;
}
function Tip({ active, label, payload, series, colors, fmt }: TipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="viz-tooltip">
      <div className="t-title">{label ? dayLabel(label) : ""}</div>
      {series.map((s, i) => {
        const p = payload.find((x) => x.dataKey === s.key);
        return (
          <div className="t-row" key={s.key}>
            <b>{p && p.value !== null && p.value !== undefined ? fmt(p.value) : "—"}</b>
            <span className="t-key">
              <i style={{ background: colors[i] }} />
              {s.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function axisProps(p: Palette) {
  return {
    tick: { fill: p["--text-3"], fontSize: 11 },
    tickLine: false,
    axisLine: { stroke: p["--axis"] },
  };
}

function DataTable<T extends Record<string, unknown>>({ rows, columns }: { rows: T[]; columns: { key: string; label: string; fmt?: (v: unknown) => string }[] }) {
  return (
    <table className="table">
      <thead>
        <tr>
          {columns.map((c, i) => (
            <th key={c.key} className={i ? "num" : ""}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, j) => (
          <tr key={j}>
            {columns.map((c, i) => (
              <td key={c.key} className={i ? "num" : ""}>
                {c.fmt ? c.fmt(r[c.key]) : String(r[c.key] ?? "—")}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------- time series (lines, area wash for one series)
export function TrendChart({ title, sub, data, series, fmt = compact, height = 240, action }: { title: string; sub?: ReactNode; data: Record<string, unknown>[]; series: Series[]; fmt?: (v: number) => string; height?: number; action?: ReactNode }) {
  const p = usePalette();
  const colors = series.map((s) => p[`--series-${s.slot}` as keyof Palette]);
  const single = series.length === 1;
  const ticks = useMemo(() => {
    const n = data.length;
    const step = Math.max(1, Math.ceil(n / 7));
    return data.filter((_, i) => i % step === 0 || i === n - 1).map((d) => d.date as string);
  }, [data]);
  return (
    <ChartCard
      title={title}
      sub={sub}
      action={action}
      legend={single ? undefined : <Legend items={series.map((s, i) => ({ label: s.label, color: colors[i] }))} />}
      table={
        <DataTable
          rows={data}
          columns={[{ key: "date", label: "Date", fmt: (v) => dayLabel(String(v)) }, ...series.map((s) => ({ key: s.key, label: s.label, fmt: (v: unknown) => (v === null || v === undefined ? "—" : fmt(Number(v))) }))]}
        />
      }
    >
      <div className="chart-box" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
            <CartesianGrid stroke={p["--grid"]} vertical={false} />
            <XAxis dataKey="date" ticks={ticks} tickFormatter={dayLabel} {...axisProps(p)} />
            <YAxis allowDecimals={false} tickFormatter={(v) => fmt(Number(v))} width={48} {...axisProps(p)} axisLine={false} />
            <Tooltip cursor={{ stroke: p["--axis"], strokeWidth: 1 }} content={<Tip series={series} colors={colors} fmt={fmt} />} />
            {series.map((s, i) =>
              single ? (
                <Area key={s.key} type="linear" dataKey={s.key} stroke={colors[i]} strokeWidth={2} fill={colors[i]} fillOpacity={0.1} dot={valueDot(colors[i], p["--surface"], s.key)} activeDot={{ r: 4, strokeWidth: 2, stroke: p["--surface"] }} connectNulls isAnimationActive={false} />
              ) : (
                <Line key={s.key} type="linear" dataKey={s.key} stroke={colors[i]} strokeWidth={2} dot={valueDot(colors[i], p["--surface"], s.key)} activeDot={{ r: 4, strokeWidth: 2, stroke: p["--surface"] }} strokeLinecap="round" connectNulls isAnimationActive={false} />
              ),
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

// ---------------------------------------------------------------- stacked columns per day
export function StackedColumns({ title, sub, data, series, fmt = compact, height = 240 }: { title: string; sub?: ReactNode; data: Record<string, unknown>[]; series: Series[]; fmt?: (v: number) => string; height?: number }) {
  const p = usePalette();
  const colors = series.map((s) => p[`--series-${s.slot}` as keyof Palette]);
  const ticks = useMemo(() => {
    const n = data.length;
    const step = Math.max(1, Math.ceil(n / 7));
    return data.filter((_, i) => i % step === 0 || i === n - 1).map((d) => d.date as string);
  }, [data]);
  return (
    <ChartCard
      title={title}
      sub={sub}
      legend={<Legend kind="rect" items={series.map((s, i) => ({ label: s.label, color: colors[i] }))} />}
      table={
        <DataTable
          rows={data}
          columns={[{ key: "date", label: "Date", fmt: (v) => dayLabel(String(v)) }, ...series.map((s) => ({ key: s.key, label: s.label, fmt: (v: unknown) => fmt(Number(v ?? 0)) }))]}
        />
      }
    >
      <div className="chart-box" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }} barCategoryGap="30%">
            <CartesianGrid stroke={p["--grid"]} vertical={false} />
            <XAxis dataKey="date" ticks={ticks} tickFormatter={dayLabel} {...axisProps(p)} />
            <YAxis allowDecimals={false} tickFormatter={(v) => fmt(Number(v))} width={48} {...axisProps(p)} axisLine={false} />
            <Tooltip cursor={{ fill: p["--grid"], opacity: 0.4 }} content={<Tip series={series} colors={colors} fmt={fmt} />} />
            {series.map((s, i) => (
              <Bar key={s.key} dataKey={s.key} stackId="a" fill={colors[i]} maxBarSize={24} stroke={p["--surface"]} strokeWidth={2} radius={i === series.length - 1 ? [4, 4, 0, 0] : 0} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

// ---------------------------------------------------------------- ranked horizontal bars (HTML)
export function RankedBars({ title, sub, rows, empty = "No data in this period.", slot = 1 }: { title: string; sub?: ReactNode; rows: { label: string; value: number; hint?: string }[]; empty?: string; slot?: 1 | 2 | 3 }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  const total = rows.reduce((a, r) => a + r.value, 0);
  return (
    <ChartCard
      title={title}
      sub={sub}
      table={
        <table className="table">
          <thead>
            <tr>
              <th>Category</th>
              <th className="num">Count</th>
              <th className="num">Share</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <td>{r.label}</td>
                <td className="num">{r.value}</td>
                <td className="num">{total ? `${Math.round((r.value / total) * 100)}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {rows.length === 0 ? (
        <p className="small subtle" style={{ padding: "32px 0", textAlign: "center" }}>
          {empty}
        </p>
      ) : (
        <div className="hbar">
          {rows.map((r) => (
            <div className="hbar-row" key={r.label} title={`${r.label}: ${r.value}${r.hint ? ` — ${r.hint}` : ""}`}>
              <span className="hbar-label truncate">{r.label}</span>
              <div className="hbar-track">
                <div className="hbar-fill" style={{ width: `${(r.value / max) * 100}%`, background: `var(--series-${slot})` }} />
              </div>
              <span className="hbar-value">{r.value}</span>
            </div>
          ))}
        </div>
      )}
    </ChartCard>
  );
}

// ---------------------------------------------------------------- hour-of-day columns (single series)
export function HourColumns({ title, sub, rows }: { title: string; sub?: ReactNode; rows: { hour: number; count: number }[] }) {
  const p = usePalette();
  const data = rows.map((r) => ({ ...r, label: `${String(r.hour).padStart(2, "0")}:00` }));
  return (
    <ChartCard
      title={title}
      sub={sub}
      table={<DataTable rows={data} columns={[{ key: "label", label: "Hour" }, { key: "count", label: "Conversations" }]} />}
    >
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }} barCategoryGap={2}>
            <CartesianGrid stroke={p["--grid"]} vertical={false} />
            <XAxis dataKey="label" interval={2} {...axisProps(p)} />
            <YAxis allowDecimals={false} width={40} {...axisProps(p)} axisLine={false} />
            <Tooltip
              cursor={{ fill: p["--grid"], opacity: 0.4 }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <div className="viz-tooltip">
                    <div className="t-title">{label}</div>
                    <div className="t-row">
                      <b>{String(payload[0].value)}</b>
                      <span className="t-key">conversations</span>
                    </div>
                  </div>
                ) : null
              }
            />
            <Bar dataKey="count" fill={p["--series-1"]} maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

/** Marker only where there is a value: isolated days stay visible, empty days stay quiet. */
function valueDot(color: string, surface: string, key: string) {
  return (props: { cx?: number; cy?: number; index?: number; payload?: Record<string, unknown> }) => {
    const { cx, cy, index, payload } = props;
    const v = payload?.[key];
    if (v === null || v === undefined || v === 0 || cx === undefined || cy === undefined) return <g key={`d${index}`} />;
    return <circle key={`d${index}`} cx={cx} cy={cy} r={4} fill={color} stroke={surface} strokeWidth={2} />;
  };
}
