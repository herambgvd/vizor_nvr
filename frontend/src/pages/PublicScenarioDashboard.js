import React, { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

// Public, UNAUTHENTICATED scenario analytics dashboard (FRS / PPE / ANPR / …).
// Aggregate numbers only — no snapshots/raw images. Realtime via the backend SSE
// relay. Vercel-style: full-bleed near-black surface, hairline borders, inline
// SVG charts. Per-scenario labels come from SCENARIO_DESCRIPTORS; the data shape
// (totals / by_camera / hourly_trend) is uniform across scenarios.

const BRANDING_URL = "/api/settings/public/branding";

// Per-scenario presentation. `cards` map totals keys -> label+accent; `split`
// (optional) draws the two-way donut; `topList` (optional) renders a ranked list
// (gated behind show_names for PII). `feedLabel(ev)` formats a live-feed row.
const SCENARIO_DESCRIPTORS = {
  frs: {
    title: "Face Recognition",
    cards: [
      { key: "recognized_today", label: "Recognized today", accent: "green" },
      { key: "unknown_today", label: "Unknown today", accent: "amber" },
      { key: "events_today", label: "Events today", accent: "blue" },
      { key: "enrolled_persons", label: "Enrolled people", accent: "violet" },
    ],
    split: { title: "Recognition split", a: "recognized_today", aLabel: "Recognized", b: "unknown_today", bLabel: "Unknown" },
    topList: { title: "Most seen today", source: "top_persons", name: "name" },
    feedLabel: (ev) => (ev.person_name || (ev.event_type || "").replace(/_/g, " ")),
  },
  ppe: {
    title: "PPE Compliance",
    cards: [
      { key: "violations_today", label: "Violations today", accent: "amber" },
      { key: "compliant_today", label: "Compliant today", accent: "green" },
      { key: "events_today", label: "Events today", accent: "blue" },
    ],
    split: { title: "Compliance split", a: "compliant_today", aLabel: "Compliant", b: "violations_today", bLabel: "Violation" },
    topList: { title: "Top violations today", source: "top_violation_types", name: "type" },
    feedLabel: (ev) => (ev.label || (ev.event_type || "").replace(/_/g, " ")),
  },
  anpr: {
    title: "License Plate Recognition",
    cards: [
      { key: "reads_today", label: "Plate reads today", accent: "blue" },
      { key: "blacklist_hits_today", label: "Alert hits today", accent: "amber" },
      { key: "whitelist_hits_today", label: "Allowed today", accent: "green" },
      { key: "unique_plates_today", label: "Unique plates", accent: "violet" },
    ],
    topList: { title: "By vehicle type", source: "by_vehicle_type", name: "type", count: "count" },
    feedLabel: (ev) => (ev.label || ev.plate || (ev.event_type || "").replace(/_/g, " ")),
  },
  "suspect-search": {
    title: "Suspect Search",
    cards: [
      { key: "searches_today", label: "Searches today", accent: "blue" },
      { key: "matches_today", label: "Matches today", accent: "green" },
      { key: "indexed_candidates", label: "Indexed", accent: "violet" },
    ],
    feedLabel: (ev) => (ev.label || (ev.event_type || "").replace(/_/g, " ")),
  },
};

// Format a timestamp in the operator-configured display timezone (fetched from
// public branding). Falls back to browser-local until tz is known.
function fmtTime(value, tz) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const opt = { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false };
  try {
    if (tz && tz !== "UTC") return d.toLocaleTimeString("en-GB", { ...opt, timeZone: tz });
  } catch { /* bad tz -> local */ }
  return d.toLocaleTimeString("en-GB", opt);
}

const C = {
  bg: "#000000",
  panel: "#0a0a0a",
  panel2: "#161616",
  border: "#1f1f1f",
  borderHi: "#2a2a2a",
  text: "#ededed",
  muted: "#a1a1a1",
  faint: "#666666",
  green: "#3fd07a",
  greenDim: "#1a7f44",
  amber: "#f5a623",
  blue: "#52a8ff",
  violet: "#a78bfa",
};

