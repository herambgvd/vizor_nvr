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
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
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
import { cn } from "../lib/utils";

const PAGE_SIZES = [25, 50, 100];

// Dark-theme action badges — match Events severity palette
const TONES = {
  create: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  update: "bg-blue-500/15 text-blue-300 border border-blue-500/30",
  start: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  stop: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
  delete: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  login: "bg-violet-500/15 text-violet-300 border border-violet-500/30",
  logout: "bg-zinc-500/15 text-zinc-300 border border-zinc-500/30",
  failed: "bg-rose-500/25 text-rose-200 border border-rose-500/50",
};

const ActionBadge = ({ action }) => {
  const lower = (action || "").toLowerCase();
  const key = Object.keys(TONES).find((k) => lower.includes(k));
  const cls = key ? TONES[key] : "bg-card/60 text-muted-foreground border border-border";
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium",
        cls,
      )}
    >
      {action || "unknown"}
    </span>
  );
};

const AuditLog = () => {
  const qc = useQueryClient();

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [action, setAction] = useState("all");
  const [userFilter, setUserFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [confirmCleanup, setConfirmCleanup] = useState(false);

  const params = useMemo(() => {
    const p = { page, page_size: pageSize };
    if (action && action !== "all") p.action = action;
    if (userFilter.trim()) p.user = userFilter.trim();
    if (startDate) p.start_date = startDate;
    if (endDate) p.end_date = endDate;
    return p;
  }, [page, pageSize, action, userFilter, startDate, endDate]);

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
  const totalPages = data?.total_pages ?? (Math.ceil(total / pageSize) || 1);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const [exportFmt, setExportFmt] = useState("csv");
  const [exporting, setExporting] = useState(false);

  const handleExport = async (fmt) => {
    setExporting(true);
    try {
      const p = { format: fmt };
      if (action && action !== "all") p.action = action;
      if (userFilter.trim()) p.user_id = userFilter.trim();
      if (startDate) p.from = startDate;
      if (endDate) p.to = endDate;
      await exportAuditLogs(p);
    } catch (e) {
      toast.error("Export failed");
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
    onError: (e) => toast.error(e.response?.data?.detail || "Cleanup failed"),
  });

  return (
    <div className="p-6 md:p-8 space-y-6 w-full">
      {/* Header — title + filters + actions on one row */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Shield className="h-6 w-6" />
          <h1 className="text-2xl font-semibold">Audit Log</h1>
          {total > 0 && (
            <span className="text-xs text-muted-foreground">
              {total} {total === 1 ? "entry" : "entries"}
            </span>
          )}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleExport("csv")}
            disabled={exporting}
          >
            <Download className="h-4 w-4 mr-1" />
            CSV
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleExport("json")}
            disabled={exporting}
          >
            <Download className="h-4 w-4 mr-1" />
            JSON
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setConfirmCleanup(true)}
            disabled={cleanupMut.isPending}
          >
            <Trash2 className="h-4 w-4 mr-1" />
            Cleanup Old Logs
          </Button>
        </div>
      </div>

      {/* Filters — one row, no nested card */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-card/40 p-3">
        <Filter className="h-4 w-4 text-muted-foreground mt-2.5 flex-shrink-0" />

        <div className="w-44">
          <Select
            value={action}
            onValueChange={(v) => {
              setAction(v);
              setPage(1);
            }}
          >
            <SelectTrigger className="h-9">
              <SelectValue placeholder="All actions" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All actions</SelectItem>
              {actions.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="relative w-52">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={userFilter}
            onChange={(e) => {
              setUserFilter(e.target.value);
              setPage(1);
            }}
            className="pl-9 h-9"
            placeholder="User…"
          />
        </div>

        <Input
          type="date"
          value={startDate}
          onChange={(e) => {
            setStartDate(e.target.value);
            setPage(1);
          }}
          className="w-44 h-9"
          placeholder="From"
        />
        <Input
          type="date"
          value={endDate}
          onChange={(e) => {
            setEndDate(e.target.value);
            setPage(1);
          }}
          className="w-44 h-9"
          placeholder="To"
        />

        {(action !== "all" || userFilter || startDate || endDate) && (
          <Button
            variant="ghost"
            size="sm"
            className="h-9"
            onClick={() => {
              setAction("all");
              setUserFilter("");
              setStartDate("");
              setEndDate("");
              setPage(1);
            }}
          >
            Clear
          </Button>
        )}
      </div>

      {/* Table */}
      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
              <tr>
                <th className="text-left p-3 font-medium">Time</th>
                <th className="text-left p-3 font-medium">User</th>
                <th className="text-left p-3 font-medium">Action</th>
                <th className="text-left p-3 font-medium">Resource</th>
                <th className="text-left p-3 font-medium">Details</th>
                <th className="text-left p-3 font-medium">IP</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td
                    colSpan={6}
                    className="p-8 text-center text-muted-foreground"
                  >
                    Loading…
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="p-8 text-center text-muted-foreground"
                  >
                    No audit entries found
                  </td>
                </tr>
              ) : (
                logs.map((log) => (
                  <tr
                    key={log.id}
                    className="border-t border-white/5 hover:bg-card/50 transition-colors"
                  >
                    <td className="p-3 whitespace-nowrap text-muted-foreground">
                      {log.created_at
                        ? format(new Date(log.created_at), "MMM d HH:mm:ss")
                        : "—"}
                    </td>
                    <td className="p-3 font-medium">
                      {log.username || log.user_id || "—"}
                    </td>
                    <td className="p-3">
                      <ActionBadge action={log.action} />
                    </td>
                    <td className="p-3 font-mono text-[11px] text-muted-foreground truncate max-w-[260px]">
                      {log.resource_type
                        ? `${log.resource_type}/${log.resource_id ?? ""}`
                        : "—"}
                    </td>
                    <td className="p-3 text-[11px] text-muted-foreground truncate max-w-[280px]">
                      {log.details
                        ? typeof log.details === "string"
                          ? log.details
                          : JSON.stringify(log.details)
                        : "—"}
                    </td>
                    <td className="p-3 font-mono text-[11px] text-muted-foreground">
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
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>Rows per page</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="bg-card border border-border rounded px-2 py-1 text-foreground"
            >
              {PAGE_SIZES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span>
              {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
            </span>
            <div className="flex gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}

      <AlertDialog open={confirmCleanup} onOpenChange={setConfirmCleanup}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cleanup old audit entries</AlertDialogTitle>
            <AlertDialogDescription>
              Delete all audit entries older than 90 days. This cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => cleanupMut.mutate({ older_than_days: 90 })}
              className="bg-destructive hover:bg-destructive/90"
              disabled={cleanupMut.isPending}
            >
              <Trash2 className="h-4 w-4 mr-1" />
              Cleanup
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default AuditLog;
