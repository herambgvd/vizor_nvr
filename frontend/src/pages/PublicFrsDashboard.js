import React, { useEffect, useRef, useState } from "react";

// Public, UNAUTHENTICATED FRS analytics dashboard. Aggregate numbers only — no
// faces, no snapshots. Realtime via the backend's SSE relay. If the operator
// hasn't enabled the public dashboard, the API returns 404 and we show an
// "unavailable" state (no internals leaked).

const DASHBOARD_URL = "/api/ai/frs/public/dashboard";
const STREAM_URL = "/api/ai/frs/public/stream";

const Stat = ({ label, value, accent }) => (
  <div
    style={{
      background: "#0f1f1a",
      border: "1px solid #1f3a30",
      borderRadius: 10,
      padding: "20px 22px",
      minWidth: 0,
    }}
  >
    <div style={{ fontSize: 11, letterSpacing: 2, textTransform: "uppercase", color: "#6f8c80" }}>{label}</div>
    <div style={{ marginTop: 8, fontSize: 34, fontWeight: 700, color: accent || "#e6f2ec" }}>{value}</div>
  </div>
);

const Bar = ({ label, value, max }) => (
  <div style={{ marginBottom: 10 }}>
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#9fb6ab", marginBottom: 4 }}>
      <span>{label}</span>
      <span>{value}</span>
    </div>
    <div style={{ height: 8, background: "#102019", borderRadius: 4, overflow: "hidden" }}>
      <div style={{ width: `${max ? (value / max) * 100 : 0}%`, height: "100%", background: "#228B22" }} />
    </div>
  </div>
);

export default function PublicFrsDashboard() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ok | unavailable | error
  const [live, setLive] = useState([]);
  const esRef = useRef(null);

  const load = async () => {
    try {
      const r = await fetch(DASHBOARD_URL);
      if (r.status === 404) { setStatus("unavailable"); return; }
      if (!r.ok) { setStatus("error"); return; }
      setData(await r.json());
      setStatus("ok");
    } catch {
      setStatus("error");
    }
  };

  useEffect(() => {
    load();
    const poll = setInterval(load, 30000); // periodic refresh of aggregates
    // Realtime feed.
    try {
      const es = new EventSource(STREAM_URL);
      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data);
          setLive((prev) => [ev, ...prev].slice(0, 15));
          // A new event arrived — refresh aggregates soon.
        } catch {
          /* ignore heartbeats / non-JSON */
        }
      };
      es.onerror = () => { /* browser auto-reconnects */ };
      esRef.current = es;
    } catch {
      /* SSE unsupported — polling still updates */
    }
    return () => {
      clearInterval(poll);
      esRef.current?.close();
    };
  }, []);

  const wrap = (children) => (
    <div style={{ minHeight: "100vh", background: "#0a1410", color: "#e6f2ec", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "28px 22px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
          <div style={{ width: 10, height: 10, borderRadius: 999, background: "#228B22" }} />
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Face Recognition — Live Overview</h1>
        </div>
        {children}
      </div>
    </div>
  );

  if (status === "loading") return wrap(<p style={{ color: "#6f8c80" }}>Loading…</p>);
  if (status === "unavailable")
    return wrap(<p style={{ color: "#9fb6ab" }}>This dashboard is not available.</p>);
  if (status === "error")
    return wrap(<p style={{ color: "#d98a8a" }}>Couldn’t load the dashboard. Please try again later.</p>);

  const t = data?.totals || {};
  const maxCam = Math.max(1, ...(data?.by_camera || []).map((c) => c.count));
  const maxHour = Math.max(1, ...(data?.hourly_trend || []).map((h) => h.count));

  return wrap(
    <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: 12, marginBottom: 22 }}>
        <Stat label="Recognized today" value={t.recognized_today ?? 0} accent="#3fd07a" />
        <Stat label="Unknown today" value={t.unknown_today ?? 0} accent="#e6b800" />
        <Stat label="Events today" value={t.events_today ?? 0} />
        <Stat label="Enrolled people" value={t.enrolled_persons ?? 0} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 22 }}>
        <div style={{ background: "#0f1f1a", border: "1px solid #1f3a30", borderRadius: 10, padding: 18 }}>
          <h3 style={{ margin: "0 0 14px", fontSize: 13, textTransform: "uppercase", letterSpacing: 1, color: "#9fb6ab" }}>By camera (today)</h3>
          {(data?.by_camera || []).length
            ? data.by_camera.map((c) => <Bar key={c.camera_id} label={c.camera_id} value={c.count} max={maxCam} />)
            : <p style={{ color: "#6f8c80", fontSize: 13 }}>No activity yet.</p>}
        </div>
        <div style={{ background: "#0f1f1a", border: "1px solid #1f3a30", borderRadius: 10, padding: 18 }}>
          <h3 style={{ margin: "0 0 14px", fontSize: 13, textTransform: "uppercase", letterSpacing: 1, color: "#9fb6ab" }}>Last 24 hours</h3>
          {(data?.hourly_trend || []).length
            ? data.hourly_trend.map((h) => <Bar key={h.hour} label={h.hour} value={h.count} max={maxHour} />)
            : <p style={{ color: "#6f8c80", fontSize: 13 }}>No activity yet.</p>}
        </div>
      </div>

      {data?.show_names && (data?.top_persons || []).length > 0 && (
        <div style={{ background: "#0f1f1a", border: "1px solid #1f3a30", borderRadius: 10, padding: 18, marginBottom: 22 }}>
          <h3 style={{ margin: "0 0 14px", fontSize: 13, textTransform: "uppercase", letterSpacing: 1, color: "#9fb6ab" }}>Most seen today</h3>
          {data.top_persons.map((p, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 14, padding: "6px 0", borderBottom: "1px solid #14271f" }}>
              <span>{p.name}</span><span style={{ color: "#3fd07a" }}>{p.count}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ background: "#0f1f1a", border: "1px solid #1f3a30", borderRadius: 10, padding: 18 }}>
        <h3 style={{ margin: "0 0 14px", fontSize: 13, textTransform: "uppercase", letterSpacing: 1, color: "#9fb6ab" }}>
          Live feed <span style={{ color: "#3fd07a" }}>●</span>
        </h3>
        {live.length === 0 ? (
          <p style={{ color: "#6f8c80", fontSize: 13 }}>Waiting for new events…</p>
        ) : (
          live.map((ev, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "6px 0", borderBottom: "1px solid #14271f" }}>
              <span>
                {ev.event_type === "face_recognized" ? "✔ " : ev.event_type === "face_unknown" ? "? " : "• "}
                {data?.show_names && ev.person_name ? ev.person_name : ev.event_type?.replace(/_/g, " ")}
                <span style={{ color: "#6f8c80" }}> · {ev.camera_id || "—"}</span>
              </span>
              <span style={{ color: "#6f8c80" }}>
                {ev.triggered_at ? new Date(ev.triggered_at).toLocaleTimeString() : ""}
              </span>
            </div>
          ))
        )}
      </div>

      <p style={{ marginTop: 18, fontSize: 11, color: "#48655a", textAlign: "center" }}>
        Aggregate view · refreshed live · {data?.generated_at ? new Date(data.generated_at).toLocaleString() : ""}
      </p>
    </>
  );
}
