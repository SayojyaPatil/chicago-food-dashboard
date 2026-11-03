import { useEffect, useRef, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, LabelList,
} from "recharts";
import "./App.css";

const API = import.meta.env.VITE_API_URL ?? "";

const INK = "#13294B";
const SOFT = "#46597A";
const MID = "#5B8DC9";
const RED = "#C8102E";
const PALE = "#C9DDEE";
const GRID = "#E3ECF4";

const SUGGESTIONS = [
  "Which ZIP code's fail rate rose most from 2024 to 2025?",
  "What was the most cited violation in 2025, and what does the code require?",
  "How cold does the food code say food must be kept?",
];

const TOOL_LABELS = {
  citywide_summary: "Citywide totals",
  zip_fail_rates: "Fail rates by ZIP code",
  compare_zip_fail_rates: "ZIP code changes between years",
  top_violations: "Most cited violations",
  facility_lookup: "Business lookup",
  search_food_code: "Food code search",
};

function useFetch(endpoint) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  useEffect(() => {
    let live = true;
    fetch(`${API}${endpoint}`)
      .then(r => { if (!r.ok) throw new Error(r.statusText || `HTTP ${r.status}`); return r.json(); })
      .then(data => live && setState({ data, loading: false, error: null }))
      .catch(e => live && setState({ data: null, loading: false, error: e.message }));
    return () => { live = false; };
  }, [endpoint]);
  return state;
}

const fmt = n => (n == null ? "–" : Number(n).toLocaleString("en-US"));