function useCountUp(target, ms = 800) {
  const [v, setV] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const start = performance.now();
    const a = from.current;
    const b = Number(target) || 0;
    let raf;
    const tick = (now) => {
      const p = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - p, 3);
      setV(Math.round(a + (b - a) * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
      else from.current = b;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

const card = { background: C.panel, border: `1px solid ${C.border}`, borderRadius: 12 };

const StatCard = ({ label, value, accent }) => {
  const n = useCountUp(value);
  return (
    <div style={{ ...card, padding: "20px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 7, height: 7, borderRadius: 2, background: accent }} />
        <div style={{ fontSize: 12, color: C.muted, letterSpacing: 0.2 }}>{label}</div>
      </div>
      <div style={{ marginTop: 14, fontSize: 38, fontWeight: 700, lineHeight: 1, color: C.text, letterSpacing: -1 }}>{n}</div>
    </div>
  );
};

const Donut = ({ recognized, unknown, aLabel = "Recognized", bLabel = "Unknown" }) => {
  const total = recognized + unknown;
  const r = 58, sw = 14, cx = 76, cy = 76, circ = 2 * Math.PI * r;
  const recFrac = total ? recognized / total : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 26, flexWrap: "wrap" }}>
      <svg width="152" height="152" viewBox="0 0 152 152">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={C.panel2} strokeWidth={sw} />
        {total > 0 && (
          <>
            <circle cx={cx} cy={cy} r={r} fill="none" stroke={C.amber} strokeWidth={sw}
              strokeDasharray={`${circ} ${circ}`} transform={`rotate(-90 ${cx} ${cy})`} opacity={unknown ? 1 : 0} />
            <circle cx={cx} cy={cy} r={r} fill="none" stroke={C.green} strokeWidth={sw} strokeLinecap="round"
              strokeDasharray={`${circ * recFrac} ${circ}`} transform={`rotate(-90 ${cx} ${cy})`}
              style={{ transition: "stroke-dasharray .8s cubic-bezier(.4,0,.2,1)" }} />
          </>
        )}
        <text x={cx} y={cy - 2} textAnchor="middle" fill={C.text} fontSize="28" fontWeight="700">{total}</text>
        <text x={cx} y={cy + 16} textAnchor="middle" fill={C.faint} fontSize="9" letterSpacing="1.5">TODAY</text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <Legend color={C.green} label={aLabel} value={recognized} pct={total ? Math.round(recFrac * 100) : 0} />
        <Legend color={C.amber} label={bLabel} value={unknown} pct={total ? Math.round((1 - recFrac) * 100) : 0} />
      </div>
    </div>
  );
};
const Legend = ({ color, label, value, pct }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
    <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
    <div>
      <div style={{ fontSize: 14, color: C.text, fontWeight: 600 }}>{value} <span style={{ color: C.faint, fontWeight: 400, fontSize: 12 }}>· {pct}%</span></div>
      <div style={{ fontSize: 11, color: C.muted }}>{label}</div>
    </div>
  </div>
);

// Render an hourly bucket's label in the operator's local timezone (the backend
// buckets in UTC and sends a UTC ISO `ts`); fall back to the UTC `hour` string.
const hourLabel = (d) => {
  if (d?.ts) {
    const dt = new Date(d.ts);
    if (!Number.isNaN(dt.getTime())) return `${String(dt.getHours()).padStart(2, "0")}:00`;
  }
  return d?.hour ?? "";
};

const AreaChart = ({ data }) => {
  const w = 720, h = 220, pad = 30;
  if (!data.length) return <Empty label="No activity today yet." h="100%" />;
  const max = Math.max(1, ...data.map((d) => d.count));
  const stepX = data.length > 1 ? (w - pad * 2) / (data.length - 1) : 0;
  const x = (i) => pad + i * stepX;
  const y = (v) => h - pad - (v / max) * (h - pad * 2);
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(d.count)}`).join(" ");
  const area = `${line} L${x(data.length - 1)},${h - pad} L${x(0)},${h - pad} Z`;
  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id="frsArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.green} stopOpacity="0.22" />
          <stop offset="100%" stopColor={C.green} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0, 0.5, 1].map((g) => (
        <line key={g} x1={pad} x2={w - pad} y1={y(max * g)} y2={y(max * g)} stroke={C.border} strokeWidth="1" />
      ))}
      <path d={area} fill="url(#frsArea)" />
      <path d={line} fill="none" stroke={C.green} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {data.map((d, i) => <circle key={i} cx={x(i)} cy={y(d.count)} r="2.5" fill={C.bg} stroke={C.green} strokeWidth="1.5" />)}
      {data.map((d, i) => (
        (i === 0 || i === data.length - 1 || i === Math.floor(data.length / 2)) &&
        <text key={`t${i}`} x={x(i)} y={h - 9} textAnchor="middle" fill={C.faint} fontSize="10">{hourLabel(d)}</text>
      ))}
    </svg>
  );
};

const HBars = ({ data }) => {
  if (!data.length) return <Empty label="No camera activity yet." h={120} />;
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {data.map((d) => (
        <div key={d.camera_id}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
            <span style={{ color: C.text }}>{d.camera_name || d.camera_id}</span><span style={{ color: C.muted }}>{d.count}</span>
          </div>
          <div style={{ height: 8, background: C.panel2, borderRadius: 4, overflow: "hidden" }}>
            <div style={{ width: `${(d.count / max) * 100}%`, height: "100%", background: C.green, borderRadius: 4, transition: "width .8s cubic-bezier(.4,0,.2,1)" }} />
          </div>
        </div>
      ))}
    </div>
  );
};

const Empty = ({ label, h }) => (
  <div style={{ height: h, display: "flex", alignItems: "center", justifyContent: "center", color: C.faint, fontSize: 13 }}>{label}</div>
);

const Panel = ({ title, children, right, fill, scroll }) => (
  <div style={{ ...card, padding: 18, display: "flex", flexDirection: "column", minHeight: 0, height: fill ? "100%" : undefined }}>
    <div style={{ flex: "0 0 auto", display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
      <h3 style={{ margin: 0, fontSize: 11, textTransform: "uppercase", letterSpacing: 1, color: C.muted, fontWeight: 600 }}>{title}</h3>
      {right}
    </div>
    <div style={{ flex: fill ? "1 1 0" : "0 0 auto", minHeight: 0, overflowY: scroll ? "auto" : "visible", display: "flex", flexDirection: "column", justifyContent: scroll ? "flex-start" : "center" }}>
      {children}
    </div>
  </div>
);

export default function PublicScenarioDashboard() {
  const { slug = "frs" } = useParams();
  const desc = SCENARIO_DESCRIPTORS[slug] || {
    title: slug.toUpperCase(), cards: [], feedLabel: (ev) => (ev.event_type || "").replace(/_/g, " "),
  };
  const DASHBOARD_URL = `/api/ai/${slug}/public/dashboard`;
  const STREAM_URL = `/api/ai/${slug}/public/stream`;

  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading");
  const [live, setLive] = useState([]);
  const [flash, setFlash] = useState(false);
  const [tz, setTz] = useState(null); // operator display timezone
  const esRef = useRef(null);

  const load = async () => {
    try {
      const r = await fetch(DASHBOARD_URL);
      if (r.status === 404) { setStatus("unavailable"); return; }
      if (!r.ok) { setStatus("error"); return; }
      setData(await r.json());
      setStatus("ok");
    } catch { setStatus("error"); }
  };

  useEffect(() => {
    load();
    // Pick up the operator display timezone (public, no auth).
    fetch(BRANDING_URL).then((r) => r.ok ? r.json() : null).then((b) => {
      if (b?.timezone) setTz(b.timezone);
    }).catch(() => {});
    const poll = setInterval(load, 30000);
    try {
      const es = new EventSource(STREAM_URL);
      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data);
          setLive((prev) => [ev, ...prev].slice(0, 14));
          setFlash(true);
          setTimeout(() => setFlash(false), 600);
          load();
        } catch { /* heartbeat */ }
      };
      esRef.current = es;
    } catch { /* SSE unsupported */ }
    return () => { clearInterval(poll); esRef.current?.close(); };
  }, []);

  const shell = (children) => (
    <div style={{ height: "100vh", width: "100%", background: C.bg, color: C.text, fontFamily: "Inter, system-ui, sans-serif", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      {/* full-bleed header bar */}
      <div style={{ flex: "0 0 auto", borderBottom: `1px solid ${C.border}`, padding: "14px 28px", display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ width: 10, height: 10, borderRadius: 999, background: C.green, boxShadow: `0 0 0 ${flash ? 7 : 3}px ${C.green}1f`, transition: "box-shadow .4s" }} />
        <h1 style={{ fontSize: 17, fontWeight: 600, margin: 0, letterSpacing: -0.2 }}>{desc.title}</h1>
        <span style={{ fontSize: 13, color: C.faint }}>Live Overview</span>
        <span style={{ marginLeft: "auto", fontSize: 12, color: C.faint }}>
          {data?.generated_at ? `Updated ${fmtTime(data.generated_at, tz)}` : ""}
        </span>
      </div>
      <div style={{ flex: "1 1 auto", minHeight: 0, padding: "16px 28px", display: "flex", flexDirection: "column", gap: 14 }}>{children}</div>
    </div>
  );

  if (status === "loading") return shell(<p style={{ color: C.muted }}>Loading…</p>);
  if (status === "unavailable") return shell(<Centered title="Dashboard not available" sub="This public view is currently turned off." />);
  if (status === "error") return shell(<Centered title="Couldn’t load the dashboard" sub="Please try again in a moment." />);

  const t = data?.totals || {};
  const ACCENT = { green: C.green, amber: C.amber, blue: C.blue, violet: C.violet };
  // Top list comes from a scenario-named source array; gate identity lists behind show_names.
  const topSrc = desc.topList ? (data?.[desc.topList.source] || []) : [];
  const topIsPII = desc.topList && desc.topList.source === "top_persons";
  const hasTop = desc.topList && topSrc.length > 0 && (!topIsPII || data?.show_names);
  const cards = (desc.cards || []).slice(0, 4);

  return shell(
    <>
      {/* Row 1 — stat cards (fixed) */}
      <div style={{ flex: "0 0 auto", display: "grid", gridTemplateColumns: `repeat(${cards.length || 1},1fr)`, gap: 14 }}>
        {cards.map((c) => (
          <StatCard key={c.key} label={c.label} value={t[c.key] ?? 0} accent={ACCENT[c.accent] || C.blue} />
        ))}
      </div>

      {/* Row 2 — trend + split (fills, equal share) */}
      <div style={{ flex: "1 1 0", minHeight: 0, display: "grid", gridTemplateColumns: desc.split ? "minmax(0,2fr) minmax(0,1fr)" : "1fr", gap: 14 }}>
        <Panel title="Activity — today" fill><div style={{ flex: 1, minHeight: 0 }}><AreaChart data={data?.hourly_trend || []} /></div></Panel>
        {desc.split && (
          <Panel title={desc.split.title} fill>
            <Donut recognized={t[desc.split.a] ?? 0} unknown={t[desc.split.b] ?? 0} aLabel={desc.split.aLabel} bLabel={desc.split.bLabel} />
          </Panel>
        )}
      </div>

      {/* Row 3 — by camera / top list + live feed (fills, equal share) */}
      <div style={{ flex: "1 1 0", minHeight: 0, display: "grid", gridTemplateColumns: hasTop ? "1fr 1fr 1.2fr" : "1fr 1.4fr", gap: 14 }}>
        <Panel title="By camera (today)" fill scroll><HBars data={data?.by_camera || []} /></Panel>
        {hasTop && (
          <Panel title={desc.topList.title} fill scroll>
            {topSrc.map((p, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 0", borderBottom: i < topSrc.length - 1 ? `1px solid ${C.border}` : "none" }}>
                <span style={{ width: 22, height: 22, borderRadius: 6, background: C.panel2, color: C.green, fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{i + 1}</span>
                <span style={{ flex: 1, fontSize: 14 }}>{p[desc.topList.name] ?? "—"}</span>
                <span style={{ color: C.text, fontWeight: 600 }}>{p[desc.topList.count || "count"] ?? 0}</span>
              </div>
            ))}
          </Panel>
        )}
        <Panel title="Live feed" fill scroll right={<span style={{ fontSize: 11, color: C.green, display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 6, height: 6, borderRadius: 999, background: C.green }} />realtime</span>}>
        {live.length === 0 ? (
          <Empty label="Waiting for new events…" h={72} />
        ) : (
          <div style={{ display: "flex", flexDirection: "column" }}>
            {live.map((ev, i) => {
              const rec = ev.event_type === "face_recognized";
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 0", borderBottom: i < live.length - 1 ? `1px solid ${C.border}` : "none", animation: i === 0 ? "frsIn .4s ease" : "none" }}>
                  {ev.crop_key ? (
                    <img src={`/api/ai/${slug}/public/snapshot?key=${encodeURIComponent(ev.crop_key)}`} alt=""
                      style={{ width: 34, height: 44, objectFit: "cover", borderRadius: 4, flexShrink: 0, background: C.panel2 }}
                      onError={(e) => { e.currentTarget.style.display = "none"; }} />
                  ) : (
                    <span style={{ width: 7, height: 7, borderRadius: 999, background: rec ? C.green : C.amber }} />
                  )}
                  <span style={{ flex: 1, fontSize: 13.5 }}>
                    {desc.feedLabel(ev)}
                    <span style={{ color: C.faint }}> · {ev.camera_name || (ev.camera_id ? String(ev.camera_id).slice(0, 8) : "—")}</span>
                  </span>
                  {ev.confidence != null && <span style={{ fontSize: 12, color: C.muted }}>{Math.round(ev.confidence * 100)}%</span>}
                  <span style={{ fontSize: 12, color: C.faint, minWidth: 70, textAlign: "right" }}>
                    {ev.triggered_at ? fmtTime(ev.triggered_at, tz) : ""}
                  </span>
                </div>
              );
            })}
          </div>
        )}
        </Panel>
      </div>

      <style>{`@keyframes frsIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}`}</style>
    </>
  );
}

const Centered = ({ title, sub }) => (
  <div style={{ minHeight: "50vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
    <p style={{ fontSize: 18, fontWeight: 600, color: "#ededed", margin: 0 }}>{title}</p>
    <p style={{ fontSize: 13, color: "#a1a1a1", margin: 0 }}>{sub}</p>
  </div>
);
