// =============================================================================
// Users — Admin user management (rendered under Settings > Users tab)
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
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
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

const ROLE_META = {
  admin: {
    icon: ShieldCheck,
    cls: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  },
  operator: {
    icon: Shield,
    cls: "bg-blue-500/15 text-blue-300 border border-blue-500/30",
  },
  viewer: {
    icon: Eye,
    cls: "bg-zinc-500/15 text-zinc-300 border border-zinc-500/30",
  },
};

const StatPill = ({ label, value }) => (
  <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border bg-card/50">
    <span className="text-xs text-muted-foreground">{label}</span>
    <span className="text-xs font-semibold tabular-nums">{value}</span>
  </div>
);

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
    <div className="space-y-4">
      {/* Inline toolbar — stat pills + Add User */}
      <div className="flex flex-wrap items-center gap-2">
        <StatPill label="Total" value={total} />
        <StatPill label="Admins" value={adminCount} />
        <StatPill label="Active" value={activeCount} />
        <div className="ml-auto">
          <Button
            size="sm"
            onClick={() => {
              setEditUser(null);
              setDialogOpen(true);
            }}
          >
            <Plus className="h-4 w-4 mr-1" />
            Add User
          </Button>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
              <tr>
                <th className="text-left p-3 font-medium">Username</th>
                <th className="text-left p-3 font-medium">Email</th>
                <th className="text-left p-3 font-medium">Role</th>
                <th className="text-left p-3 font-medium">Status</th>
                <th className="text-left p-3 font-medium">Created</th>
                <th className="text-right p-3 font-medium">Actions</th>
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
              ) : users.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="p-8 text-center text-muted-foreground"
                  >
                    No users found
                  </td>
                </tr>
              ) : (
                users.map((u) => {
                  const rm = ROLE_META[u.role_name] || ROLE_META.viewer;
                  const RoleIcon = rm.icon;
                  const isSelf = u.id === currentUser?.id;
                  const active = u.is_active !== false;
                  return (
                    <tr
                      key={u.id}
                      className="border-t border-white/5 hover:bg-card/50 transition-colors"
                    >
                      <td className="p-3 font-medium">
                        {u.username}
                        {isSelf && (
                          <span className="ml-2 text-[11px] text-muted-foreground">
                            (you)
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-muted-foreground">
                        {u.email || "—"}
                      </td>
                      <td className="p-3">
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium",
                            rm.cls,
                          )}
                        >
                          <RoleIcon className="h-3 w-3" />
                          {u.role_name}
                        </span>
                      </td>
                      <td className="p-3">
                        <span
                          className={cn(
                            "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-medium",
                            active
                              ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                              : "bg-zinc-500/15 text-zinc-400 border border-zinc-500/30",
                          )}
                        >
                          <span
                            className={cn(
                              "h-1.5 w-1.5 rounded-full",
                              active ? "bg-emerald-400" : "bg-zinc-500",
                            )}
                          />
                          {active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td className="p-3 text-muted-foreground text-[11px]">
                        {u.created_at
                          ? format(new Date(u.created_at), "MMM d, yyyy")
                          : "—"}
                      </td>
                      <td className="p-3 text-right">
                        <div className="inline-flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            title="Edit user"
                            onClick={() => {
                              setEditUser(u);
                              setDialogOpen(true);
                            }}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-amber-300 hover:text-amber-200 hover:bg-amber-500/10"
                            title="Revoke all sessions"
                            disabled={isSelf}
                            onClick={() => setRevokeTarget(u)}
                          >
                            <LogOut className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-rose-300 hover:text-rose-200 hover:bg-rose-500/10"
                            title="Delete user"
                            disabled={isSelf}
                            onClick={() => handleDelete(u)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
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
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete User</AlertDialogTitle>
            <AlertDialogDescription>
              Delete <strong>{deleteTarget?.username}</strong>? Permanently
              removes the account and revokes all active sessions. This cannot
              be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteMut.mutate(deleteTarget?.id)}
              disabled={deleteMut.isPending}
              className="bg-destructive hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Revoke sessions confirmation */}
      <AlertDialog
        open={!!revokeTarget}
        onOpenChange={() => setRevokeTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke All Sessions</AlertDialogTitle>
            <AlertDialogDescription>
              Force-logout <strong>{revokeTarget?.username}</strong> by
              revoking all their active refresh tokens. They'll be signed out
              on all devices immediately.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => revokeMut.mutate(revokeTarget?.id)}
              disabled={revokeMut.isPending}
              className="bg-amber-600 hover:bg-amber-700"
            >
              Revoke Sessions
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

// ── user form dialog ───────────────────────────────────────────────────────

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
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit User" : "Create User"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label>Username</Label>
            <Input
              value={form.username}
              onChange={(e) => set("username", e.target.value)}
              required
              disabled={isEdit}
            />
          </div>
          <div>
            <Label>Email</Label>
            <Input
              type="email"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              placeholder="user@example.com"
            />
          </div>
          <div>
            <Label>
              {isEdit ? "New Password (leave empty to keep)" : "Password"}
            </Label>
            <Input
              type="password"
              value={form.password}
              onChange={(e) => set("password", e.target.value)}
              required={!isEdit}
              minLength={6}
              placeholder={isEdit ? "••••••••" : ""}
            />
          </div>
          <div>
            <Label>Role</Label>
            <Select
              value={form.role_name}
              onValueChange={(v) => set("role_name", v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {roles.map((r) => {
                  const name = typeof r === "string" ? r : r.name;
                  return (
                    <SelectItem key={name} value={name}>
                      {name.charAt(0).toUpperCase() + name.slice(1)}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={mutation.isPending}>
              {isEdit ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default Users;
