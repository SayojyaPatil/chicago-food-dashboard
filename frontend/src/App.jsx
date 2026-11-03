import { useEffect, useRef, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, LabelList, ReferenceLine, Cell,
} from "recharts";
import "./App.css";

const API = import.meta.env.VITE_API_URL ?? "";

const INK = "#13294B";
const SOFT = "#46597A";
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

function Mark() {
  // An inspection checklist box with a tick. Our own mark, not a city symbol.
  return (
    <svg className="mark" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M7.5 12.5l3 3 6-7" />
    </svg>
  );
}

// ── Asking ───────────────────────────────────────────────────────────────────

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// The model sometimes writes **bold** or *italic*. Render those two cases;
// everything else stays plain text (no HTML is ever injected).
function Inline({ text }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g);
  return parts.map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (/^\*[^*\s][^*]*\*$/.test(part)) return <em key={i}>{part.slice(1, -1)}</em>;
    return part;
  });
}

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
  const cited = (result?.sources || []).filter(src => (result?.answer || "").includes(src.section));
  return (
    <section className="answer" aria-live="polite">
      <div className="answer-main">
        <p className="answer-question">{run.question}</p>
        {run.status === "working" && <p className="answer-text answer-pending">Checking the data…</p>}
        {run.status === "error" && <p className="answer-error">{run.error}</p>}
        {result && (
          <>
            <div className="answer-text">{paragraphs.map((p, i) => <p key={i}><Inline text={p} /></p>)}</div>
            {result.unverified_numbers?.length > 0 && (
              <p className="answer-note">
                <strong>Check before reusing:</strong> {result.unverified_numbers.join(", ")} {result.unverified_numbers.length === 1 ? "does" : "do"} not
                appear in the data the agent retrieved.
              </p>
            )}
            {result.steps?.some(s => s.removed_passages) && (
              <p className="answer-note">Some retrieved text was dropped because it read like instructions rather than code text.</p>
            )}
            {cited.length > 0 && (
              <div className="sources">
                <h3>Food code sections cited</h3>
                <ul>{cited.map(s => <li key={s.section}><b>{s.section}</b> {s.title}</li>)}</ul>
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
                  {s.running ? "running" : s.ok === false ? `rejected: ${s.error}` : `${plural(s.rows, s.tool === "search_food_code" ? "passage" : "row")} in ${s.ms} ms`}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="work-empty">{run.status === "working" ? "Choosing a data source…"
            : run.status === "error" ? "Stopped before any lookup."
            : "Answered without looking anything up."}</p>
        )}
        {result && run.steps?.length > 0 && (
          <p className="work-total">{plural(run.steps.length, "lookup")}, {(result.latency_ms / 1000).toFixed(1)} s total, {totalMs} ms in queries</p>
        )}
      </aside>
    </section>
  );
}

// ── The record ───────────────────────────────────────────────────────────────

const KEEP_UPPER = new Set(["TCS", "HACCP", "PIC", "CFPM", "UL", "NSF", "CDPH"]);

function sentenceCase(title = "") {
  const lower = title.toLowerCase().replace(/\b(\d+)f\b/g, "$1°F");
  const words = lower.split(/(\s+)/).map(w => (KEEP_UPPER.has(w.replace(/[^a-z]/gi, "").toUpperCase()) ? w.toUpperCase() : w));
  const text = words.join("").replace(/\bchicago\b/g, "Chicago");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const pct = v => (v == null ? "–" : `${Number(v).toFixed(1)}%`);

function oneIn(rate) {
  const n = Math.round(100 / Number(rate));
  return Number.isFinite(n) && n > 1 ? `about 1 in ${n}` : pct(rate);
}

function Record({ kpi, risk, period }) {
  if (kpi.loading) return <p className="state-msg">Loading the inspection record…</p>;
  if (kpi.error || !kpi.data) return <p className="state-msg error" role="alert">The inspection summary did not load ({kpi.error}).</p>;
  const k = kpi.data;
  const high = risk.data?.find(r => r.risk === "High");
  const low = risk.data?.find(r => r.risk === "Low");
  return (
    <>
      <p className="record-sentence">
        {capitalize(period.label)}, city inspectors made {fmt(k.total_inspections)} inspections,
        and <span className="fail">{oneIn(k.fail_rate)} failed</span>.
      </p>
      <p className="record-sub">
        {pct(k.overall_pass_rate)} passed, {pct(k.conditions_rate)} passed with conditions (problems found
        and fixed during the visit), and {pct(k.fail_rate)} failed.
        {k.prior_fail_rate != null ? ` The year before, ${pct(k.prior_fail_rate)} failed.` : ""}
        {high && low ? ` Places with the most complex food handling failed ${pct(high.fail_rate_pct)} of the time, against ${pct(low.fail_rate_pct)} for the simplest.` : ""}
      </p>
    </>
  );
}

function ChartTip({ active, payload, label, render }) {
  if (!active || !payload?.length) return null;
  return <div className="chart-tooltip">{render(payload[0].payload, label)}</div>;
}

function Chart({ title, sub, state, children }) {
  return (
    <div className="chart">
      <h3>{state.data?.length ? title(state.data) : " "}</h3>
      {sub && <p className="chart-sub">{sub}</p>}
      {state.loading && <p className="state-msg">Loading…</p>}
      {state.error && <p className="state-msg error">This chart did not load ({state.error}).</p>}
      {state.data && (state.data.length ? children(state.data) : <p className="state-msg">No inspections in this period.</p>)}
    </div>
  );
}

const axis = { fill: SOFT, fontSize: 13 };

// One-line category labels. Recharts wraps long labels and then hides
// neighbouring ticks to make room; this keeps every label, truncated.
function CategoryTick({ x, y, payload, max = 40 }) {
  const text = String(payload.value);
  const shown = text.length > max ? `${text.slice(0, max - 1)}…` : text;
  return (
    <text x={x} y={y} dy={4} textAnchor="end" fill={INK} fontSize={13}>
      <title>{text}</title>{shown}
    </text>
  );
}

// Describe the period the data actually covers, not an assumed 12 months.
function coverage(freshness) {
  const f = freshness?.data;
  if (!f?.earliest_inspection_date || !f?.latest_inspection_date) return { full: true, label: "in the last 12 months" };
  const latest = new Date(`${f.latest_inspection_date}T12:00:00`);
  const earliest = new Date(`${f.earliest_inspection_date}T12:00:00`);
  const yearAgo = new Date(latest); yearAgo.setFullYear(latest.getFullYear() - 1);
  if (earliest <= yearAgo) return { full: true, label: "in the last 12 months" };
  const since = earliest.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  return { full: false, label: `since ${since}` };
}

// Value label with a white outline, so reference lines pass behind the number.
function ValueLabel({ x, y, width, height, value }) {
  if (value == null) return null;
  return (
    <text x={x + width + 6} y={y + height / 2} dy={4} fill={INK} fontSize={13}
      stroke="#FFFFFF" strokeWidth={5} strokeLinejoin="round" paintOrder="stroke">
      {pct(value)}
    </text>
  );
}

const capitalize = t => t.charAt(0).toUpperCase() + t.slice(1);

function monthLabel(m) {
  const d = new Date(`${m}-15T12:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

function Trend({ kpi, period }) {
  const state = useFetch("/metrics/pass-fail-trend");
  const k = kpi.data;
  const title = () => {
    if (k?.fail_rate == null) return "Is it getting better or worse?";
    if (k.prior_fail_rate == null) return `Fail rate ${period.label}: ${pct(k.fail_rate)}`;
    const diff = Number(k.fail_rate) - Number(k.prior_fail_rate);
    if (Math.abs(diff) < 0.5) return `Failures held steady: ${pct(k.fail_rate)} this year, ${pct(k.prior_fail_rate)} the year before`;
    return `Failures went ${diff < 0 ? "down" : "up"}: ${pct(k.fail_rate)} this year, ${pct(k.prior_fail_rate)} the year before`;
  };
  return (
    <Chart state={state} title={title}
      sub={`Share of inspections that failed, month by month${period.full ? ", over up to two years" : ""}. The dashed line is the average ${period.label}. The latest month may be incomplete.`}>
      {data => (
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={data} margin={{ top: 12, right: 16, left: -6, bottom: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="month" tick={axis} tickLine={false} axisLine={{ stroke: PALE }} minTickGap={36} tickFormatter={monthLabel} />
            <YAxis tick={axis} tickLine={false} axisLine={false} width={48} unit="%" domain={[0, "auto"]} />
            {k?.fail_rate && <ReferenceLine y={Number(k.fail_rate)} stroke={SOFT} strokeDasharray="4 4" />}
            <Tooltip content={<ChartTip render={r => (
              <><b>{monthLabel(r.month)}</b><div>{pct(r.fail_rate_pct)} failed</div><div>{fmt(r.fail)} of {fmt(r.inspections)} inspections</div></>
            )} />} />
            <Line type="linear" dataKey="fail_rate_pct" name="Fail rate" stroke={RED} strokeWidth={2.5}
              dot={{ r: 2.5, fill: RED, strokeWidth: 0 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </Chart>
  );
}

function Violations({ period }) {
  const state = useFetch("/metrics/top-violations");
  const narrow = typeof window !== "undefined" && window.innerWidth < 520;
  return (
    <Chart state={state}
      title={d => `Most common problem: ${sentenceCase(d[0].title).toLowerCase()}, found in ${pct(d[0].share_pct)} of inspections`}
      sub={`Share of inspections ${period.label} that cited each problem. One inspection can cite several, so the bars add up to more than 100%.`}>
      {data => {
        const rows = data.map(r => ({ ...r, label: `${r.violation_number}. ${sentenceCase(r.title)}` }));
        if (narrow) {
          const top = Math.max(...rows.map(r => Number(r.share_pct)));
          return (
            <ul className="stacked-bars">
              {rows.map(r => (
                <li key={r.violation_number}>
                  <span className="stacked-label">{r.label}</span>
                  <span className="stacked-row">
                    <span className="stacked-bar" style={{ width: `${(Number(r.share_pct) / top) * 82}%` }} />
                    <span className="stacked-value">{pct(r.share_pct)}</span>
                  </span>
                </li>
              ))}
            </ul>
          );
        }
        return (
          <ResponsiveContainer width="100%" height={rows.length * 38 + 10}>
            <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 56, left: 0, bottom: 0 }}>
              <XAxis type="number" hide domain={[0, "dataMax"]} />
              <YAxis type="category" dataKey="label" width={narrow ? 160 : 400} interval={0} tickLine={false} axisLine={false}
                tick={<CategoryTick max={narrow ? 22 : 56} />} />
              <Tooltip cursor={{ fill: "#F2F8FC" }} content={<ChartTip render={r => (
                <><b>{r.label}</b><div>{fmt(r.inspections_cited)} inspections ({pct(r.share_pct)})</div></>
              )} />} />
              <Bar dataKey="share_pct" fill={INK} barSize={16}>
                <LabelList dataKey="share_pct" position="right" formatter={pct} style={{ fill: INK, fontSize: 13 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        );
      }}
    </Chart>
  );
}

function RateBars({ data, labelKey, city, height, labelWidth, max }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 18, right: 52, left: 0, bottom: 0 }}>
        <XAxis type="number" hide domain={[0, dataMax => Math.max(max || dataMax, dataMax, Number(city || 0)) * 1.1]} />
        <YAxis type="category" dataKey={labelKey} width={labelWidth} interval={0} tickLine={false} axisLine={false}
          tick={<CategoryTick max={labelWidth > 100 ? 22 : 8} />} />
        <Tooltip cursor={{ fill: "#F2F8FC" }} content={<ChartTip render={r => (
          <><b>{r[labelKey]}</b><div>{pct(r.fail_rate_pct)} failed</div><div>{fmt(r.failed)} of {fmt(r.total_inspections)} inspections</div></>
        )} />} />
        {city && <ReferenceLine x={Number(city)} stroke={SOFT} strokeDasharray="4 4"
          label={{ value: `City ${pct(city)}`, position: "top", fill: SOFT, fontSize: 12 }} />}
        <Bar dataKey="fail_rate_pct" barSize={14}>
          {data.map(r => <Cell key={r[labelKey]} fill={Number(r.fail_rate_pct) > Number(city) ? RED : PALE} />)}
          <LabelList dataKey="fail_rate_pct" content={<ValueLabel />} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function Zips({ kpi, period }) {
  const state = useFetch("/metrics/zip-fail-rates");
  const city = kpi.data?.fail_rate;
  return (
    <Chart state={state}
      title={d => `ZIP codes range from ${pct(d[d.length - 1].fail_rate_pct)} to ${pct(d[0].fail_rate_pct)} failed`}
      sub={`Highest and lowest fail rates among ZIP codes with at least 100 inspections ${period.label}. Red bars are above the citywide rate.`}>
      {data => {
        const top = data.slice(0, 6);
        const bottom = data.length > 10 ? data.slice(-4) : data.slice(6);
        const max = Number(data[0].fail_rate_pct);
        return (
          <>
            <h3 className="chart-group">Highest</h3>
            <RateBars data={top} labelKey="zip" city={city} max={max} height={top.length * 30 + 30} labelWidth={64} />
            {bottom.length > 0 && (
              <>
                <h3 className="chart-group">Lowest</h3>
                <RateBars data={bottom} labelKey="zip" city={city} max={max} height={bottom.length * 30 + 30} labelWidth={64} />
              </>
            )}
          </>
        );
      }}
    </Chart>
  );
}

function Facilities({ kpi, period }) {
  const state = useFetch("/metrics/top-facility-types");
  const city = kpi.data?.fail_rate;
  return (
    <Chart state={state}
      title={d => { const worst = [...d].sort((a, b) => b.fail_rate_pct - a.fail_rate_pct)[0]; return `Highest fail rate by kind of business: ${worst.facility_type}, ${pct(worst.fail_rate_pct)}`; }}
      sub={`Fail rate for the ten most inspected kinds of business ${period.label}. Red bars are above the citywide rate.`}>
      {data => {
        const rows = [...data].sort((a, b) => b.fail_rate_pct - a.fail_rate_pct);
        return <RateBars data={rows} labelKey="facility_type" city={city} height={rows.length * 30 + 30}
          labelWidth={typeof window !== "undefined" && window.innerWidth < 520 ? 140 : 180} />;
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
  const risk = useFetch("/metrics/risk-distribution");
  const freshness = useFetch("/metrics/freshness");
  const period = coverage(freshness);

  return (
    <>
      <header className="band band-top">
        <div className="wrap">
          <div className="masthead">
            <div className="brand"><Mark />Chicago food inspections</div>
            <FreshnessLine state={freshness} />
          </div>
          <Ask />
        </div>
      </header>

      <main className="wrap">
        <section className="block" aria-labelledby="overall">
          <h2 className="block-title" id="overall">Overall</h2>
          <div className="overview">
            <div className="record"><Record kpi={kpi} risk={risk} period={period} /></div>
            <Trend kpi={kpi} period={period} />
          </div>
        </section>

        <section className="block" aria-labelledby="problems">
          <h2 className="block-title" id="problems">What goes wrong</h2>
          <Violations period={period} />
        </section>

        <section className="block" aria-labelledby="where">
          <h2 className="block-title" id="where">Where, and at what kind of place</h2>
          <div className="pair">
            <Zips kpi={kpi} period={period} />
            <Facilities kpi={kpi} period={period} />
          </div>
        </section>
      </main>

      <footer className="band band-bottom">
        <div className="wrap">
          <p>
            Data from the City of Chicago <a href="https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5">Food Inspections</a> dataset,
            published by the Department of Public Health. Rule text from the{" "}
            <a href="https://www.chicago.gov/content/dam/city/depts/dol/rulesandregs/CDPH-Food-Code-Rules-02-01-2019.pdf">Chicago Food Code Rules</a>.
          </p>
          <p>Answers are generated from that data by an AI model and can be wrong. Check the steps shown with each answer.</p>
          <p className="legal">
            This site provides applications using data that has been modified for use from its original source,
            www.cityofchicago.org, the official website of the City of Chicago. The City of Chicago makes no claims as to
            the content, accuracy, timeliness, or completeness of any of the data provided at this site. The data provided
            at this site is subject to change at any time. It is understood that the data provided at this site is being
            used at one's own risk. This project is not affiliated with or endorsed by the City of Chicago.
            See the Data Portal <a href="https://www.chicago.gov/city/en/narr/foia/CityData.html">terms of use</a>.
          </p>
        </div>
      </footer>
    </>
  );
}
