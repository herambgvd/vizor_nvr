// =============================================================================
// SchemaForm — render per-scenario camera config from camera_config_schema
// =============================================================================
// Field types:
//   toggle           — Switch
//   number           — number input with min/max
//   slider           — range slider 0-1 or min-max
//   select           — single select with options[]
//   multi_checkbox   — list of checkboxes
//   roi_polygon      — single or multi polygon via ROICanvas
//   zones_panel      — embedded ZonesPanel (people counting)
//   group_multiselect — FRS group picker (Phase 3 — stub for now)
//
// Adding a new field type = case in renderField + Pydantic accepts.
// =============================================================================

import React from "react";
import { Switch } from "../ui/switch";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Badge } from "../ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import ROICanvas from "./ROICanvas";
import ZonesPanel from "./ZonesPanel";
import { cn } from "../../lib/utils";

const SchemaForm = ({ schema, value, onChange, cameraId }) => {
  const fields = schema?.fields || [];

  const setField = (key, v) =>
    onChange?.({ ...(value || {}), [key]: v });

  const renderField = (f) => {
    const current = value?.[f.key] ?? f.default;

    switch (f.type) {
      case "toggle":
        return (
          <div className="flex items-center justify-between gap-3">
            <div>
              <Label>{f.label}</Label>
              {f.help && (
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  {f.help}
                </p>
              )}
            </div>
            <Switch
              checked={current === true}
              onCheckedChange={(v) => setField(f.key, v)}
            />
          </div>
        );

      case "number":
        return (
          <div>
            <Label>{f.label}</Label>
            <Input
              type="number"
              min={f.min}
              max={f.max}
              step={f.step || 1}
              value={current ?? ""}
              onChange={(e) => setField(f.key, Number(e.target.value))}
              className="mt-1"
            />
          </div>
        );

      case "slider":
        return (
          <div>
            <div className="flex items-center justify-between mb-1">
              <Label>{f.label}</Label>
              <span className="text-xs font-mono text-muted-foreground">
                {Number(current ?? f.default ?? 0).toFixed(2)}
              </span>
            </div>
            <input
              type="range"
              min={f.min ?? 0}
              max={f.max ?? 1}
              step={f.step ?? 0.01}
              value={current ?? f.default ?? 0}
              onChange={(e) => setField(f.key, Number(e.target.value))}
              className="w-full accent-teal-400"
            />
            <div className="flex items-center justify-between text-[10px] text-muted-foreground font-mono">
              <span>{f.min ?? 0}</span>
              <span>{f.max ?? 1}</span>
            </div>
          </div>
        );

      case "select":
        return (
          <div>
            <Label>{f.label}</Label>
            <Select
              value={current ?? ""}
              onValueChange={(v) => setField(f.key, v)}
            >
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(f.options || []).map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );

      case "multi_checkbox": {
        const list = Array.isArray(current) ? current : [];
        const toggle = (val) => {
          const next = list.includes(val)
            ? list.filter((x) => x !== val)
            : [...list, val];
          setField(f.key, next);
        };
        return (
          <div>
            <Label>{f.label}</Label>
            <div className="mt-1.5 flex flex-wrap gap-2">
              {(f.options || []).map((opt) => {
                const active = list.includes(opt.value);
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggle(opt.value)}
                    className={cn(
                      "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-xs font-medium transition-colors",
                      active
                        ? "bg-teal-500/15 text-teal-300 border-teal-500/40"
                        : "bg-card/40 text-muted-foreground border-border hover:text-white",
                    )}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>
        );
      }

      case "roi_polygon": {
        // Phase 2 supports single ROI. Multi-ROI editing UI in Phase 3.
        const rois = Array.isArray(current) ? current : [];
        const first = rois[0] || null;
        return (
          <div>
            <Label>{f.label}</Label>
            <p className="text-[11px] text-muted-foreground mb-2">
              Optional. Empty = whole frame.
            </p>
            <ROICanvas
              cameraId={cameraId}
              mode="polygon"
              value={first ? { kind: "polygon", points: first.points || first } : null}
              onChange={(g) => {
                if (!g?.points?.length) {
                  setField(f.key, []);
                } else {
                  setField(f.key, [{ points: g.points }]);
                }
              }}
            />
          </div>
        );
      }

      case "zones_panel":
        return (
          <div>
            <Label>{f.label}</Label>
            <div className="mt-2">
              <ZonesPanel cameraId={cameraId} />
            </div>
          </div>
        );

      case "group_multiselect":
        return (
          <div>
            <Label>{f.label}</Label>
            <p className="text-[11px] text-muted-foreground mt-1">
              Group picker — wired in FRS phase.
            </p>
          </div>
        );

      default:
        return (
          <div className="text-[11px] text-muted-foreground">
            Unknown field type: {f.type}
          </div>
        );
    }
  };

  if (!fields.length) {
    return (
      <p className="text-xs text-muted-foreground py-4">
        This scenario has no per-camera config.
      </p>
    );
  }

  return (
    <div className="space-y-5">
      {fields.map((f) => (
        <div key={f.key}>{renderField(f)}</div>
      ))}
    </div>
  );
};

export default SchemaForm;
