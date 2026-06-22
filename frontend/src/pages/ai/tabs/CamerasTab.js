// =============================================================================
// AI · Cameras tab — commercial-NVR style 40:60 split.
//   LEFT  (40%): every NVR camera as a selectable row + an assigned indicator.
//                Click a camera to load its config on the right.
//   RIGHT (60%): the selected camera's full, schema-driven config (grouped
//                sections, ROI editor). Saving creates/updates the
//                CameraAIConfig — i.e. turns the scenario ON for that camera.
// Schema comes from scenario.camera_config_schema.fields; fields may declare a
// `group` for sectioning, `help` text, and types float|int|bool|multiselect|roi.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Camera as CameraIcon,
  Save,
  AlertTriangle,
  Loader2,
  CheckCircle2,
  Power,
  Trash2,
  Search,
  VideoOff,
} from "lucide-react";
import { toast } from "sonner";
import { friendlyError } from "../../../lib/utils";

import { getAllCameras } from "../../../api/cameras";
import { BACKEND_URL } from "../../../api/client";
import {
  listScenarioCameras,
  assignCamera,
  unassignCamera,
  updateCameraConfig,
} from "../../../api/ai";

// ---------------------------------------------------------------------------
// primitives
// ---------------------------------------------------------------------------

const Toggle = ({ checked, disabled, onChange }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    disabled={disabled}
    onClick={(e) => { e.stopPropagation(); onChange(!checked); }}
    className="relative inline-flex h-[20px] w-[36px] items-center rounded-full transition-colors disabled:opacity-40 shrink-0"
    style={{ background: checked ? "var(--console-accent, #228B22)" : "var(--console-border, #333333)" }}
  >
    <span className="inline-block h-[14px] w-[14px] rounded-full bg-white transition-transform"
      style={{ transform: checked ? "translateX(19px)" : "translateX(3px)" }} />
  </button>
);

const STREAM_COLORS = {
  running: "var(--console-accent)",
  starting: "#f59e0b",
  stopped: "var(--console-muted)",
  error: "var(--console-rec)",
};

const StreamBadge = ({ state }) => {
  if (!state) return null;
  const color = STREAM_COLORS[state] || "var(--console-muted)";
  return (
    <span className="inline-flex items-center gap-1 font-telemetry text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded border"
      style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {state}
    </span>
  );
};

// Live camera snapshot via go2rtc. Falls back to a camera-off placeholder.
const CameraSnap = ({ cameraId, className }) => {
  const [bust] = React.useState(() => Date.now());
  const [ok, setOk] = React.useState(true);
  const src = cameraId
    ? `${BACKEND_URL}/go2rtc/api/frame.jpeg?src=${String(cameraId).toLowerCase()}&t=${bust}`
    : null;
  if (!src || !ok) {
    return (
      <div className={className} style={{ background: "var(--console-raised)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <VideoOff className="h-4 w-4" style={{ color: "var(--console-muted)" }} />
      </div>
    );
  }
  return <img src={src} alt="" className={className} style={{ objectFit: "cover" }} onError={() => setOk(false)} />;
};

// ---------------------------------------------------------------------------
// schema-driven field renderers
// ---------------------------------------------------------------------------

const FloatField = ({ field, value, onChange }) => {
  const v = value ?? field.default ?? field.min ?? 0;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          {field.label}
        </label>
        <span className="font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
          {Number(v).toFixed(2)}
        </span>
      </div>
      <input type="range" min={field.min ?? 0} max={field.max ?? 1} step={field.step ?? 0.01}
        value={v} onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full" style={{ accentColor: "var(--console-accent)" }} />
    </div>
  );
};

const IntField = ({ field, value, onChange }) => {
  const v = value ?? field.default ?? field.min ?? 0;
  return (
    <div className="flex items-center justify-between gap-3">
      <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        {field.label}
      </label>
      <input type="number" min={field.min} max={field.max} step={field.step ?? 1}
        value={v} onChange={(e) => onChange(parseInt(e.target.value, 10))}
        className="w-24 text-right rounded px-2 py-1 font-telemetry text-[11px] border"
        style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-text)" }} />
    </div>
  );
};

