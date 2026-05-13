// =============================================================================
// AuditLog — Filterable audit trail viewer (admin only)
// =============================================================================

import React, { useState, useMemo } from "react";
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
  Calendar,
} from "lucide-react";
import { getAuditLogs, getAuditActions, cleanupAuditLogs } from "../api/audit";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { toast } from "sonner";
import { format } from "date-fns";

const PAGE_SIZE = 25;

const AuditLog = () => {
  const qc = useQueryClient();

  // filters
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("all");
  const [userFilter, setUserFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // build query params
  const params = useMemo(() => {
    const p = { page, page_size: PAGE_SIZE };
    if (action && action !== "all") p.action = action;
    if (userFilter.trim()) p.user = userFilter.trim();
    if (startDate) p.start_date = startDate;
    if (endDate) p.end_date = endDate;
    return p;
  }, [page, action, userFilter, startDate, endDate]);

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
    : (actionsData?.actions ?? []);

  const logs = data?.items ?? data ?? [];
  const total = data?.total ?? logs.length;
  const totalPages = data?.total_pages ?? (Math.ceil(total / PAGE_SIZE) || 1);

  const cleanupMut = useMutation({
    mutationFn: cleanupAuditLogs,
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["audit-logs"] });
      toast.success(`Cleaned up ${res.deleted ?? 0} old log entries`);
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Cleanup failed"),
  });

  const handleCleanup = () => {
    if (!window.confirm("Delete audit entries older than 90 days?")) return;
    cleanupMut.mutate({ older_than_days: 90 });
  };

  return (
    <div className="p-8 h-full overflow-y-auto">
      {/* header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1
            className="text-3xl font-bold text-white tracking-tight"
            style={{ fontFamily: "Manrope, sans-serif" }}
          >
            Audit Log
          </h1>
          <p className="text-zinc-500 mt-1">
            Track system actions and changes
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleCleanup}
          disabled={cleanupMut.isPending}
        >
          <Trash2 className="h-4 w-4 mr-1" />
          Cleanup Old Logs
        </Button>
      </div>

      {/* filters */}
      <div className="bg-zinc-950 border border-white/10 rounded-lg p-4 mb-6">
        <div className="flex items-center gap-2 mb-3 text-sm text-zinc-500 font-medium">
          <Filter className="h-4 w-4" />
          Filters
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <Label className="text-xs">Action</Label>
            <Select
              value={action}
              onValueChange={(v) => {
                setAction(v);
                setPage(1);
              }}
            >
              <SelectTrigger>
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
          <div>
            <Label className="text-xs">User</Label>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-zinc-500" />
              <Input
                value={userFilter}
                onChange={(e) => {
                  setUserFilter(e.target.value);
                  setPage(1);
                }}
                className="pl-8"
                placeholder="Username…"
              />
            </div>
          </div>
          <div>
            <Label className="text-xs">From</Label>
            <Input
              type="date"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div>
            <Label className="text-xs">To</Label>
            <Input
              type="date"
              value={endDate}
              onChange={(e) => {
                setEndDate(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>
      </div>

      {/* table */}
      <div className="bg-zinc-950 border border-white/10 rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-10 text-center text-zinc-500">Loading…</div>
        ) : logs.length === 0 ? (
          <div className="p-10 text-center text-zinc-500">
            No audit entries found
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-950/40 border-b border-white/10">
              <tr>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Time
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  User
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Action
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Resource
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Details
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  IP
                </th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr
                  key={log.id}
                  className="border-b border-slate-100 last:border-0 hover:bg-zinc-950/40/50"
                >
                  <td className="px-4 py-3 whitespace-nowrap text-zinc-500">
                    {log.created_at
                      ? format(new Date(log.created_at), "MMM d, yyyy HH:mm:ss")
                      : "-"}
                  </td>
                  <td className="px-4 py-3 font-medium text-white">
                    {log.username || log.user_id || "-"}
                  </td>
                  <td className="px-4 py-3">
                    <ActionBadge action={log.action} />
                  </td>
                  <td className="px-4 py-3 text-zinc-400 font-mono text-xs truncate max-w-[200px]">
                    {log.resource_type
                      ? `${log.resource_type}/${log.resource_id ?? ""}`
                      : "-"}
                  </td>
                  <td className="px-4 py-3 text-zinc-500 text-xs truncate max-w-[250px]">
                    {log.details
                      ? typeof log.details === "string"
                        ? log.details
                        : JSON.stringify(log.details)
                      : "-"}
                  </td>
                  <td className="px-4 py-3 text-zinc-500 text-xs font-mono">
                    {log.ip_address || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-zinc-500">
            Page {page} of {totalPages}
          </p>
          <div className="flex gap-2">
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
      )}
    </div>
  );
};

// ── action badge ───────────────────────────────────────────────────────────────

const colorMap = {
  create: "bg-green-100 text-green-700",
  update: "bg-blue-100 text-blue-700",
  delete: "bg-red-100 text-red-700",
  login: "bg-purple-100 text-purple-700",
  logout: "bg-white/[0.04] text-zinc-400",
};

const ActionBadge = ({ action }) => {
  const key = Object.keys(colorMap).find((k) =>
    action?.toLowerCase().includes(k),
  );
  const cls = key ? colorMap[key] : "bg-white/[0.04] text-zinc-400";
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}
    >
      {action || "unknown"}
    </span>
  );
};

export default AuditLog;
