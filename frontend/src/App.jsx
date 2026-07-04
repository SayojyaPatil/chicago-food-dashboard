import { useState, useEffect } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, Cell
} from "recharts";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const RISK_COLORS = { High: "#ef4444", Medium: "#f59e0b", Low: "#22c55e" };
const ACCENT      = "#38bdf8";
const FAIL_COLOR  = "#ef4444";
const PASS_COLOR  = "#22c55e";
const COND_COLOR  = "#f59e0b";

function useFetch(endpoint) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    fetch(`${API}${endpoint}`)
      .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [endpoint]);

  return { data, loading, error };
}

function KPICard({ label, value, sub, accent }) {
  return (
    <div className="kpi-card">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value" style={{ color: accent || ACCENT }}>{value}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

function SectionTitle({ children }) {
  return <h2 className="section-title">{children}</h2>;
}

function ChartCard({ title, children, loading, error }) {
  return (
    <div className="chart-card">
      <h3 className="chart-title">{title}</h3>
      {loading && <div className="state-msg">Loading...</div>}
      {error   && <div className="state-msg error">Failed to load data</div>}
      {!loading && !error && children}
    </div>
  );
}

// ── Charts ────────────────────────────────────────────────────────────────────

function PassFailTrend() {
  const { data, loading, error } = useFetch("/metrics/pass-fail-trend");

  return (
    <ChartCard title="Monthly Pass / Fail Trend (24 Months)" loading={loading} error={error}>
      {data && (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="month" tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
              labelStyle={{ color: "#e2e8f0" }}
            />
            <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
            <Line type="monotone" dataKey="pass"             stroke={PASS_COLOR} strokeWidth={2} dot={false} name="Pass" />
            <Line type="monotone" dataKey="fail"             stroke={FAIL_COLOR} strokeWidth={2} dot={false} name="Fail" />
            <Line type="monotone" dataKey="pass_conditions"  stroke={COND_COLOR} strokeWidth={2} dot={false} name="Pass w/ Conditions" />
          </LineChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}

function RiskDistribution() {
  const { data, loading, error } = useFetch("/metrics/risk-distribution");

  return (
    <ChartCard title="Failure Rate by Risk Level" loading={loading} error={error}>
      {data && (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="risk" tick={{ fill: "#94a3b8", fontSize: 12 }} tickLine={false} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} axisLine={false} unit="%" />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
              labelStyle={{ color: "#e2e8f0" }}
              formatter={(v) => [`${v}%`, "Fail Rate"]}
            />
            <Bar dataKey="fail_rate_pct" name="Fail Rate %" radius={[4, 4, 0, 0]}>
              {data.map((entry) => (
                <Cell key={entry.risk} fill={RISK_COLORS[entry.risk] || ACCENT} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}

function TopFacilities() {
  const { data, loading, error } = useFetch("/metrics/top-facility-types");

  return (
    <ChartCard title="Top 10 Facility Types — Pass Rate" loading={loading} error={error}>
      {data && (
        <ResponsiveContainer width="100%" height={320}>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 5, right: 30, left: 120, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
            <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} unit="%" domain={[0, 100]} />
            <YAxis
              type="category"
              dataKey="facility_type"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              tickLine={false}
              width={115}
            />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
              labelStyle={{ color: "#e2e8f0" }}
              formatter={(v) => [`${v}%`, "Pass Rate"]}
            />
            <Bar dataKey="pass_rate_pct" name="Pass Rate %" fill={ACCENT} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}

function ZipFailRates() {
  const { data, loading, error } = useFetch("/metrics/zip-fail-rates");

  return (
    <ChartCard title="Top 15 Zip Codes by Failure Count" loading={loading} error={error}>
      {data && (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="zip" tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} tickLine={false} axisLine={false} />
            <Tooltip
              contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8 }}
              labelStyle={{ color: "#e2e8f0" }}
            />
            <Bar dataKey="failed"            name="Failed"       fill={FAIL_COLOR} radius={[4, 4, 0, 0]} stackId="a" />
            <Bar dataKey="total_inspections" name="Total"        fill="#1e293b"    radius={[4, 4, 0, 0]} stackId="b" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </ChartCard>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const { data: kpi, loading: kpiLoading } = useFetch("/metrics/kpi-summary");

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div>
            <h1 className="header-title">Chicago Food Safety Dashboard</h1>
            <p className="header-sub">Chicago Dept of Public Health — Inspection Analytics</p>
          </div>
          <span className="header-badge">Live Data</span>
        </div>
      </header>

      <main className="main">
        {/* KPI Row */}
        <section className="kpi-row">
          {kpiLoading ? (
            <div className="state-msg">Loading KPIs...</div>
          ) : kpi ? (
            <>
              <KPICard label="Total Inspections"    value={Number(kpi.total_inspections).toLocaleString()} />
              <KPICard label="Overall Pass Rate"    value={`${kpi.overall_pass_rate}%`}   accent={PASS_COLOR} />
              <KPICard label="Total Failures"       value={Number(kpi.total_failed).toLocaleString()}       accent={FAIL_COLOR} />
              <KPICard label="High-Risk Fail Rate"  value={`${kpi.high_risk_fail_rate}%`} accent="#f59e0b" />
              <KPICard label="Zip Codes Covered"    value={kpi.zip_codes_covered} />
            </>
          ) : null}
        </section>

        {/* Charts */}
        <SectionTitle>Compliance Trends</SectionTitle>
        <div className="chart-grid full">
          <PassFailTrend />
        </div>

        <SectionTitle>Risk & Facility Breakdown</SectionTitle>
        <div className="chart-grid two-col">
          <RiskDistribution />
          <TopFacilities />
        </div>

        <SectionTitle>Geographic Analysis</SectionTitle>
        <div className="chart-grid full">
          <ZipFailRates />
        </div>
      </main>

      <footer className="footer">
        Source: City of Chicago Open Data Portal · data.cityofchicago.org
      </footer>
    </div>
  );
}
