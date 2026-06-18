import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Bell,
  CheckCircle2,
  CircleAlert,
  CircleOff,
  ShieldCheck,
  ToggleLeft,
  ToggleRight,
  Video,
} from "lucide-react";
import { toast } from "sonner";
import { getScenarioHealth, toggleScenario } from "../../../api/ai";

const friendlyCapability = {
  archive_search: "Search old recordings",
  live_inference: "Watch live video",
  event_producer: "Create alerts",
  enrollment: "Manage people or samples",
  reporting: "Reports",
  gpu_required: "Uses GPU",
  supports_roi: "Area selection",
  supports_schedule: "Schedule support",
};

const titleCase = (value) =>
  String(value || "")
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

const scenarioPurpose = (scenario) => {
  if (scenario.slug === "suspect-search") {
    return "Find matching people, bags or helmets from recorded video.";
  }
  if (scenario.slug === "frs") {
    return "Recognize enrolled people and review related events.";
  }
  if (scenario.slug === "ppe") {
    return "Detect helmet and vest compliance from selected cameras.";
  }
  return scenario.description || "Use this feature with selected cameras.";
};

const statusTone = (ok) => (
  ok
    ? { icon: CheckCircle2, label: "Ready", color: "var(--console-online)" }
    : { icon: CircleAlert, label: "Needs attention", color: "#F59E0B" }
);

const InfoCard = ({ icon: Icon, title, value, help, tone }) => (
  <div
    className="rounded p-4 min-h-[122px]"
    style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
  >
    <div className="flex items-start gap-3">
      <div
        className="h-9 w-9 rounded flex items-center justify-center shrink-0"
        style={{ background: "var(--console-raised)" }}
      >
        <Icon className="h-4 w-4" style={{ color: tone || "var(--console-accent)" }} />
      </div>
      <div className="min-w-0">
        <p className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          {title}
        </p>
        <p className="mt-1 text-sm font-semibold" style={{ color: "var(--console-text)" }}>
          {value}
        </p>
        {help && (
          <p className="mt-1 text-[12px] leading-relaxed" style={{ color: "var(--console-muted)" }}>
            {help}
          </p>
        )}
      </div>
    </div>
  </div>
);

const ScenarioSettingsTab = ({ scenario }) => {
  const queryClient = useQueryClient();
  const healthQuery = useQuery({
    queryKey: ["ai-scenario-health", scenario.slug],
    queryFn: () => getScenarioHealth(scenario.slug),
    enabled: !!scenario?.slug && scenario.registered,
    retry: 1,
  });

  const toggleMutation = useMutation({
    mutationFn: (enabled) => toggleScenario(scenario.id, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ai-scenarios"] });
      queryClient.invalidateQueries({ queryKey: ["ai-scenario", "slug", scenario.slug] });
      toast.success("Feature setting updated");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Could not update feature"),
  });

  const workerReady = scenario.registered && !healthQuery.isError;
  const workerTone = statusTone(workerReady);
  const WorkerIcon = workerTone.icon;
  const activeCameras = scenario.active_camera_count || 0;
  const cameraLimit = scenario.camera_limit || 0;
  const featureOn = !!scenario.enabled;
  const canUse = scenario.registered && scenario.licensed && featureOn;
  const capabilities = (scenario.capabilities || [])
    .map((item) => friendlyCapability[item] || titleCase(item))
    .filter(Boolean);
  const events = (scenario.event_types || []).map(titleCase);

  return (
    <div className="p-6 w-full space-y-5">
      <div
        className="rounded p-5 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
      >
        <div className="min-w-0">
          <h2 className="font-telemetry text-[15px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            {scenario.name} Settings
          </h2>
          <p className="mt-1 text-sm leading-relaxed max-w-[980px]" style={{ color: "var(--console-muted)" }}>
            {scenarioPurpose(scenario)}
          </p>
        </div>
        <button
          type="button"
          disabled={!scenario.registered || toggleMutation.isPending}
          onClick={() => toggleMutation.mutate(!featureOn)}
          className="inline-flex h-9 items-center justify-center gap-2 rounded px-4 text-[12px] font-semibold uppercase tracking-wide disabled:opacity-50 xl:min-w-[150px]"
          style={{
            background: featureOn ? "var(--console-accent)" : "var(--console-raised)",
            color: featureOn ? "var(--console-accent-foreground)" : "var(--console-text)",
            border: "1px solid var(--console-border)",
          }}
        >
          {featureOn ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
          {featureOn ? "Feature On" : "Feature Off"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 w-full">
        <InfoCard
          icon={canUse ? CheckCircle2 : CircleOff}
          title="Feature status"
          value={canUse ? "Ready to use" : "Not ready yet"}
          help={!scenario.registered ? "Background service is not connected." : !scenario.licensed ? "License is not active." : !featureOn ? "Turn this feature on to use it." : "Operators can use this feature now."}
          tone={canUse ? "var(--console-online)" : "#F59E0B"}
        />
        <InfoCard
          icon={ShieldCheck}
          title="License"
          value={scenario.licensed ? "Active" : "Not active"}
          help={scenario.licensed ? "This feature is allowed on this system." : "Ask admin to activate the license."}
          tone={scenario.licensed ? "var(--console-online)" : "#F59E0B"}
        />
        <InfoCard
          icon={Video}
          title="Cameras in use"
          value={`${activeCameras}${cameraLimit > 0 ? ` / ${cameraLimit}` : ""}`}
          help="Choose cameras from the Cameras tab."
        />
        <InfoCard
          icon={WorkerIcon}
          title="Processing status"
          value={workerTone.label}
          help={workerReady ? "This feature is responding." : "Video recording will continue; only this feature is affected."}
          tone={workerTone.color}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.3fr_1fr] gap-3">
        <div
          className="rounded p-4 space-y-4 min-h-[180px]"
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        >
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
            <h3 className="font-telemetry text-[12px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
              What operators can do
            </h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {(capabilities.length ? capabilities : ["Use selected cameras"]).map((label) => (
              <span
                key={label}
                className="rounded px-2.5 py-1 text-[11px] font-telemetry"
                style={{ background: "var(--console-raised)", color: "var(--console-text)", border: "1px solid var(--console-border)" }}
              >
                {label}
              </span>
            ))}
          </div>
        </div>

        <div
          className="rounded p-4 min-h-[180px]"
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        >
          <div className="flex items-center gap-2">
            <Bell className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
            <h3 className="font-telemetry text-[12px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
              Alerts created by this feature
            </h3>
          </div>
          {events.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {events.map((label) => (
                <span
                  key={label}
                  className="rounded px-2.5 py-1 text-[11px] font-telemetry"
                  style={{ background: "var(--console-raised)", color: "var(--console-muted)", border: "1px solid var(--console-border)" }}
                >
                  {label}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-[12px]" style={{ color: "var(--console-muted)" }}>
              This feature does not create alerts yet.
            </p>
          )}
        </div>
      </div>

      <div
        className="rounded p-4 text-[12px] leading-relaxed"
        style={{ background: "var(--console-raised)", color: "var(--console-muted)", border: "1px solid var(--console-border)" }}
      >
        To start using this feature, keep it turned on and enable it for the required cameras from the Cameras tab.
        Turning it off stops new processing, but old saved results and alerts can still be reviewed where available.
      </div>
    </div>
  );
};

export default ScenarioSettingsTab;
