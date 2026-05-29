// =============================================================================
// Users — Admin user management (/settings/users, rendered in Settings shell)
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  Pencil,
  Shield,
  ShieldCheck,
  Eye,
  LogOut,
} from "lucide-react";
import {
  getAllUsers,
  createUser,
  updateUser,
  deleteUser,
  revokeSessions,
  getRoles,
} from "../api/auth";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { toast } from "sonner";
import { useAuth } from "../context/AuthContext";
import { format } from "date-fns";
import { cn } from "../lib/utils";

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

const DestructiveBtn = ({ children, disabled, onClick, type = "button", className = "" }) => (
  <button
    type={type}
    onClick={onClick}
    disabled={disabled}
    className={`inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50 ${className}`}
    style={{ background: "var(--console-rec)", color: "#fff" }}
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

const GhostIconBtn = ({ children, onClick, disabled, title, style: extraStyle = {} }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    title={title}
    className="h-7 w-7 flex items-center justify-center rounded transition-colors hover:bg-white/5 disabled:opacity-50"
    style={{ color: "var(--console-muted)", ...extraStyle }}
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

const FormRow = ({ label, children }) => (
  <div>
    <label className="block font-telemetry text-[10px] uppercase tracking-wide mb-1" style={{ color: "var(--console-muted)" }}>
      {label}
    </label>
    {children}
  </div>
);

// ─── Role / status badge helpers ──────────────────────────────────────────────

const ROLE_META = {
  admin: {
    icon: ShieldCheck,
    color: "var(--console-rec)",
    border: "rgba(239,68,68,0.3)",
    bg: "rgba(239,68,68,0.12)",
  },
  operator: {
    icon: Shield,
    color: "var(--console-accent)",
    border: "rgba(20,184,166,0.3)",
    bg: "rgba(20,184,166,0.12)",
  },
  viewer: {
    icon: Eye,
    color: "var(--console-muted)",
    border: "var(--console-border)",
    bg: "var(--console-raised)",
  },
};

const RoleBadge = ({ roleName }) => {
  const meta = ROLE_META[roleName] || ROLE_META.viewer;
  const Icon = meta.icon;
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded font-telemetry text-[11px] font-medium border"
      style={{ background: meta.bg, color: meta.color, borderColor: meta.border }}
    >
      <Icon className="h-3 w-3" />
      {roleName}
    </span>
  );
};

const StatusBadge = ({ active }) => (
  <span
    className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded font-telemetry text-[11px] font-medium border"
    style={{
      background: active ? "rgba(34,197,94,0.12)" : "var(--console-raised)",
      color: active ? "var(--console-online)" : "var(--console-muted)",
      borderColor: active ? "rgba(34,197,94,0.3)" : "var(--console-border)",
    }}
  >
    <span
      className="h-1.5 w-1.5 rounded-full"
      style={{ background: active ? "var(--console-online)" : "var(--console-muted)" }}
    />
    {active ? "Active" : "Inactive"}
  </span>
);

const StatPill = ({ label, value }) => (
  <div
    className="inline-flex items-center gap-2 px-3 py-1 rounded border"
    style={{ background: "var(--console-raised)", borderColor: "var(--console-border)" }}
  >
    <span className="font-telemetry text-[10px] uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
      {label}
    </span>
    <span className="font-telemetry text-xs font-semibold tabular-nums" style={{ color: "var(--console-text)" }}>
      {value}
    </span>
  </div>
);

// ─── Main component ───────────────────────────────────────────────────────────

const Users = () => {
  const { user: currentUser } = useAuth();
  const qc = useQueryClient();

  const { data: users = [], isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: getAllUsers,
  });

  const { data: roles = [] } = useQuery({
    queryKey: ["roles"],
    queryFn: getRoles,
    staleTime: 60_000,
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [revokeTarget, setRevokeTarget] = useState(null);

  const deleteMut = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success("User deleted");
      setDeleteTarget(null);
    },
    onError: (e) => {
      toast.error(e.response?.data?.detail || "Failed to delete");
      setDeleteTarget(null);
    },
  });

  const revokeMut = useMutation({
    mutationFn: revokeSessions,
    onSuccess: () => {
      toast.success(`Sessions revoked for ${revokeTarget?.username}`);
      setRevokeTarget(null);
    },
    onError: (e) => {
      toast.error(e.response?.data?.detail || "Failed to revoke sessions");
      setRevokeTarget(null);
    },
  });

  const handleDelete = (u) => {
    if (u.id === currentUser?.id) {
      toast.error("You can't delete your own account");
      return;
    }
    setDeleteTarget(u);
  };

  const total = users.length;
  const adminCount = users.filter((u) => u.role_name === "admin").length;
  const activeCount = users.filter((u) => u.is_active !== false).length;

  return (
    <div className="p-4 space-y-4">
      {/* Header bar */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 rounded border"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <span className="w-0.5 h-4 rounded-full flex-shrink-0" style={{ background: "var(--console-accent)" }} />
        <span className="font-telemetry text-xs font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>
          User Management
        </span>
        <div className="flex-1" />
        <PrimaryBtn
          onClick={() => {
            setEditUser(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add User
        </PrimaryBtn>
      </div>

      {/* Stat pills */}
      <div className="flex flex-wrap items-center gap-2">
        <StatPill label="Total" value={total} />
        <StatPill label="Admins" value={adminCount} />
        <StatPill label="Active" value={activeCount} />
      </div>

      {/* Table */}
      <div className="rounded border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
        <div className="overflow-x-auto">
          <table className="w-full font-telemetry text-[11px]">
            <thead style={{ background: "var(--console-raised)", borderBottom: "1px solid var(--console-border)" }}>
              <tr>
                {["Username", "Email", "Role", "Status", "Created", ""].map((h, i) => (
                  <th
                    key={i}
                    className={cn("px-3 py-2.5 font-semibold uppercase tracking-wide", i === 5 ? "text-right" : "text-left")}
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
                    className="px-3 py-8 text-center font-telemetry text-xs"
                    style={{ background: "var(--console-panel)", color: "var(--console-muted)" }}
                  >
                    Loading…
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-3 py-8 text-center font-telemetry text-xs"
                    style={{ background: "var(--console-panel)", color: "var(--console-muted)" }}
                  >
                    No users found
                  </td>
                </tr>
              ) : (
                users.map((u) => {
                  const isSelf = u.id === currentUser?.id;
                  const active = u.is_active !== false;
                  return (
                    <tr
                      key={u.id}
                      className="border-b last:border-0 hover:bg-white/5 transition-colors"
                      style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
                    >
                      <td className="px-3 py-2.5" style={{ color: "var(--console-text)" }}>
                        <span className="font-semibold">{u.username}</span>
                        {isSelf && (
                          <span className="ml-2 font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
                            (you)
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2.5" style={{ color: "var(--console-muted)" }}>
                        {u.email || "—"}
                      </td>
                      <td className="px-3 py-2.5">
                        <RoleBadge roleName={u.role_name} />
                      </td>
                      <td className="px-3 py-2.5">
                        <StatusBadge active={active} />
                      </td>
                      <td className="px-3 py-2.5 tabular-nums" style={{ color: "var(--console-muted)" }}>
                        {u.created_at
                          ? format(new Date(u.created_at), "MMM d, yyyy")
                          : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <div className="inline-flex items-center gap-0.5">
                          <GhostIconBtn
                            title="Edit user"
                            onClick={() => {
                              setEditUser(u);
                              setDialogOpen(true);
                            }}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </GhostIconBtn>
                          <GhostIconBtn
                            title="Revoke all sessions"
                            disabled={isSelf}
                            onClick={() => setRevokeTarget(u)}
                            style={{ color: "var(--console-alarm)" }}
                          >
                            <LogOut className="h-3.5 w-3.5" />
                          </GhostIconBtn>
                          <GhostIconBtn
                            title="Delete user"
                            disabled={isSelf}
                            onClick={() => handleDelete(u)}
                            style={{ color: "var(--console-rec)" }}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </GhostIconBtn>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Form dialog */}
      <UserFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        user={editUser}
        roles={
          roles.length
            ? roles
            : [{ name: "admin" }, { name: "operator" }, { name: "viewer" }]
        }
        queryClient={qc}
      />

      {/* Delete confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={() => setDeleteTarget(null)}
      >
        <AlertDialogContent
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle className="font-telemetry text-sm font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
              Delete User
            </AlertDialogTitle>
            <AlertDialogDescription className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
              Delete <strong style={{ color: "var(--console-text)" }}>{deleteTarget?.username}</strong>? Permanently
              removes the account and revokes all active sessions. This cannot
              be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <SecondaryBtn>Cancel</SecondaryBtn>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <DestructiveBtn
                onClick={() => deleteMut.mutate(deleteTarget?.id)}
                disabled={deleteMut.isPending}
              >
                Delete
              </DestructiveBtn>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Revoke sessions confirmation */}
      <AlertDialog
        open={!!revokeTarget}
        onOpenChange={() => setRevokeTarget(null)}
      >
        <AlertDialogContent
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle className="font-telemetry text-sm font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
              Revoke All Sessions
            </AlertDialogTitle>
            <AlertDialogDescription className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
              Force-logout <strong style={{ color: "var(--console-text)" }}>{revokeTarget?.username}</strong> by
              revoking all their active refresh tokens. They'll be signed out
              on all devices immediately.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel asChild>
              <SecondaryBtn>Cancel</SecondaryBtn>
            </AlertDialogCancel>
            <AlertDialogAction asChild>
              <button
                type="button"
                onClick={() => revokeMut.mutate(revokeTarget?.id)}
                disabled={revokeMut.isPending}
                className="inline-flex items-center h-[28px] px-3 rounded font-telemetry text-[11px] font-semibold uppercase tracking-wide transition-opacity disabled:opacity-50"
                style={{ background: "var(--console-alarm)", color: "#1a0e00" }}
              >
                Revoke Sessions
              </button>
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

// ── user form dialog ───────────────────────────────────────────────────────────

const UserFormDialog = ({ open, onOpenChange, user, roles, queryClient }) => {
  const isEdit = !!user;

  const [form, setForm] = useState({
    username: "",
    email: "",
    password: "",
    role_name: "viewer",
    is_active: true,
  });

  React.useEffect(() => {
    if (user) {
      setForm({
        username: user.username || "",
        email: user.email || "",
        password: "",
        role_name: user.role_name || "viewer",
        is_active: user.is_active !== false,
      });
    } else {
      setForm({
        username: "",
        email: "",
        password: "",
        role_name: "viewer",
        is_active: true,
      });
    }
  }, [user, open]);

  const mutation = useMutation({
    mutationFn: (data) =>
      isEdit ? updateUser(user.id, data) : createUser(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onOpenChange(false);
      toast.success(isEdit ? "User updated" : "User created");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Failed"),
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const payload = { ...form };
    if (isEdit && !payload.password) delete payload.password;
    mutation.mutate(payload);
  };

  const set = (key, val) => setForm((prev) => ({ ...prev, [key]: val }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
      >
        <DialogHeader>
          <DialogTitle className="font-telemetry text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
            {isEdit ? "Edit User" : "Create User"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <FormRow label="Username">
            <ConsoleInput
              value={form.username}
              onChange={(e) => set("username", e.target.value)}
              required
              disabled={isEdit}
            />
          </FormRow>
          <FormRow label="Email">
            <ConsoleInput
              type="email"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              placeholder="user@example.com"
            />
          </FormRow>
          <FormRow label={isEdit ? "New Password (leave empty to keep)" : "Password"}>
            <ConsoleInput
              type="password"
              value={form.password}
              onChange={(e) => set("password", e.target.value)}
              required={!isEdit}
              minLength={6}
              placeholder={isEdit ? "••••••••" : ""}
            />
          </FormRow>
          <FormRow label="Role">
            <Select
              value={form.role_name}
              onValueChange={(v) => set("role_name", v)}
            >
              <SelectTrigger
                className="h-[30px] font-telemetry text-xs rounded border"
                style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-text)" }}
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent
                style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)", color: "var(--console-text)" }}
              >
                {roles.map((r) => {
                  const name = typeof r === "string" ? r : r.name;
                  return (
                    <SelectItem key={name} value={name} className="font-telemetry text-xs">
                      {name.charAt(0).toUpperCase() + name.slice(1)}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </FormRow>
          <DialogFooter>
            <SecondaryBtn type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </SecondaryBtn>
            <PrimaryBtn type="submit" disabled={mutation.isPending}>
              {isEdit ? "Update" : "Create"}
            </PrimaryBtn>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default Users;
