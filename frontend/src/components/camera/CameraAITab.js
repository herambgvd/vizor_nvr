// =============================================================================
// CameraAITab — per-camera AI scenario configuration.
//
// Shows every GA scenario from /api/ai/scenarios. For each, the operator
// can toggle enable + edit common config knobs (threshold, ROI ID, etc.).
// Saved config is written via PUT /api/ai/cameras/{id}/scenarios/{slug}.
// =============================================================================

import React, { useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Sparkles, Loader2, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  listScenarios,
  listCameraScenarios,
  upsertCameraScenario,
  removeCameraScenario,
} from "../../api/ai";

import { Button } from "../ui/button";
import { Switch } from "../ui/switch";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Badge } from "../ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../ui/card";


/**
 * Returns a small set of editable fields from a scenario's default_config.
 * We expose primitives (string, number, boolean); nested ROI/zones are
 * edited in a separate component (Phase 1.11.c).
 */
function flatPrimitives(obj, prefix = "") {
  if (!obj || typeof obj !== "object") return [];
  const out = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === null) continue;
    if (
      typeof v === "string" ||
      typeof v === "number" ||
      typeof v === "boolean"
    ) {
      out.push({ key: prefix + k, value: v, type: typeof v });
    }
  }
  return out;
}


function ScenarioCard({ scenario, currentCfg, cameraId, onSaved }) {
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState(currentCfg?.enabled ?? false);
  const [config, setConfig] = useState(
    currentCfg?.config && Object.keys(currentCfg.config).length
      ? currentCfg.config
      : scenario.default_config || {}
  );

  const editable = useMemo(
    () => flatPrimitives(scenario.default_config || {}),
    [scenario]
  );

  const saveMutation = useMutation({
    mutationFn: () =>
      upsertCameraScenario(cameraId, scenario.slug, { enabled, config }),
    onSuccess: () => {
      toast.success(`${scenario.name} updated`);
      queryClient.invalidateQueries({ queryKey: ["camera-scenarios", cameraId] });
      onSaved?.();
    },
    onError: (e) => toast.error(`Save failed: ${e.message}`),
  });

  const deleteMutation = useMutation({
    mutationFn: () => removeCameraScenario(cameraId, scenario.slug),
    onSuccess: () => {
      toast.success(`${scenario.name} disabled`);
      queryClient.invalidateQueries({ queryKey: ["camera-scenarios", cameraId] });
    },
    onError: (e) => toast.error(`Disable failed: ${e.message}`),
  });

  const updateField = (key, value) => {
    setConfig((c) => ({ ...c, [key]: value }));
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">{scenario.name}</CardTitle>
            <CardDescription className="text-xs pt-1">
              {scenario.description}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <Badge variant="outline" className="text-[10px]">
              {scenario.tier}
            </Badge>
            <Switch
              checked={enabled}
              onCheckedChange={setEnabled}
              aria-label={`Toggle ${scenario.name}`}
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {enabled && editable.length > 0 ? (
          <div className="grid grid-cols-2 gap-3">
            {editable.map((f) => (
              <div key={f.key} className="space-y-1">
                <Label className="text-xs">{f.key.replace(/_/g, " ")}</Label>
                {f.type === "boolean" ? (
                  <Switch
                    checked={!!config[f.key]}
                    onCheckedChange={(v) => updateField(f.key, v)}
                  />
                ) : (
                  <Input
                    type={f.type === "number" ? "number" : "text"}
                    value={
                      config[f.key] !== undefined ? config[f.key] : f.value
                    }
                    step={f.type === "number" ? "0.01" : undefined}
                    onChange={(e) =>
                      updateField(
                        f.key,
                        f.type === "number"
                          ? parseFloat(e.target.value)
                          : e.target.value
                      )
                    }
                    className="h-8 text-xs"
                  />
                )}
              </div>
            ))}
          </div>
        ) : null}

        <div className="flex items-center justify-end gap-2 pt-2">
          {currentCfg ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1" />
              Remove
            </Button>
          ) : null}
          <Button
            size="sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5 mr-1" />
            )}
            {currentCfg ? "Update" : "Enable"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}


export default function CameraAITab({ cameraId }) {
  const { data: scenarios = [], isLoading: loadingCatalog } = useQuery({
    queryKey: ["ai-scenarios"],
    queryFn: () => listScenarios({ status: "ga" }),
  });

  const { data: cameraScenarios = [], isLoading: loadingCamera } = useQuery({
    queryKey: ["camera-scenarios", cameraId],
    queryFn: () => listCameraScenarios(cameraId),
    enabled: !!cameraId,
  });

  const byCamSlug = useMemo(() => {
    const m = {};
    for (const cs of cameraScenarios) {
      m[cs.scenario_slug] = cs;
    }
    return m;
  }, [cameraScenarios]);

  if (loadingCatalog || loadingCamera) {
    return (
      <div className="p-6 text-sm text-slate-400">Loading AI scenarios…</div>
    );
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl space-y-4">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 text-white">
          <Sparkles size={20} />
        </div>
        <div>
          <h2 className="text-lg font-semibold">AI Scenarios</h2>
          <p className="text-xs text-slate-500">
            Enable AI analytics on this camera. Toggle a scenario
            on, tune thresholds, and save. Pipelines run independently per camera.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {scenarios.map((s) => (
          <ScenarioCard
            key={s.slug}
            scenario={s}
            currentCfg={byCamSlug[s.slug]}
            cameraId={cameraId}
          />
        ))}
      </div>

      {scenarios.length === 0 ? (
        <div className="text-center py-8 text-slate-500 text-sm">
          No GA scenarios available yet. Check the AI Scenarios page for roadmap.
        </div>
      ) : null}
    </div>
  );
}
