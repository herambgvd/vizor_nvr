// =============================================================================
// AIModulesIndex — /ai/modules
// =============================================================================
// Grid of scenario cards. Click → /ai/modules/<slug>. Pulls catalog from
// backend so adding a scenario = DB row, no frontend changes.
// =============================================================================

import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Sparkles,
  ArrowUpRight,
  CheckCircle2,
  Lock,
} from "lucide-react";
import apiClient from "../../api/client";
import { Badge } from "../../components/ui/badge";
import { cn } from "../../lib/utils";
import useLicense from "../../hooks/useLicense";

const fetchScenarios = async () => {
  const r = await apiClient.get("/ai/scenarios");
  return r.data;
};

const CATEGORY_CHIPS = [
  { value: "all", label: "All" },
  { value: "person", label: "Person" },
  { value: "behavior", label: "Behavior" },
  { value: "safety", label: "Safety" },
  { value: "security", label: "Security" },
  { value: "vehicle", label: "Vehicle" },
  { value: "search", label: "Search" },
];

const STATUS_STYLE = {
  ga: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  beta: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
  planned: "bg-zinc-500/15 text-zinc-400 border border-zinc-500/30",
};

const TIER_STYLE = {
  free: "bg-zinc-500/15 text-zinc-300 border border-zinc-500/30",
  pro: "bg-blue-500/15 text-blue-300 border border-blue-500/30",
  business: "bg-violet-500/15 text-violet-300 border border-violet-500/30",
  enterprise: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
};

const AIModulesIndex = () => {
  const [category, setCategory] = useState("all");
  const { data: scenarios = [], isLoading } = useQuery({
    queryKey: ["ai-scenarios"],
    queryFn: fetchScenarios,
    staleTime: 60_000,
  });
  const license = useLicense();

  const filtered = useMemo(() => {
    if (category === "all") return scenarios;
    return scenarios.filter((s) => s.category === category);
  }, [scenarios, category]);

  return (
    <div className="p-4 md:p-6 space-y-5 w-full">
      <div className="flex items-center gap-3">
        <Sparkles className="h-6 w-6 text-teal-300" />
        <h1 className="text-2xl font-semibold">AI Modules</h1>
        <span className="text-xs text-muted-foreground">
          {filtered.length} of {scenarios.length}
        </span>
        {license.isActive && (
          <Badge className="ml-auto bg-violet-500/15 text-violet-300 border border-violet-500/30">
            {license.tier?.toUpperCase()} · {license.scenarios.size} scenarios
            {license.aiCameraCap &&
              ` · ${license.aiCameraCap.used}/${license.aiCameraCap.limit} AI cams`}
            {license.daysRemaining <= 30 && license.daysRemaining > 0 && (
              <span className="ml-1 text-amber-300">
                · {license.daysRemaining}d left
              </span>
            )}
          </Badge>
        )}
      </div>

      {/* Category chips */}
      <div className="flex flex-wrap items-center gap-2">
        {CATEGORY_CHIPS.map((c) => (
          <button
            key={c.value}
            type="button"
            onClick={() => setCategory(c.value)}
            className={cn(
              "px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
              category === c.value
                ? "bg-card text-white border-white/20"
                : "bg-card/40 text-muted-foreground border-border hover:text-white",
            )}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Cards */}
      {isLoading ? (
        <div className="text-sm text-muted-foreground py-12 text-center">
          Loading scenarios…
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((s) => {
            const isGa = s.status === "ga";
            const isLicensed = s.licensed !== false;  // backend marks
            const unlocked = isGa && isLicensed;
            const target = unlocked ? `/ai/modules/${s.slug}` : null;
            const card = (
              <div
                className={cn(
                  "group h-full rounded-xl border border-white/10 bg-card/40 p-5 transition-all relative",
                  unlocked
                    ? "hover:border-teal-500/40 hover:bg-card/60 cursor-pointer"
                    : "opacity-60 cursor-not-allowed",
                )}
              >
                {isGa && !isLicensed && (
                  <Badge className="absolute top-3 right-3 bg-amber-500/15 text-amber-300 border border-amber-500/30 inline-flex items-center gap-1">
                    <Lock className="h-3 w-3" />
                    Upgrade
                  </Badge>
                )}
                <div className="flex items-start justify-between gap-2 mb-3">
                  <h3 className="text-base font-semibold flex items-center gap-2 min-w-0">
                    <Sparkles className="h-4 w-4 text-teal-300 shrink-0" />
                    <span className="truncate">{s.name}</span>
                  </h3>
                  <div className="flex flex-wrap gap-1.5 shrink-0">
                    <Badge className={TIER_STYLE[s.tier] || TIER_STYLE.pro}>
                      {s.tier}
                    </Badge>
                    <Badge className={STATUS_STYLE[s.status] || STATUS_STYLE.planned}>
                      {s.status === "ga" ? (
                        <span className="inline-flex items-center gap-1">
                          <CheckCircle2 className="h-3 w-3" />
                          GA
                        </span>
                      ) : (
                        s.status
                      )}
                    </Badge>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground line-clamp-3 mb-3">
                  {s.description}
                </p>
                {s.use_cases?.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {s.use_cases.slice(0, 4).map((u) => (
                      <span
                        key={u}
                        className="text-[10px] text-muted-foreground bg-card/60 px-1.5 py-0.5 rounded"
                      >
                        {u}
                      </span>
                    ))}
                  </div>
                )}
                {unlocked && (
                  <div className="mt-4 flex items-center justify-end text-xs text-teal-300 opacity-0 group-hover:opacity-100 transition-opacity">
                    Open
                    <ArrowUpRight className="h-3.5 w-3.5 ml-1" />
                  </div>
                )}
              </div>
            );

            return target ? (
              <Link key={s.slug} to={target}>
                {card}
              </Link>
            ) : (
              <div key={s.slug}>{card}</div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default AIModulesIndex;
