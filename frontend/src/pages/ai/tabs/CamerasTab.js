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
} from "lucide-react";
import { toast } from "sonner";

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
    style={{ background: checked ? "var(--console-accent)" : "var(--console-border)" }}
  >
    <span className="inline-block h-[14px] w-[14px] rounded-full bg-white transition-transform"
      style={{ transform: checked ? "translateX(19px)" : "translateX(3px)" }} />
  </button>
);

const STREAM_COLORS = {
  running: "var(--console-accent)",
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
                background: on ? "var(--console-accent)" : "var(--console-raised)",
                borderColor: on ? "var(--console-accent)" : "var(--console-border)",
                color: on ? "#fff" : "var(--console-muted)",
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

  const addPoint = (e) => {
    const box = wrapRef.current?.getBoundingClientRect();
    if (!box) return;
    const x = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
    const y = Math.min(1, Math.max(0, (e.clientY - box.top) / box.height));
    onChange([...points, [Number(x.toFixed(4)), Number(y.toFixed(4))]]);
  };
  const undo = () => onChange(points.slice(0, -1));
  const clear = () => onChange([]);
  const poly = points.map((p) => `${p[0] * 100},${p[1] * 100}`).join(" ");

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          {field.label}
        </label>
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
        className="relative w-full rounded border overflow-hidden cursor-crosshair"
        style={{ borderColor: "var(--console-border)", background: "#000", aspectRatio: "16 / 9" }}>
        {snap && (
          <img src={snap} alt="" className="absolute inset-0 w-full h-full object-contain pointer-events-none"
            onError={() => setSnap(null)} />
        )}
        <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none">
          {points.length > 1 && (
            <polygon points={poly} fill="rgba(45,212,191,0.18)" stroke="var(--console-accent)" strokeWidth="0.4" />
          )}
          {points.map((p, i) => (
            <circle key={i} cx={p[0] * 100} cy={p[1] * 100} r="0.9" fill="var(--console-accent)" />
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
        {points.length} point{points.length === 1 ? "" : "s"} — empty = whole frame
      </span>
    </div>
  );
};

const FieldRenderer = ({ field, value, onChange, cameraId }) => {
  switch (field.type) {
    case "float": return <FloatField field={field} value={value} onChange={onChange} />;
    case "int": return <IntField field={field} value={value} onChange={onChange} />;
    case "bool": return <BoolField field={field} value={value} onChange={onChange} />;
    case "multiselect": return <MultiSelectField field={field} value={value} onChange={onChange} />;
    case "roi": return <RoiField field={field} value={value} onChange={onChange} cameraId={cameraId} />;
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
  const assigned = !!config;
  const [draft, setDraft] = useState(() => ({ ...(config?.config || {}) }));

  useEffect(() => {
    setDraft({ ...(config?.config || {}) });
  }, [config?.id, camera?.id]);  // reload when selection / config changes

  const setField = (key, val) => setDraft((d) => ({ ...d, [key]: val }));

  // Group fields by `group` (insertion order preserved).
  const groups = useMemo(() => {
    const out = [];
    const idx = {};
    for (const f of fields) {
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
      const d = e?.response?.data?.detail || "";
      if (e?.response?.status === 403) toast.error(d || "Camera limit reached");
      else toast.error(d || "Failed to enable");
    },
  });
  const saveMut = useMutation({
    mutationFn: () => updateCameraConfig(config.id, { config: draft }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scenario-cameras", scenarioId] }); toast.success("Config saved"); },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to save"),
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

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between pb-3 mb-3" style={{ borderBottom: "1px solid var(--console-border)" }}>
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="h-9 w-9 rounded flex items-center justify-center shrink-0" style={{ background: "var(--console-raised)" }}>
            <CameraIcon className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
          </div>
          <div className="min-w-0">
            <div className="font-telemetry text-[13px] font-semibold uppercase tracking-wide truncate" style={{ color: "var(--console-text)" }}>
              {camera.name || camera.id}
            </div>
            <div className="flex items-center gap-2">
              {assigned ? <StreamBadge state={config.stream_state || "stopped"} /> : (
                <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  Not assigned
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

      {/* Grouped config */}
      <div className="flex-1 overflow-y-auto pr-1 flex flex-col gap-5">
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
      </div>

      {/* Footer action */}
      <div className="flex justify-end pt-3 mt-3" style={{ borderTop: "1px solid var(--console-border)" }}>
        <button type="button" disabled={pending}
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

const CamerasTab = ({ scenario }) => {
  const scenarioId = scenario?.id;
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState(null);

  const { data: cameras = [], isLoading: camsLoading } = useQuery({
    queryKey: ["all-cameras"],
    queryFn: getAllCameras,
  });
  const { data: configs = [] } = useQuery({
    queryKey: ["scenario-cameras", scenarioId],
    queryFn: () => listScenarioCameras(scenarioId),
    enabled: !!scenarioId,
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

  // default selection = first camera
  useEffect(() => {
    if (!selectedId && camList.length) setSelectedId(camList[0].id);
  }, [camList, selectedId]);

  const assignedCount = configs.filter((c) => c.enabled !== false).length;
  const cap = scenario?.camera_limit || 0;
  const selectedCam = camList.find((c) => c.id === selectedId) || null;

  return (
    <div className="flex gap-4 h-[calc(100vh-220px)] min-h-[480px]">
      {/* LEFT 25% — camera list */}
      <div className="w-1/4 flex flex-col rounded border overflow-hidden"
        style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
        <div className="flex items-center justify-between px-3 py-2.5" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <span className="font-telemetry text-[10px] uppercase tracking-widest flex items-center gap-1.5" style={{ color: "var(--console-muted)" }}>
            <CheckCircle2 className="h-3.5 w-3.5" style={{ color: "var(--console-accent)" }} /> Cameras
          </span>
          <span className="font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
            {assignedCount}{cap > 0 ? ` / ${cap}` : ""}
          </span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {camsLoading ? (
            <div className="p-4 font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>Loading…</div>
          ) : camList.length === 0 ? (
            <div className="p-4 font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>No cameras. Add one in the Cameras page.</div>
          ) : camList.map((cam) => {
            const cfg = configByCam[cam.id];
            const active = selectedId === cam.id;
            return (
              <button key={cam.id} type="button" onClick={() => setSelectedId(cam.id)}
                className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors"
                style={{
                  background: active ? "var(--console-raised)" : "transparent",
                  borderBottom: "1px solid var(--console-border)",
                  borderLeft: active ? "2px solid var(--console-accent)" : "2px solid transparent",
                }}>
                <CameraIcon className="h-4 w-4 shrink-0" style={{ color: cfg?.enabled ? "var(--console-accent)" : "var(--console-muted)" }} />
                <div className="min-w-0 flex-1">
                  <div className="font-telemetry text-[12px] truncate" style={{ color: "var(--console-text)" }}>{cam.name || cam.id}</div>
                  <div className="font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                    {cfg ? (cfg.enabled ? (cfg.stream_state || "stopped") : "disabled") : "not assigned"}
                  </div>
                </div>
                {cfg?.enabled && <span className="h-2 w-2 rounded-full shrink-0" style={{ background: "var(--console-accent)" }} />}
              </button>
            );
          })}
        </div>
      </div>

      {/* RIGHT 75% — config */}
      <div className="w-3/4 rounded border p-4 overflow-hidden"
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
          <div className="h-full flex items-center justify-center font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Select a camera
          </div>
        )}
      </div>
    </div>
  );
};

export default CamerasTab;