function longDate(iso) {
  if (!iso) return null;
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  return d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function Star() {
  // Six-pointed star from the Chicago flag
  const pts = Array.from({ length: 12 }, (_, i) => {
    const r = i % 2 === 0 ? 11 : 5.2;
    const a = (Math.PI / 6) * i - Math.PI / 2;
    return `${12 + r * Math.cos(a)},${12 + r * Math.sin(a)}`;
  }).join(" ");
  return <svg className="star" viewBox="0 0 24 24" aria-hidden="true"><polygon points={pts} /></svg>;
}

// ── Asking ───────────────────────────────────────────────────────────────────

function describeArgs(args = {}) {
  const parts = [];
  if (args.year) parts.push(String(args.year));
  if (args.year_a && args.year_b) parts.push(`${args.year_a} vs ${args.year_b}`);
  if (args.zip) parts.push(`ZIP ${args.zip}`);
  if (args.facility_type) parts.push(args.facility_type);
  if (args.order) parts.push(args.order === "lowest" ? "lowest first" : "highest first");
  if (args.name) parts.push(`"${args.name}"`);
  if (args.query) parts.push(`"${args.query}"`);
  return parts.join(", ");
}

async function streamAnswer(question, onEvent) {
  const response = await fetch(`${API}/agent/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) {
    let detail = `The request failed (${response.status}).`;
    try { detail = (await response.json()).detail || detail; } catch { /* keep default */ }
    throw new Error(detail);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();
    lines.filter(Boolean).forEach(line => onEvent(JSON.parse(line)));
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}

function Ask() {
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState(null);
  const busy = run?.status === "working";
  const inputRef = useRef(null);

  async function ask(text) {
    const q = text.trim();
    if (!q || busy) return;
    setQuestion(q);
    setRun({ question: q, status: "working", steps: [], result: null, error: null });
    try {
      await streamAnswer(q, event => setRun(prev => {
        if (!prev) return prev;
        if (event.type === "tool_start") {
          return { ...prev, steps: [...prev.steps, { tool: event.tool, args: event.args, running: true }] };
        }
        if (event.type === "tool_end") {
          const steps = [...prev.steps];
          const i = steps.findLastIndex(s => s.running && s.tool === event.tool);
          if (i >= 0) steps[i] = { ...event, running: false };
          return { ...prev, steps };
        }
        if (event.type === "answer") return { ...prev, status: "done", result: event, steps: event.steps };
        if (event.type === "error") return { ...prev, status: "error", error: event.detail };
        return prev;
      }));
      setRun(prev => (prev && prev.status === "working"
        ? { ...prev, status: "error", error: "The answer stopped before it finished. Try again." } : prev));
    } catch (e) {
      setRun(prev => ({ ...prev, status: "error", error: e.message }));
    }
  }

  return (
    <>
      <form className="ask-form" onSubmit={e => { e.preventDefault(); ask(question); }}>
        <label className="ask-label" htmlFor="question">Ask what the inspectors found.</label>
        <div className="ask-row">
          <input
            id="question" ref={inputRef} className="ask-input" value={question} maxLength={500}
            onChange={e => setQuestion(e.target.value)} autoComplete="off"
            placeholder="Which ZIP codes got worse this year, and what drove it?"
          />
          <button className="ask-button" type="submit" disabled={busy || question.trim().length < 3}>
            {busy ? "Working" : "Ask"}
          </button>
        </div>
        <div className="suggestions">
          <span>Try</span>
          {SUGGESTIONS.map(s => (
            <button key={s} type="button" className="suggestion" onClick={() => ask(s)} disabled={busy}>{s}</button>
          ))}
        </div>
      </form>
      {run && <Answer run={run} />}
    </>
  );
}

function Answer({ run }) {
  const { result } = run;
  const paragraphs = (result?.answer || "").split(/\n{2,}/).filter(Boolean);
  const totalMs = (run.steps || []).reduce((sum, s) => sum + (s.ms || 0), 0);
  return (
    <section className="answer" aria-live="polite">
      <div className="answer-main">
        <p className="answer-question">{run.question}</p>
        {run.status === "working" && <p className="answer-text answer-pending">Checking the data…</p>}
        {run.status === "error" && <p className="answer-error">{run.error}</p>}
        {result && (
          <>
            <div className="answer-text">{paragraphs.map((p, i) => <p key={i}>{p}</p>)}</div>
            {result.unverified_numbers?.length > 0 && (
              <p className="answer-note">
                <strong>Check before reusing:</strong> {result.unverified_numbers.join(", ")} {result.unverified_numbers.length === 1 ? "does" : "do"} not
                appear in the data the agent retrieved.
              </p>
            )}
            {result.steps?.some(s => s.removed_passages) && (
              <p className="answer-note">Some retrieved text was dropped because it read like instructions rather than code text.</p>
            )}
            {result.sources?.length > 0 && (
              <div className="sources">
                <h3>Food code sections used</h3>
                <ul>{result.sources.map(s => <li key={s.section}><b>{s.section}</b> {s.title}</li>)}</ul>
              </div>
            )}
          </>
        )}
      </div>
      <aside className="work">
        <h3>How it answered</h3>
        {run.steps?.length ? (
          <ol>
            {run.steps.map((s, i) => (
              <li key={i} className={s.running ? "running" : s.ok === false ? "failed" : ""}>
                <div className="step-name">{TOOL_LABELS[s.tool] || s.tool}</div>
                {describeArgs(s.args) && <div className="step-args">{describeArgs(s.args)}</div>}
                <div className="step-meta">
                  {s.running ? "running" : s.ok === false ? `rejected: ${s.error}` : `${s.rows} ${s.tool === "search_food_code" ? "passages" : "rows"} in ${s.ms} ms`}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="work-empty">{run.status === "working" ? "Choosing a data source…" : "Answered without looking anything up."}</p>
        )}
        {result && run.steps?.length > 0 && (
          <p className="work-total">{run.steps.length} lookups, {(result.latency_ms / 1000).toFixed(1)} s total, {totalMs} ms in queries</p>
        )}
      </aside>
    </section>
  );
}

// ── The record ───────────────────────────────────────────────────────────────

function Record({ kpi, freshness }) {
  if (kpi.loading) return <p className="state-msg">Loading the inspection record…</p>;
  if (kpi.error || !kpi.data) return <p className="state-msg error" role="alert">The inspection summary did not load ({kpi.error}).</p>;
  const k = kpi.data;
  const since = longDate(freshness.data?.earliest_inspection_date);
  return (
    <>
      <p className="record-sentence">
        {fmt(k.total_inspections)} inspections{since ? ` since ${since}` : ""}. {k.overall_pass_rate}% passed
        outright and <span className="fail">{fmt(k.total_failed)} failed</span>.
      </p>
      <p className="record-sub">
        High-risk kitchens, the places handling raw food at volume, failed {k.high_risk_fail_rate}% of their
        inspections. The record covers {fmt(k.zip_codes_covered)} ZIP codes.
      </p>
    </>
  );
}

function ChartTip({ active, payload, label, unit = "" }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div><b>{label}</b></div>
      {payload.map(p => <div key={p.dataKey}>{p.name}: {fmt(p.value)}{unit}</div>)}
    </div>
  );
}

function Chart({ title, sub, state, wide, children }) {
  return (
    <section className={`chart${wide ? " wide" : ""}`}>
      <h2>{title}</h2>
      {sub && <p className="chart-sub">{sub}</p>}
      {state.loading && <p className="state-msg">Loading…</p>}
      {state.error && <p className="state-msg error">This chart did not load ({state.error}).</p>}
      {state.data && children(state.data)}
    </section>
  );
}

const axis = { fill: SOFT, fontSize: 13 };

function Trend() {
  const state = useFetch("/metrics/pass-fail-trend");
  return (
    <Chart wide state={state} title="Outcomes by month"
      sub="Inspections per month over the last two years. The newest month is usually still filling in.">
      {data => (
        <>
          <div className="legend">
            <span><i style={{ background: INK }} />Pass</span>
            <span><i style={{ background: MID }} />Pass with conditions</span>
            <span><i style={{ background: RED }} />Fail</span>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" tick={axis} tickLine={false} axisLine={{ stroke: PALE }} minTickGap={40} />
              <YAxis tick={axis} tickLine={false} axisLine={false} width={48} />
              <Tooltip content={<ChartTip />} />
              <Line type="linear" dataKey="pass" name="Pass" stroke={INK} strokeWidth={2.25} dot={false} />
              <Line type="linear" dataKey="pass_conditions" name="Pass with conditions" stroke={MID} strokeWidth={2} dot={false} />
              <Line type="linear" dataKey="fail" name="Fail" stroke={RED} strokeWidth={2.25} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </>
      )}
    </Chart>
  );
}

function Risk() {
  const state = useFetch("/metrics/risk-distribution");
  return (
    <Chart state={state} title="Fail rate by risk level"
      sub="The city rates each business by how much risky food handling it does.">
      {data => (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 22, right: 8, left: -8, bottom: 0 }} barCategoryGap="34%">
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="risk" tick={{ ...axis, fill: INK, fontSize: 14 }} tickLine={false} axisLine={{ stroke: PALE }} />
            <YAxis tick={axis} tickLine={false} axisLine={false} unit="%" width={48} />
            <Tooltip content={<ChartTip unit="%" />} cursor={{ fill: "#F2F8FC" }} />
            <Bar dataKey="fail_rate_pct" name="Fail rate" fill={RED}>
              <LabelList dataKey="fail_rate_pct" position="top" formatter={v => `${v}%`} style={{ fill: INK, fontSize: 13 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </Chart>
  );
}

function Facilities() {
  const state = useFetch("/metrics/top-facility-types");
  return (
    <Chart state={state} title="Pass rate by kind of business" sub="The ten most inspected facility types.">
      {data => (
        <ResponsiveContainer width="100%" height={340}>
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 44, left: 0, bottom: 0 }}>
            <XAxis type="number" domain={[0, 100]} hide />
            <YAxis type="category" dataKey="facility_type" width={typeof window !== "undefined" && window.innerWidth < 520 ? 128 : 170} tickLine={false} axisLine={false}
              tick={{ fill: INK, fontSize: 13 }}
              tickFormatter={l => (l.length > 24 ? `${l.slice(0, 22)}…` : l)} />
            <Tooltip content={<ChartTip unit="%" />} cursor={{ fill: "#F2F8FC" }} />
            <Bar dataKey="pass_rate_pct" name="Pass rate" fill={INK} barSize={14}>
              <LabelList dataKey="pass_rate_pct" position="right" formatter={v => `${v}%`} style={{ fill: INK, fontSize: 13 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </Chart>
  );
}

function Zips() {
  const state = useFetch("/metrics/zip-fail-rates");
  return (
    <Chart wide state={state} title="Where failures add up"
      sub="The 15 ZIP codes with the most failed inspections, against all their other results.">
      {data => {
        const rows = data.map(r => ({ ...r, other: Math.max(0, Number(r.total_inspections) - Number(r.failed)) }));
        return (
          <>
            <div className="legend">
              <span><i style={{ background: RED }} />Failed</span>
              <span><i style={{ background: PALE }} />Other results</span>
            </div>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={rows} margin={{ top: 8, right: 8, left: -8, bottom: 0 }} barCategoryGap="22%">
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="zip" tick={axis} tickLine={false} axisLine={{ stroke: PALE }} />
                <YAxis tick={axis} tickLine={false} axisLine={false} width={48} />
                <Tooltip content={<ChartTip />} cursor={{ fill: "#F2F8FC" }} />
                <Bar dataKey="failed" name="Failed" stackId="z" fill={RED} />
                <Bar dataKey="other" name="Other results" stackId="z" fill={PALE} />
              </BarChart>
            </ResponsiveContainer>
          </>
        );
      }}
    </Chart>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

function FreshnessLine({ state }) {
  const f = state.data;
  if (!f?.latest_inspection_date) return <span className="freshness">City of Chicago open data</span>;
  const through = longDate(f.latest_inspection_date);
  return (
    <span className="freshness">
      Inspections through {through}{f.last_refresh_at ? ", refreshed daily" : ""}
    </span>
  );
}

export default function App() {
  const kpi = useFetch("/metrics/kpi-summary");
  const freshness = useFetch("/metrics/freshness");

  return (
    <>
      <header className="band band-top">
        <div className="wrap">
          <div className="masthead">
            <div className="brand"><Star />Chicago food inspections</div>
            <FreshnessLine state={freshness} />
          </div>
          <Ask />
        </div>
      </header>

      <main className="wrap">
        <section className="record"><Record kpi={kpi} freshness={freshness} /></section>
        <div className="charts">
          <Trend />
          <Risk />
          <Facilities />
          <Zips />
        </div>
      </main>

      <footer className="band band-bottom">
        <div className="wrap">
          <p>
            Data from the City of Chicago <a href="https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5">Food Inspections</a> dataset,
            published by the Department of Public Health. Rule text from the{" "}
            <a href="https://www.chicago.gov/content/dam/city/depts/dol/rulesandregs/CDPH-Food-Code-Rules-02-01-2019.pdf">Chicago Food Code Rules</a>.
          </p>
          <p>Answers are generated from that data by an AI model and can be wrong. Check the steps shown with each answer.</p>
        </div>
      </footer>
    </>
  );
}