const BoolField = ({ field, value, onChange }) => {
  const v = value ?? field.default ?? false;
  return (
    <div className="flex items-center justify-between">
      <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        {field.label}
      </label>
      <Toggle checked={!!v} onChange={onChange} />
    </div>
  );
};

const StringField = ({ field, value, onChange }) => {
  const v = value ?? field.default ?? "";
  return (
    <div className="flex flex-col gap-1.5">
      <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        {field.label}
      </label>
      <input type="text" value={v} onChange={(e) => onChange(e.target.value)}
        placeholder={field.placeholder || field.default || ""}
        className="w-full rounded px-2 py-1 font-telemetry text-[11px] border"
        style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-text)" }} />
    </div>
  );
};

const MultiSelectField = ({ field, value, onChange }) => {
  const selected = value ?? field.default ?? [];
  const toggle = (opt) =>
    onChange(selected.includes(opt) ? selected.filter((o) => o !== opt) : [...selected, opt]);
  return (
    <div className="flex flex-col gap-1.5">
      <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        {field.label}
      </label>
      <div className="flex flex-wrap gap-1.5">
        {(field.options || []).map((opt) => {
          const on = selected.includes(opt);
          return (
            <button key={opt} type="button" onClick={() => toggle(opt)}
              className="font-telemetry text-[10px] uppercase tracking-wide px-2 py-1 rounded border transition-colors"
              style={{
                background: on ? "var(--console-accent, #228B22)" : "var(--console-raised, #111111)",
                borderColor: on ? "var(--console-accent, #228B22)" : "var(--console-border, #333333)",
                color: on ? "#fff" : "var(--console-muted, #888888)",
              }}>
              {opt}
            </button>
          );
        })}
      </div>
    </div>
  );
};

