// =============================================================================
// AuditLog — Filterable audit trail viewer (admin only)
// =============================================================================

import React, { useState, useMemo, useEffect } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import {
  Shield,
  Search,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Filter,
  Download,
} from "lucide-react";
import { getAuditLogs, getAuditActions, cleanupAuditLogs, exportAuditLogs } from "../api/audit";
import SearchableSelect from "../components/ui/searchable-select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/ui/alert-dialog";
import { toast } from "sonner";
import { format } from "date-fns";
import { cn, friendlyError } from "../lib/utils";

const PAGE_SIZES = [25, 50, 100];

// ─── Shared primitives ────────────────────────────────────────────────────────

const PrimaryBtn = ({ children, disabled, onClick, type = "button", className = "" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className={`inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50 ${className}`}
    style={{ background: "var(--console-accent)", color: "#06231f" }}
  >
    {children}
  </button>
);

const SecondaryBtn = ({ children, disabled, onClick, type = "button", className = "" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className={`inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] border transition-colors hover:bg-white/5 disabled:opacity-50 ${className}`}
    style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
  >
    {children}
  </button>
);

const DestructiveBtn = ({ children, disabled, onClick, type = "button" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className="inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50"
    style={{ background: "var(--console-rec)", color: "#fff" }}
  >
    {children}
  </button>
);

const ConsoleInput = ({ className = "", style: extraStyle = {}, ...props }) => (
  <input
    {...props}
    className={`w-full rounded font-telemetry text-xs h-[30px] px-2 border outline-none focus:ring-1 ${className}`}
    style={{
      background: "var(--console-raised)",
      border: "1px solid var(--console-border)",
      color: "var(--console-text)",
      "--tw-ring-color": "var(--console-accent)",
      ...extraStyle,
    }}
  />
);

// ─── Action badge ─────────────────────────────────────────────────────────────

const ACTION_TONES = {
  create: { bg: "hsl(var(--ring) / 0.12)", color: "var(--console-online)", border: "hsl(var(--ring) / 0.3)" },
  update: { bg: "rgba(20,184,166,0.12)", color: "var(--console-accent)", border: "rgba(20,184,166,0.3)" },
  start:  { bg: "hsl(var(--ring) / 0.12)", color: "var(--console-online)", border: "hsl(var(--ring) / 0.3)" },
  stop:   { bg: "rgba(245,158,11,0.12)", color: "var(--console-alarm)", border: "rgba(245,158,11,0.3)" },
  delete: { bg: "rgba(239,68,68,0.12)", color: "var(--console-rec)", border: "rgba(239,68,68,0.3)" },
  login:  { bg: "rgba(139,92,246,0.12)", color: "#a78bfa", border: "rgba(139,92,246,0.3)" },
  logout: { bg: "var(--console-raised)", color: "var(--console-muted)", border: "var(--console-border)" },
  failed: { bg: "rgba(239,68,68,0.20)", color: "var(--console-rec)", border: "rgba(239,68,68,0.5)" },
};

// Map cryptic action codes to clear phrases so clients aren't confused.
const ACTION_OVERRIDES = {
  login_success: "Login",
  login_failed: "Login Failed",
  login_2fa_failed: "Login 2FA Failed",
  login_blocked_schedule: "Login Blocked (Schedule)",
  login_password_policy: "Login Blocked (Password Policy)",
  logout: "Logout",
  "2fa_enabled": "2FA Enabled",
  "2fa_disabled": "2FA Disabled",
  revoke_sessions: "Revoke Sessions",
  session_revoke: "Revoke Session",
  sessions_revoke_others: "Revoke Other Sessions",
  password_change: "Change Password",
  config_backup: "Back Up Configuration",
  config_restore: "Restore Configuration",
  credentials_rotate: "Rotate Credentials",
  credentials_rotate_dry_run: "Rotate Credentials (Dry Run)",
  firmware_upload: "Upload Firmware",
  firmware_upload_dry_run: "Upload Firmware (Dry Run)",
  tls_generate_self_signed: "Generate Self-Signed TLS Cert",
  tls_upload: "Upload TLS Cert",
  diagnostics_bundle_download: "Download Diagnostics Bundle",
  camera_factory_default: "Camera Factory Reset",
  camera_time_sync: "Sync Camera Time",
  time_push_cameras: "Push Time to Cameras",
};

// Acronyms that should stay uppercase when title-casing an action code.
const ACTION_ACRONYMS = new Set([
  "onvif", "ptz", "raid", "ntp", "tls", "sms", "ip", "ddns",
  "2fa", "id", "url", "nvr", "api", "cpu", "pos", "anr",
]);

const humanizeAction = (action) => {
  if (!action) return "Unknown";
  if (ACTION_OVERRIDES[action]) return ACTION_OVERRIDES[action];
  return action
    .split(/[_.:]+/)
    .filter(Boolean)
    .map((w) =>
      ACTION_ACRONYMS.has(w.toLowerCase())
        ? w.toUpperCase()
        : w.charAt(0).toUpperCase() + w.slice(1),
    )
    .join(" ");
};

const ActionBadge = ({ action }) => {
  const lower = (action || "").toLowerCase();
  const key = Object.keys(ACTION_TONES).find((k) => lower.includes(k));
  const tone = key ? ACTION_TONES[key] : { bg: "var(--console-raised)", color: "var(--console-muted)", border: "var(--console-border)" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded font-telemetry text-[11px] font-medium border"
      style={{ background: tone.bg, color: tone.color, borderColor: tone.border }}
      title={action || "unknown"}
    >
      {humanizeAction(action)}
    </span>
  );
};

// ─── Main component ───────────────────────────────────────────────────────────

const AuditLog = () => {
  const qc = useQueryClient();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [action, setAction] = useState("all");
  const [searchFilter, setSearchFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [confirmCleanup, setConfirmCleanup] = useState(false);

  // Backend (app/audit/router.py query_audit_logs) uses the unified pagination
  // contract: limit + offset, and returns {items, total, limit, offset}.
  // Date inputs are calendar days — widen `end_time` to end-of-day so the
  // selected "to" date is inclusive.
  const params = useMemo(() => {
    const p = { limit: pageSize, offset: (page - 1) * pageSize };
    if (action && action !== "all") p.action = action;
    if (searchFilter.trim()) p.search = searchFilter.trim();
    if (startDate) p.start_time = `${startDate}T00:00:00`;
    if (endDate) p.end_time = `${endDate}T23:59:59`;
    return p;
  }, [page, pageSize, action, searchFilter, startDate, endDate]);

  const { data, isLoading } = useQuery({
    queryKey: ["audit-logs", params],
    queryFn: () => getAuditLogs(params),
    placeholderData: keepPreviousData,
  });

  const { data: actionsData } = useQuery({
    queryKey: ["audit-actions"],
    queryFn: getAuditActions,
    staleTime: 60_000,
  });
  const actions = Array.isArray(actionsData)
    ? actionsData
    : actionsData?.actions ?? [];

  const logs = data?.items ?? data ?? [];
  const total = data?.total ?? logs.length;
  // Unified envelope returns total only; derive the page count client-side.
  const totalPages = Math.ceil(total / pageSize) || 1;

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const [exporting, setExporting] = useState(false);

  const handleExport = async (fmt) => {
    setExporting(true);
    try {
      // Export endpoint (/audit/logs/export) filters on action + from/to date
      // only; it has no free-text search, so the active filters are applied
      // where the backend supports them.
      const p = { format: fmt };
      if (action && action !== "all") p.action = action;
      if (startDate) p.from = `${startDate}T00:00:00`;
      if (endDate) p.to = `${endDate}T23:59:59`;
      await exportAuditLogs(p);
    } catch (e) {
      toast.error(friendlyError(e, "Couldn't export the audit log."));
    } finally {
      setExporting(false);
    }
  };

  const cleanupMut = useMutation({
    mutationFn: cleanupAuditLogs,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["audit-logs"] });
      toast.success(`Cleaned up ${res?.deleted ?? 0} old entries`);
      setConfirmCleanup(false);
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't clean up audit entries.")),
  });

  const hasFilters = action !== "all" || searchFilter || startDate || endDate;

  return (
    <div
      className="h-full flex flex-col overflow-hidden"
      style={{ background: "var(--console-bg)", color: "var(--console-text)" }}
    >
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b flex-shrink-0"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <span className="w-0.5 h-4 rounded-full flex-shrink-0" style={{ background: "var(--console-accent)" }} />
        <Shield className="h-3.5 w-3.5 flex-shrink-0" style={{ color: "var(--console-accent)" }} />
        <span className="font-telemetry text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>
          Audit Log
        </span>
        {total > 0 && (
          <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
            {total} {total === 1 ? "entry" : "entries"}
          </span>
        )}
        <div className="flex-1" />
        <div className="flex items-center gap-1.5">
          <SecondaryBtn onClick={() => handleExport("csv")} disabled={exporting}>
            <Download className="h-3.5 w-3.5 mr-1" />
            CSV
          </SecondaryBtn>
          <SecondaryBtn onClick={() => handleExport("json")} disabled={exporting}>
            <Download className="h-3.5 w-3.5 mr-1" />
            JSON
          </SecondaryBtn>
          <SecondaryBtn onClick={() => setConfirmCleanup(true)} disabled={cleanupMut.isPending}>
            <Trash2 className="h-3.5 w-3.5 mr-1" />
            Cleanup
          </SecondaryBtn>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6 space-y-4">
        <div
          className="flex flex-wrap items-center gap-2 rounded border p-2.5"
          style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
        >
          <Filter className="h-3.5 w-3.5 flex-shrink-0" style={{ color: "var(--console-muted)" }} />

          <div className="w-52">
            <SearchableSelect
              value={action}
              onChange={(v) => {
                setAction(v);
                setPage(1);
              }}
              options={[
                { value: "all", label: "All actions" },
                ...actions.map((a) => ({ value: a, label: humanizeAction(a) })),
              ]}
              placeholder="All actions"
              searchPlaceholder="Search action…"
              emptyText="No matching action"
            />
          </div>

          <div className="relative w-60">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 pointer-events-none" style={{ color: "var(--console-muted)" }} />
            <ConsoleInput
              value={searchFilter}
              onChange={(e) => {
                setSearchFilter(e.target.value);
                setPage(1);
              }}
              style={{ paddingLeft: "1.75rem" }}
              placeholder="Search user, action, details…"
            />
          </div>

          <ConsoleInput
            type="date"
            value={startDate}
            onChange={(e) => {
              setStartDate(e.target.value);
              setPage(1);
            }}
            style={{ width: "11rem" }}
            placeholder="From"
          />
          <ConsoleInput
            type="date"
            value={endDate}
            onChange={(e) => {
              setEndDate(e.target.value);
              setPage(1);
            }}
            style={{ width: "11rem" }}
            placeholder="To"
          />

          {hasFilters && (
            <SecondaryBtn
              onClick={() => {
                setAction("all");
                setSearchFilter("");
                setStartDate("");
                setEndDate("");
                setPage(1);
              }}
            >
              Clear
            </SecondaryBtn>
          )}
        </div>

      {/* Table */}
      <div className="rounded border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
        <div className="overflow-x-auto">
          <table className="w-full font-telemetry text-[11px]">
            <thead style={{ background: "var(--console-raised)", borderBottom: "1px solid var(--console-border)" }}>
              <tr>
                {["Time", "User", "Action", "Resource", "Details", "IP"].map((h, i) => (
                  <th
                    key={i}
                    className="px-3 py-2.5 text-left font-semibold uppercase tracking-wide"
                    style={{ color: "var(--console-muted)" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-3 py-8 text-center"
                    style={{ background: "var(--console-panel)", color: "var(--console-muted)" }}
                  >
                    Loading…
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-3 py-8 text-center"
                    style={{ background: "var(--console-panel)", color: "var(--console-muted)" }}
                  >
                    No audit entries found
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr
                    key={log.id}
                    className="border-b last:border-0 hover:bg-white/5 transition-colors"
                    style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
                  >
                    <td className="px-3 py-2.5 whitespace-nowrap tabular-nums" style={{ color: "var(--console-muted)" }}>
                      {log.created_at
                        ? format(new Date(log.created_at), "MMM d HH:mm:ss")
                        : "—"}
                    </td>
                    <td className="px-3 py-2.5 font-semibold" style={{ color: "var(--console-text)" }}>
                      {log.username || log.user_id || "—"}
                    </td>
                    <td className="px-3 py-2.5">
                      <ActionBadge action={log.action} />
                    </td>
                    <td className="px-3 py-2.5 truncate max-w-[260px]" style={{ color: "var(--console-muted)" }}>
                      {log.resource_type
                        ? `${log.resource_type}/${log.resource_id ?? ""}`
                        : "—"}
                    </td>
                    <td className="px-3 py-2.5 truncate max-w-[280px]" style={{ color: "var(--console-muted)" }}>
                      {log.details
                        ? typeof log.details === "string"
                          ? log.details
                          : JSON.stringify(log.details)
                        : "—"}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums" style={{ color: "var(--console-muted)" }}>
                      {log.ip_address || "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
          <div className="flex items-center gap-2">
            <span className="uppercase tracking-wide">Rows</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="rounded border font-telemetry text-[11px] px-2 py-1 outline-none"
              style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-text)" }}
            >
              {PAGE_SIZES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="tabular-nums">
              {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
            </span>
            <div className="flex gap-1">
              <SecondaryBtn
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </SecondaryBtn>
              <SecondaryBtn
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </SecondaryBtn>
            </div>
          </div>
        </div>
      )}

      {/* Cleanup confirmation dialog */}
      <AlertDialog open={confirmCleanup} onOpenChange={setConfirmCleanup}>
        <AlertDialogContent
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle className="font-telemetry text-sm font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
              Cleanup Old Audit Entries
            </AlertDialogTitle>
            <AlertDialogDescription className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
              Delete audit entries older than 365 days. Recent activity is always
              retained for at least a year and cannot be removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <SecondaryBtn>Cancel</SecondaryBtn>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <DestructiveBtn
                onClick={() => cleanupMut.mutate({ days: 365 })}
                disabled={cleanupMut.isPending}
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" />
                Cleanup
              </DestructiveBtn>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      </div>
    </div>
  );
};

export default AuditLog;
