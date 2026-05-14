// =============================================================================
// Users — Admin user management
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Users as UsersIcon,
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
import { Switch } from "../components/ui/switch";
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

const ROLE_META = {
  admin: { icon: ShieldCheck, color: "text-red-600 bg-red-50" },
  operator: { icon: Shield, color: "text-blue-600 bg-blue-50" },
  viewer: { icon: Eye, color: "text-zinc-400 bg-card/60" },
};

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
      toast.success(`All sessions revoked for ${revokeTarget?.username}`);
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

  return (
    <div className="p-8 h-full overflow-y-auto">
      {/* header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1
            className="text-3xl font-bold text-white tracking-tight"
            style={{ fontFamily: "Manrope, sans-serif" }}
          >
            Users
          </h1>
          <p className="text-muted-foreground mt-1">Manage user accounts and roles</p>
        </div>
        <Button
          onClick={() => {
            setEditUser(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="h-4 w-4 mr-1" />
          Add User
        </Button>
      </div>

      {/* stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
        <StatCard label="Total Users" value={users.length} />
        <StatCard
          label="Admins"
          value={users.filter((u) => u.role_name === "admin").length}
        />
        <StatCard
          label="Active"
          value={users.filter((u) => u.is_active !== false).length}
        />
      </div>

      {/* table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {isLoading ? (
          <div className="p-10 text-center text-muted-foreground">Loading…</div>
        ) : users.length === 0 ? (
          <div className="p-10 text-center text-muted-foreground">No users found</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-card/40 border-b border-border">
              <tr>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Username
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Email
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Role
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Status
                </th>
                <th className="text-left px-4 py-3 text-zinc-400 font-medium">
                  Created
                </th>
                <th className="text-right px-4 py-3 text-zinc-400 font-medium">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const rm = ROLE_META[u.role_name] || ROLE_META.viewer;
                const RoleIcon = rm.icon;
                const isSelf = u.id === currentUser?.id;
                return (
                  <tr
                    key={u.id}
                    className="border-b border-slate-100 last:border-0 hover:bg-card/40/50"
                  >
                    <td className="px-4 py-3 font-medium text-white">
                      {u.username}
                      {isSelf && (
                        <span className="ml-2 text-xs text-muted-foreground">
                          (you)
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-zinc-400">
                      {u.email || "-"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${rm.color}`}
                      >
                        <RoleIcon className="h-3 w-3" />
                        {u.role_name}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {u.is_active !== false ? (
                        <span
                          className="inline-block h-2 w-2 rounded-full bg-green-500"
                          title="Active"
                        />
                      ) : (
                        <span
                          className="inline-block h-2 w-2 rounded-full bg-slate-300"
                          title="Inactive"
                        />
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground text-xs">
                      {u.created_at
                        ? format(new Date(u.created_at), "MMM d, yyyy")
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1">
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
                          className="h-8 w-8 text-orange-500"
                          title="Revoke all sessions"
                          disabled={isSelf}
                          onClick={() => setRevokeTarget(u)}
                        >
                          <LogOut className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-red-500"
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
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* form dialog */}
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
      <AlertDialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete User</AlertDialogTitle>
            <AlertDialogDescription>
              Delete <strong>{deleteTarget?.username}</strong>? This will permanently remove their
              account and revoke all active sessions. This action cannot be undone.
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
      <AlertDialog open={!!revokeTarget} onOpenChange={() => setRevokeTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke All Sessions</AlertDialogTitle>
            <AlertDialogDescription>
              Force-logout <strong>{revokeTarget?.username}</strong> by revoking all their active
              refresh tokens. They will be signed out on all devices immediately.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => revokeMut.mutate(revokeTarget?.id)}
              disabled={revokeMut.isPending}
              className="bg-orange-600 hover:bg-orange-700"
            >
              Revoke Sessions
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

// ── stat card ──────────────────────────────────────────────────────────────────

const StatCard = ({ label, value }) => (
  <div className="bg-card border border-border rounded-lg p-4">
    <p className="text-sm text-muted-foreground">{label}</p>
    <p className="text-2xl font-bold text-white">{value}</p>
  </div>
);

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
    // don't send empty password on edit
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