// ROI editor — polygon over a live go2rtc frame, normalised (0..1) points.
const RoiField = ({ field, value, onChange, cameraId }) => {
  const points = Array.isArray(value) ? value : [];
  const wrapRef = React.useRef(null);
  const [bust] = React.useState(() => Date.now());
  const [snap, setSnap] = React.useState(
    cameraId ? `${BACKEND_URL}/go2rtc/api/frame.jpeg?src=${cameraId.toLowerCase()}&t=${bust}` : null
  );
  // drag: { type: 'vertex', index } resizes one corner; { type: 'poly', ... }
  // moves the whole shape. While dragging, clicks don't add points.
  const drag = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);

  const relXY = (e) => {
    const box = wrapRef.current?.getBoundingClientRect();
    if (!box) return null;
    return [
      Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)),
      Math.min(1, Math.max(0, (e.clientY - box.top) / box.height)),
    ];
  };
  const round = (n) => Number(n.toFixed(4));

  const addPoint = (e) => {
    if (drag.current) return; // a drag just ended — don't also add a point
    const p = relXY(e);
    if (!p) return;
    onChange([...points, [round(p[0]), round(p[1])]]);
  };

  // Start dragging a vertex (resize) or the polygon body (move).
  const startVertexDrag = (e, index) => {
    e.stopPropagation();
    drag.current = { type: "vertex", index };
    setDragging(true);
  };
  const startPolyDrag = (e) => {
    e.stopPropagation();
    const p = relXY(e);
    if (!p) return;
    drag.current = { type: "poly", origin: p, base: points.map((q) => [...q]) };
    setDragging(true);
  };
  React.useEffect(() => {
    if (!dragging) return;
    const onMove = (e) => {
      const d = drag.current;
      if (!d) return;
      const p = relXY(e);
      if (!p) return;
      if (d.type === "vertex") {
        const next = points.map((q, i) => (i === d.index ? [round(p[0]), round(p[1])] : q));
        onChange(next);
      } else {
        const dx = p[0] - d.origin[0];
        const dy = p[1] - d.origin[1];
        onChange(d.base.map(([x, y]) => [
          round(Math.min(1, Math.max(0, x + dx))),
          round(Math.min(1, Math.max(0, y + dy))),
        ]));
      }
    };
    const onUp = () => {
      setDragging(false);
      // Clear the drag flag on the next tick so the trailing click is swallowed.
      setTimeout(() => { drag.current = null; }, 0);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, points, onChange]);

  const undo = () => onChange(points.slice(0, -1));
  const clear = () => onChange([]);
  const poly = points.map((p) => `${p[0] * 100},${p[1] * 100}`).join(" ");
  const closed = points.length > 2;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-end">
        <div className="flex items-center gap-2">
          <button type="button" onClick={undo} disabled={!points.length}
            className="font-telemetry text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border disabled:opacity-40"
            style={{ borderColor: "var(--console-border)", color: "var(--console-muted)", background: "var(--console-raised)" }}>
            Undo
          </button>
          <button type="button" onClick={clear} disabled={!points.length}
            className="font-telemetry text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border disabled:opacity-40"
            style={{ borderColor: "var(--console-border)", color: "var(--console-rec)", background: "var(--console-raised)" }}>
            Clear
          </button>
        </div>
      </div>
      <div ref={wrapRef} onClick={addPoint}
        className="relative w-full rounded border overflow-hidden"
        style={{ borderColor: "var(--console-border)", background: "#000", aspectRatio: "16 / 9",
          cursor: dragging ? "grabbing" : "crosshair" }}>
        {snap && (
          <img src={snap} alt="" className="absolute inset-0 w-full h-full object-contain pointer-events-none"
            onError={() => setSnap(null)} />
        )}
        <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          {points.length > 1 && (
            <polygon points={poly} fill="rgba(45,212,191,0.18)" stroke="var(--console-accent)" strokeWidth="0.4"
              style={{ cursor: closed ? "grab" : "default", pointerEvents: closed ? "auto" : "none" }}
              onMouseDown={closed ? startPolyDrag : undefined} />
          )}
          {points.map((p, i) => (
            <g key={i}>
              {/* large invisible hit-target so the small handle is easy to grab */}
              <circle cx={p[0] * 100} cy={p[1] * 100} r="2.6" fill="transparent"
                style={{ cursor: "grab", pointerEvents: "auto" }}
                onMouseDown={(e) => startVertexDrag(e, i)} />
              <circle cx={p[0] * 100} cy={p[1] * 100} r="1.1" fill="var(--console-accent)"
                stroke="#fff" strokeWidth="0.3" style={{ pointerEvents: "none" }} />
            </g>
          ))}
        </svg>
        {!points.length && (
          <div className="absolute inset-0 flex items-center justify-center font-telemetry text-[10px] uppercase tracking-widest pointer-events-none"
            style={{ color: "var(--console-muted)" }}>
            Click to add ROI points
          </div>
        )}
      </div>
      <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
        {points.length} point{points.length === 1 ? "" : "s"} — click to add · drag a corner to resize · drag inside to move · empty = whole frame
      </span>
    </div>
  );
};

// Line editor — a 2-point tripwire over a live frame, normalised (0..1) points.
// Used for ANPR direction / speed-calibration lines.
const LineField = ({ field, value, onChange, cameraId }) => {
  const points = Array.isArray(value) ? value.slice(0, 2) : [];
  const wrapRef = React.useRef(null);
  const [bust] = React.useState(() => Date.now());
  const [snap, setSnap] = React.useState(
    cameraId ? `${BACKEND_URL}/go2rtc/api/frame.jpeg?src=${cameraId.toLowerCase()}&t=${bust}` : null
  );

  const addPoint = (e) => {
    if (points.length >= 2) return; // a line has exactly two endpoints
    const box = wrapRef.current?.getBoundingClientRect();
    if (!box) return;
    const x = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
    const y = Math.min(1, Math.max(0, (e.clientY - box.top) / box.height));
    onChange([...points, [Number(x.toFixed(4)), Number(y.toFixed(4))]]);
  };
  const clear = () => onChange([]);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          {field.label}
        </label>
        <button type="button" onClick={clear} disabled={!points.length}
          className="font-telemetry text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border disabled:opacity-40"
          style={{ borderColor: "var(--console-border)", color: "var(--console-rec)", background: "var(--console-raised)" }}>
          Clear
        </button>
      </div>
      <div ref={wrapRef} onClick={addPoint}
        className="relative w-full rounded border overflow-hidden cursor-crosshair"
        style={{ borderColor: "var(--console-border)", background: "#000", aspectRatio: "16 / 9" }}>
        {snap && (
          <img src={snap} alt="" className="absolute inset-0 w-full h-full object-contain pointer-events-none"
            onError={() => setSnap(null)} />
        )}
        <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none">
          {points.length === 2 && (
            <line x1={points[0][0] * 100} y1={points[0][1] * 100} x2={points[1][0] * 100} y2={points[1][1] * 100}
              stroke="var(--console-accent)" strokeWidth="0.6" />
          )}
          {points.map((p, i) => (
            <circle key={i} cx={p[0] * 100} cy={p[1] * 100} r="0.9" fill="var(--console-accent)" />
          ))}
        </svg>
        {!points.length && (
          <div className="absolute inset-0 flex items-center justify-center font-telemetry text-[10px] uppercase tracking-widest pointer-events-none"
            style={{ color: "var(--console-muted)" }}>
            Click two points to set the line
          </div>
        )}
      </div>
      <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
        {points.length}/2 points — empty = no line
      </span>
    </div>
  );
};

