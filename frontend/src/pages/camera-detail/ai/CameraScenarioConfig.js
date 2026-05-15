// =============================================================================
// CameraScenarioConfig — /cameras/:id/ai/:slug
// =============================================================================
// Schema-driven per-scenario per-camera form. Renders fields from
// scenario.camera_config_schema via SchemaForm. Persists to
// camera_ai_configs through PUT /api/ai/cameras/:id/scenarios/:slug.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
import { useParams, useOutletContext } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, Save, Power, PowerOff, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import apiClient from "../../../api/client";
import { Button } from "../../../components/ui/button";
import { Badge } from "../../../components/ui/badge";
import SchemaForm from "../../../components/nvr/SchemaForm";

const upsertConfig = ({ cameraId, slug, body }) =>
  apiClient
    .put(`/ai/cameras/${cameraId}/scenarios/${slug}`, body)
    .then((r) => r.data);

const disableConfig = ({ cameraId, slug }) =>
  apiClient.delete(`/ai/cameras/${cameraId}/scenarios/${slug}`);

// Strip the toggle field from schema — handled by the dedicated
// Enable/Disable header button instead of an inline field.
const filterEnabledField = (schema) => {
  if (!schema?.fields) return schema;
  return {
    ...schema,
    fields: schema.fields.filter((f) => f.key !== "enabled"),
  };
};

// Build a defaults object from schema fields so the form starts coherent.
const defaultsFromSchema = (schema) => {
  const obj = {};
  (schema?.fields || []).forEach((f) => {
    if (f.default !== undefined) obj[f.key] = f.default;
    else if (f.type === "multi_checkbox" || f.type === "roi_polygon") obj[f.key] = [];
    else if (f.type === "toggle") obj[f.key] = false;
  });
  return obj;
};

const CameraScenarioConfig = () => {
  const { slug } = useParams();
  const { cameraId, scenarios, cameraConfigs } = useOutletContext();
  const qc = useQueryClient();

  const scenario = useMemo(
    () => scenarios.find((s) => s.slug === slug),
    [scenarios, slug],
  );
  const existing = useMemo(
    () => cameraConfigs.find((c) => c.scenario_slug === slug),
    [cameraConfigs, slug],
  );

  const filteredSchema = useMemo(
    () => filterEnabledField(scenario?.camera_config_schema),
    [scenario],
  );

  const initialConfig = useMemo(() => {
    const fromExisting = existing?.config || {};
    const fromDefaults = {
      ...defaultsFromSchema(scenario?.camera_config_schema),
      ...(scenario?.default_config || {}),
    };
    return { ...fromDefaults, ...fromExisting };
  }, [existing, scenario]);

  const [enabled, setEnabled] = useState(!!existing?.enabled);
  const [config, setConfig] = useState(initialConfig);

  useEffect(() => {
    setEnabled(!!existing?.enabled);
    setConfig(initialConfig);
  }, [existing, initialConfig]);

  const saveMut = useMutation({
    mutationFn: ({ body }) => upsertConfig({ cameraId, slug, body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["camera-ai-configs", cameraId] });
      toast.success("Scenario saved");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Save failed"),
  });

  const disableMut = useMutation({
    mutationFn: () => disableConfig({ cameraId, slug }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["camera-ai-configs", cameraId] });
      toast.success("Scenario disabled");
      setEnabled(false);
    },
  });

  const handleSave = () => {
    saveMut.mutate({ body: { enabled, config } });
  };

  const handleResetDefaults = () => {
    setConfig({
      ...defaultsFromSchema(scenario?.camera_config_schema),
      ...(scenario?.default_config || {}),
    });
    toast.success("Reset to defaults — click Save to apply");
  };

  if (!scenario) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Scenario not found.
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 max-w-3xl space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Sparkles className="h-5 w-5 text-teal-300 shrink-0" />
            <h2 className="text-lg font-semibold truncate">{scenario.name}</h2>
            <Badge variant="outline" className="text-[10px]">
              {scenario.tier}
            </Badge>
            <Badge
              variant="outline"
              className={
                enabled
                  ? "text-[10px] bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                  : "text-[10px]"
              }
            >
              {enabled ? "Enabled" : "Disabled"}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground mt-1.5 max-w-2xl">
            {scenario.description}
          </p>
        </div>
        <Button
          variant={enabled ? "destructive" : "default"}
          size="sm"
          onClick={() => {
            if (enabled && existing) {
              disableMut.mutate();
            } else {
              setEnabled(true);
            }
          }}
          disabled={disableMut.isPending}
        >
          {enabled ? (
            <>
              <PowerOff className="h-4 w-4 mr-1" /> Disable
            </>
          ) : (
            <>
              <Power className="h-4 w-4 mr-1" /> Enable
            </>
          )}
        </Button>
      </div>

      {/* Schema-driven form */}
      <div className="rounded-lg border border-border bg-card/40 p-4 md:p-5">
        <SchemaForm
          schema={filteredSchema}
          value={config}
          onChange={setConfig}
          cameraId={cameraId}
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2">
        <Button onClick={handleSave} disabled={saveMut.isPending} size="sm">
          <Save className="h-4 w-4 mr-1" />
          {saveMut.isPending ? "Saving…" : "Save"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleResetDefaults}
          disabled={saveMut.isPending}
        >
          <RotateCcw className="h-4 w-4 mr-1" />
          Reset to defaults
        </Button>
      </div>

      {scenario.requires_models?.length > 0 && (
        <div className="text-[11px] text-muted-foreground border-t border-white/5 pt-3">
          <span className="uppercase tracking-wider mr-2">
            Requires models:
          </span>
          {scenario.requires_models.join(", ")}
        </div>
      )}
    </div>
  );
};

export default CameraScenarioConfig;
