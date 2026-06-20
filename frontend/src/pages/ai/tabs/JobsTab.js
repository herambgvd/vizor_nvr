import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, RefreshCw, XCircle } from "lucide-react";

import { cancelScenarioJob, listScenarioJobs } from "../../../api/ai";
import { friendlyError } from "../../../lib/utils";

const terminalStates = new Set(["completed", "failed", "cancelled"]);

function statusClass(status) {
  if (status === "completed") return "border-[#228B22]/40 text-[#8bd98b] bg-[#228B22]/10";
  if (status === "failed") return "border-red-500/40 text-red-200 bg-red-950/30";
  if (status === "cancelled") return "border-zinc-500/40 text-zinc-300 bg-zinc-900/40";
  return "border-amber-500/40 text-amber-100 bg-amber-950/20";
}

function fmtDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

const JobsTab = ({ scenario }) => {
  const queryClient = useQueryClient();
  const slug = scenario?.slug;
  const queryKey = ["scenario-jobs", slug];
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey,
    queryFn: () => listScenarioJobs(slug, { limit: 100 }),
    enabled: !!slug,
    refetchInterval: (query) => {
      const jobs = query.state.data?.items || [];
      return jobs.some((job) => !terminalStates.has(job.status)) ? 2500 : false;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (jobId) => cancelScenarioJob(slug, jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const jobs = data?.items || [];

  return (
    <div className="p-5 max-w-[1280px] space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-telemetry text-[14px] font-semibold uppercase tracking-wide text-zinc-100">
            Scenario Jobs
          </h2>
          <p className="font-telemetry text-[11px] text-zinc-500 mt-1">
            Plugin-owned indexing, search and nested search history.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="inline-flex h-9 items-center gap-2 rounded border border-white/10 px-3 text-[12px] text-zinc-200"
        >
          <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <div className="rounded border border-white/10 bg-black overflow-hidden">
        <div className="grid grid-cols-[1.2fr_0.8fr_0.7fr_0.7fr_0.8fr_1fr_0.5fr] gap-3 border-b border-white/10 px-4 py-3 text-[10px] uppercase tracking-widest text-zinc-500">
          <span>Job</span>
          <span>Type</span>
          <span>Status</span>
          <span>Progress</span>
          <span>Results</span>
          <span>Updated</span>
          <span />
        </div>

        {isLoading ? (
          <div className="p-10 text-center text-[12px] text-zinc-500">Loading jobs...</div>
        ) : error ? (
          <div className="p-10 text-center text-[12px] text-red-300">
            {friendlyError(error, "Could not load jobs.")}
          </div>
        ) : jobs.length === 0 ? (
          <div className="p-12 text-center text-zinc-600">
            <Briefcase className="mx-auto mb-3 h-7 w-7" />
            <div className="text-[12px]">No plugin jobs yet.</div>
          </div>
        ) : jobs.map((job) => {
          const progress = Math.round((Number(job.progress) || 0) * 100);
          const canCancel = job.job_id && !terminalStates.has(job.status);
          return (
            <div key={job.job_id} className="grid grid-cols-[1.2fr_0.8fr_0.7fr_0.7fr_0.8fr_1fr_0.5fr] gap-3 border-b border-white/5 px-4 py-3 text-[12px] text-zinc-300 last:border-b-0">
              <div className="min-w-0">
                <div className="truncate font-mono text-[11px] text-zinc-200">{job.job_id}</div>
                {job.message && <div className="mt-1 truncate text-[11px] text-zinc-600">{job.message}</div>}
              </div>
              <div className="capitalize text-zinc-400">{String(job.type || "-").replace(/_/g, " ")}</div>
              <div>
                <span className={`inline-flex rounded border px-2 py-1 text-[10px] uppercase tracking-wide ${statusClass(job.status)}`}>
                  {job.status || "unknown"}
                </span>
              </div>
              <div>
                <div className="h-1.5 rounded bg-zinc-900">
                  <div className="h-full rounded bg-[#228B22]" style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
                </div>
                <div className="mt-1 text-[10px] text-zinc-500">{progress}%</div>
              </div>
              <div className="text-zinc-400">
                {job.result_count ?? job.indexed_candidates ?? 0}
              </div>
              <div className="text-[11px] text-zinc-500">{fmtDate(job.updated_at || job.created_at)}</div>
              <div className="text-right">
                {canCancel && (
                  <button
                    type="button"
                    disabled={cancelMutation.isPending}
                    onClick={() => cancelMutation.mutate(job.job_id)}
                    className="inline-flex h-8 items-center justify-center rounded border border-red-500/40 px-2 text-red-200 disabled:opacity-50"
                    title="Cancel job"
                  >
                    <XCircle className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default JobsTab;