const FieldRenderer = ({ field, value, onChange, cameraId }) => {
  switch (field.type) {
    case "float": return <FloatField field={field} value={value} onChange={onChange} />;
    case "int": return <IntField field={field} value={value} onChange={onChange} />;
    case "bool": return <BoolField field={field} value={value} onChange={onChange} />;
    case "string": return <StringField field={field} value={value} onChange={onChange} />;
    case "multiselect": return <MultiSelectField field={field} value={value} onChange={onChange} />;
    case "roi": return <RoiField field={field} value={value} onChange={onChange} cameraId={cameraId} />;
    case "line": return <LineField field={field} value={value} onChange={onChange} cameraId={cameraId} />;
    default: return null;
  }
};

const Field = ({ field, value, onChange, cameraId }) => (
  <div className="flex flex-col gap-1">
    <FieldRenderer field={field} value={value} onChange={onChange} cameraId={cameraId} />
    {field.help && (
      <p className="font-telemetry text-[10px] leading-snug" style={{ color: "var(--console-muted)", opacity: 0.7 }}>
        {field.help}
      </p>
    )}
  </div>
);

// ---------------------------------------------------------------------------
// RIGHT — full config panel for the selected camera
// ---------------------------------------------------------------------------

const ConfigPanel = ({ camera, config, scenario, scenarioId, qc }) => {
  const fields = scenario?.camera_config_schema?.fields || [];
  const isFrs = (scenario?.slug || "frs") === "frs";
  const assigned = !!config;
  const [draft, setDraft] = useState(() => ({ ...(config?.config || {}) }));

  useEffect(() => {
    const c = { ...(config?.config || {}) };
    fields.forEach((field) => {
      if (c[field.key] === undefined && field.default !== undefined) {
        c[field.key] = field.default;
      }
    });
    // FRS has two mutually exclusive modes. Other scenarios should use their
    // manifest defaults without inheriting face-recognition config keys.
    if (isFrs && c.recognition_enabled === undefined && c.detection_enabled === undefined) {
      c.recognition_enabled = true;
      c.detection_enabled = false;
    }
    setDraft(c);
  }, [config?.id, camera?.id, fields, isFrs]);  // reload when selection / config changes

  // Recognition and detection-only are mutually exclusive modes — exactly one
  // must be active. Toggling one ON forces the other OFF; turning the active one
  // OFF flips to the other (never lets both end up off).
  const setField = (key, val) =>
    setDraft((d) => {
      const next = { ...d, [key]: val };
      if (isFrs && key === "recognition_enabled") {
        next.detection_enabled = !val;
      } else if (isFrs && key === "detection_enabled") {
        next.recognition_enabled = !val;
      }
      return next;
    });

  // Split ROI (goes to the visual right column) from scalar settings (left).
  const roiFields = useMemo(() => fields.filter((f) => f.type === "roi"), [fields]);

  // Group the non-ROI settings by `group` (insertion order preserved).
  const groups = useMemo(() => {
    const out = [];
    const idx = {};
    for (const f of fields) {
      if (f.type === "roi") continue;
      const g = f.group || "General";
      if (!(g in idx)) { idx[g] = out.length; out.push([g, []]); }
      out[idx[g]][1].push(f);
    }
    return out;
  }, [fields]);

  const enableMut = useMutation({
    mutationFn: () => assignCamera(scenarioId, { camera_id: camera.id, enabled: true, config: draft }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scenario-cameras", scenarioId] }); toast.success("Scenario enabled on camera"); },
    onError: (e) => {
      if (e?.response?.status === 403) toast.error("Camera limit reached for this scenario");
      else toast.error(friendlyError(e, "Couldn't enable the scenario on this camera"));
    },
  });
  const saveMut = useMutation({
    mutationFn: () => updateCameraConfig(config.id, { config: draft }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scenario-cameras", scenarioId] }); toast.success("Config saved"); },
    onError: (e) => toast.error(friendlyError(e, "Failed to save")),
  });
  const toggleMut = useMutation({
    mutationFn: (en) => updateCameraConfig(config.id, { enabled: en }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scenario-cameras", scenarioId] }),
  });
  const removeMut = useMutation({
    mutationFn: () => unassignCamera(config.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scenario-cameras", scenarioId] }); toast.success("Camera removed from scenario"); },
  });

  const pending = enableMut.isPending || saveMut.isPending;
  // Dirty = draft differs from the saved config (only meaningful once assigned).
  const dirty = useMemo(
    () => assigned && JSON.stringify(draft) !== JSON.stringify(config?.config || {}),
    [assigned, draft, config]
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 mb-3" style={{ borderBottom: "1px solid var(--console-border)" }}>
        <div className="flex items-center gap-3 min-w-0">
          <CameraSnap cameraId={camera.id} className="h-12 w-20 rounded shrink-0" />
          <div className="min-w-0">
            <div className="font-telemetry text-[13px] font-semibold uppercase tracking-wide truncate" style={{ color: "var(--console-text)" }}>
              {camera.name || camera.id}
            </div>
            <div className="flex items-center gap-2 mt-0.5">
              {assigned ? <StreamBadge state={config.enabled ? (config.stream_state === "running" || config.stream_state === "error" ? config.stream_state : "starting") : "stopped"} /> : (
                <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  Not assigned
                </span>
              )}
              {dirty && (
                <span className="font-telemetry text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded"
                  style={{ background: "rgba(245,158,11,0.15)", color: "#f59e0b" }}>
                  Unsaved
                </span>
              )}
            </div>
          </div>
        </div>
        {assigned && (
          <div className="flex items-center gap-3 shrink-0">
            <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>Active</span>
            <Toggle checked={config.enabled} disabled={toggleMut.isPending} onChange={(v) => toggleMut.mutate(v)} />
            <button type="button" onClick={() => removeMut.mutate()} disabled={removeMut.isPending}
              className="p-1.5 rounded border" style={{ borderColor: "var(--console-border)", color: "var(--console-rec)", background: "var(--console-raised)" }}>
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {assigned && config.last_error && (
        <div className="flex items-start gap-1.5 mb-3 rounded p-2 text-[11px]"
          style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", color: "var(--console-rec)" }}>
          <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span className="break-all font-telemetry">{config.last_error}</span>
        </div>
      )}

      {/* Two-column body: settings (left, scrollable) + ROI/preview (right). */}
      <div className="flex-1 min-h-0 flex gap-4">
        {/* LEFT — scalar settings, grouped + scrollable */}
        <div className="flex-1 min-w-0 flex flex-col min-h-0">
          <div className="relative flex-1 min-h-0">
            <div className="absolute inset-0 overflow-y-auto pr-2 flex flex-col gap-5">
              {groups.map(([group, gfields]) => (
                <div key={group} className="flex flex-col gap-3">
                  <div className="font-telemetry text-[10px] font-semibold uppercase tracking-widest" style={{ color: "var(--console-accent)" }}>
                    {group}
                  </div>
                  {gfields.map((f) => (
                    <Field key={f.key} field={f} value={draft[f.key]} onChange={(v) => setField(f.key, v)} cameraId={camera.id} />
                  ))}
                </div>
              ))}
              <div className="h-1" />
            </div>
            {/* bottom fade — signals more content below the fold */}
            <div className="pointer-events-none absolute bottom-0 left-0 right-2 h-6"
              style={{ background: "linear-gradient(to top, var(--console-panel), transparent)" }} />
          </div>
        </div>

        {/* RIGHT — ROI editor (or a live preview when the scenario has no ROI) */}
        <div className="w-[42%] shrink-0 flex flex-col min-h-0 rounded-lg border overflow-hidden"
          style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}>
          <div className="px-3 py-2 font-telemetry text-[10px] font-semibold uppercase tracking-widest shrink-0"
            style={{ color: "var(--console-accent)", borderBottom: "1px solid var(--console-border)" }}>
            {roiFields.length ? "Region of interest" : "Live preview"}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto p-3 flex flex-col gap-3">
            {roiFields.length ? (
              roiFields.map((f) => (
                <Field key={f.key} field={f} value={draft[f.key]} onChange={(v) => setField(f.key, v)} cameraId={camera.id} />
              ))
            ) : (
              <CameraSnap cameraId={camera.id} className="w-full aspect-video rounded" />
            )}
          </div>
        </div>
      </div>

      {/* Footer action */}
      <div className="flex items-center justify-between pt-3 mt-3" style={{ borderTop: "1px solid var(--console-border)" }}>
        <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          {assigned ? (dirty ? "Unsaved changes" : "All changes saved") : "Enable to start analysing"}
        </span>
        <button type="button" disabled={pending || (assigned && !dirty)}
          onClick={() => (assigned ? saveMut.mutate() : enableMut.mutate())}
          className="inline-flex items-center gap-1.5 font-telemetry text-[11px] uppercase tracking-widest px-4 py-2 rounded transition-opacity disabled:opacity-50"
          style={{ background: "var(--console-accent)", color: "#06231f" }}>
          {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : assigned ? <Save className="h-3.5 w-3.5" /> : <Power className="h-3.5 w-3.5" />}
          {assigned ? "Save config" : "Enable scenario"}
        </button>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// main — 40:60 split
// ---------------------------------------------------------------------------

const FILTERS = [
  { key: "all", label: "All" },
  { key: "assigned", label: "Assigned" },
  { key: "unassigned", label: "Free" },
];

const CamerasTab = ({ scenario }) => {
  const scenarioId = scenario?.id;
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");

  const { data: cameras = [], isLoading: camsLoading } = useQuery({
    queryKey: ["all-cameras"],
    queryFn: getAllCameras,
  });
  const { data: configs = [] } = useQuery({
    queryKey: ["scenario-cameras", scenarioId],
    queryFn: () => listScenarioCameras(scenarioId),
    enabled: !!scenarioId,
    // Poll so the worker's stream_state (stopped → running) reflects without a
    // manual refresh after enabling a camera.
    refetchInterval: 8000,
  });

  const camList = useMemo(
    () => (Array.isArray(cameras) ? cameras : cameras?.items || cameras?.cameras || []),
    [cameras]
  );
  const configByCam = useMemo(() => {
    const m = {};
    for (const c of configs) m[c.camera_id] = c;
    return m;
  }, [configs]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return camList.filter((cam) => {
      const cfg = configByCam[cam.id];
      if (filter === "assigned" && !cfg) return false;
      if (filter === "unassigned" && cfg) return false;
      if (q && !`${cam.name || ""} ${cam.id}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [camList, configByCam, search, filter]);

  // default selection = first visible camera
  useEffect(() => {
    if ((!selectedId || !filtered.some((c) => c.id === selectedId)) && filtered.length) {
      setSelectedId(filtered[0].id);
    }
  }, [filtered, selectedId]);

  const assignedCount = configs.filter((c) => c.enabled !== false).length;
  const cap = scenario?.camera_limit || 0;
  const capFrac = cap > 0 ? Math.min(1, assignedCount / cap) : 0;
  const selectedCam = camList.find((c) => c.id === selectedId) || null;

  return (
    <div className="flex gap-4 h-[calc(100vh-220px)] min-h-[480px]">
      {/* LEFT — camera list */}
      <div className="w-[300px] shrink-0 flex flex-col rounded-lg border overflow-hidden"
        style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
        {/* header + capacity meter */}
        <div className="px-3 pt-2.5 pb-2 flex flex-col gap-2" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <div className="flex items-center justify-between">
            <span className="font-telemetry text-[10px] uppercase tracking-widest flex items-center gap-1.5" style={{ color: "var(--console-muted)" }}>
              <CheckCircle2 className="h-3.5 w-3.5" style={{ color: "var(--console-accent)" }} /> Cameras
            </span>
            <span className="font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
              {assignedCount}{cap > 0 ? ` / ${cap}` : ""} <span style={{ color: "var(--console-muted)" }}>assigned</span>
            </span>
          </div>
          {cap > 0 && (
            <div className="h-1 rounded-full overflow-hidden" style={{ background: "var(--console-raised)" }}>
              <div className="h-full rounded-full transition-all" style={{ width: `${capFrac * 100}%`, background: capFrac >= 1 ? "var(--console-rec)" : "var(--console-accent)" }} />
            </div>
          )}
          {/* search */}
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search cameras"
              className="w-full rounded pl-7 pr-2 py-1.5 font-telemetry text-[11px] outline-none"
              style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)", color: "var(--console-text)" }} />
          </div>
          {/* filter chips */}
          <div className="flex items-center gap-1.5">
            {FILTERS.map((f) => {
              const on = filter === f.key;
              return (
                <button key={f.key} type="button" onClick={() => setFilter(f.key)}
                  className="font-telemetry text-[9px] uppercase tracking-widest px-2 py-1 rounded border transition-colors"
                  style={{
                    background: on ? "var(--console-accent)" : "var(--console-raised)",
                    borderColor: on ? "var(--console-accent)" : "var(--console-border)",
                    color: on ? "#06231f" : "var(--console-muted)",
                  }}>
                  {f.label}
                </button>
              );
            })}
          </div>
        </div>
        {/* list */}
        <div className="flex-1 overflow-y-auto">
          {camsLoading ? (
            <div className="p-4 font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>Loading…</div>
          ) : filtered.length === 0 ? (
            <div className="p-4 font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
              {camList.length === 0 ? "No cameras. Add one in the Cameras page." : "No cameras match."}
            </div>
          ) : filtered.map((cam) => {
            const cfg = configByCam[cam.id];
            const active = selectedId === cam.id;
            // Enabled but worker not yet reporting "running" → "starting" (amber),
            // not a confusing "stopped".
            let statusLabel = "not assigned";
            let statusColor = "var(--console-muted)";
            if (cfg) {
              if (!cfg.enabled) {
                statusLabel = "disabled";
              } else if (cfg.stream_state === "running") {
                statusLabel = "running"; statusColor = STREAM_COLORS.running;
              } else if (cfg.stream_state === "error") {
                statusLabel = "error"; statusColor = STREAM_COLORS.error;
              } else {
                statusLabel = "starting"; statusColor = "#f59e0b";
              }
            }
            return (
              <button key={cam.id} type="button" onClick={() => setSelectedId(cam.id)}
                className="w-full flex items-center gap-2.5 px-2.5 py-2 text-left transition-colors hover:brightness-110"
                style={{
                  background: active ? "var(--console-raised)" : "transparent",
                  borderBottom: "1px solid var(--console-border)",
                  borderLeft: active ? "2px solid var(--console-accent)" : "2px solid transparent",
                }}>
                <CameraSnap cameraId={cam.id} className="h-10 w-14 rounded shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="font-telemetry text-[12px] truncate" style={{ color: "var(--console-text)" }}>{cam.name || cam.id}</div>
                  <div className="font-telemetry text-[9px] uppercase tracking-widest flex items-center gap-1" style={{ color: "var(--console-muted)" }}>
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: statusColor }} />
                    {statusLabel}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* RIGHT — config */}
      <div className="flex-1 rounded-lg border p-4 overflow-hidden"
        style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
        {selectedCam ? (
          <ConfigPanel
            key={selectedCam.id}
            camera={selectedCam}
            config={configByCam[selectedCam.id] || null}
            scenario={scenario}
            scenarioId={scenarioId}
            qc={qc}
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center gap-2" style={{ color: "var(--console-muted)" }}>
            <CameraIcon className="h-7 w-7" />
            <span className="font-telemetry text-[11px] uppercase tracking-widest">Select a camera</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default CamerasTab;
