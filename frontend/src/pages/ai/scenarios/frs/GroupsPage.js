// =============================================================================
// FRS · Groups — /ai/modules/frs/groups
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Users, Plus, Trash2, Pencil, UserPlus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import apiClient from "../../../../api/client";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { Label } from "../../../../components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../../../../components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../../../../components/ui/alert-dialog";
import { Badge } from "../../../../components/ui/badge";

const listGroups = () => apiClient.get("/ai/frs/groups").then((r) => r.data);
const createGroup = (data) => apiClient.post("/ai/frs/groups", data).then((r) => r.data);
const updateGroup = (id, data) => apiClient.patch(`/ai/frs/groups/${id}`, data).then((r) => r.data);
const deleteGroup = (id) => apiClient.delete(`/ai/frs/groups/${id}`).then((r) => r.data);

const GroupsPage = () => {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const goToMembers = (group) =>
    navigate(`/ai/modules/frs/persons?group=${group.id}`);

  const { data: groups = [], isLoading } = useQuery({
    queryKey: ["frs-groups"],
    queryFn: listGroups,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["frs-groups"] });

  const createMut = useMutation({
    mutationFn: createGroup,
    onSuccess: () => {
      invalidate();
      setShowForm(false);
      toast.success("Group created");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Create failed"),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, data }) => updateGroup(id, data),
    onSuccess: () => {
      invalidate();
      setShowForm(false);
      setEditing(null);
      toast.success("Group updated");
    },
  });
  const deleteMut = useMutation({
    mutationFn: deleteGroup,
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      toast.success("Group deleted");
    },
  });

  return (
    <div className="p-4 md:p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-teal-300" />
          <h2 className="text-sm font-semibold">Person groups</h2>
          <span className="text-xs text-muted-foreground">{groups.length}</span>
        </div>
        <Button size="sm" onClick={() => { setEditing(null); setShowForm(true); }}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          New group
        </Button>
      </div>

      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
              <tr>
                <th className="text-left p-3 font-medium">Name</th>
                <th className="text-left p-3 font-medium">Description</th>
                <th className="text-right p-3 font-medium">Members</th>
                <th className="text-right p-3 font-medium">Color</th>
                <th className="text-right p-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              ) : groups.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-8 text-center text-muted-foreground">
                    No groups
                  </td>
                </tr>
              ) : (
                groups.map((g) => (
                  <tr key={g.id} className="border-t border-white/5 hover:bg-card/50">
                    <td className="p-3 font-medium">{g.name}</td>
                    <td className="p-3 text-muted-foreground">{g.description || "—"}</td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => goToMembers(g)}
                        className="font-mono text-teal-300 hover:text-teal-200 hover:underline"
                      >
                        {g.member_count ?? 0}
                      </button>
                    </td>
                    <td className="p-3 text-right">
                      {g.color ? (
                        <Badge
                          variant="outline"
                          className="text-[10px]"
                          style={{
                            backgroundColor: `${g.color}22`,
                            borderColor: `${g.color}66`,
                            color: g.color,
                          }}
                        >
                          {g.color}
                        </Badge>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="p-3 text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        title="Manage members"
                        onClick={() => goToMembers(g)}
                      >
                        <UserPlus className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => { setEditing(g); setShowForm(true); }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-rose-300 hover:text-rose-200 hover:bg-rose-500/10"
                        onClick={() => setDeleteTarget(g)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <GroupForm
        open={showForm}
        onOpenChange={(v) => { setShowForm(v); if (!v) setEditing(null); }}
        group={editing}
        onSubmit={(data) => {
          if (editing) updateMut.mutate({ id: editing.id, data });
          else createMut.mutate(data);
        }}
        pending={createMut.isPending || updateMut.isPending}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete group</AlertDialogTitle>
            <AlertDialogDescription>
              Remove "{deleteTarget?.name}"? Members are not deleted — they
              become un-grouped.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteMut.mutate(deleteTarget?.id)}
              className="bg-destructive hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

const GroupForm = ({ open, onOpenChange, group, onSubmit, pending }) => {
  const isEdit = !!group;
  const [form, setForm] = useState({
    name: "",
    description: "",
    color: "#14b8a6",
  });

  React.useEffect(() => {
    if (group) {
      setForm({
        name: group.name || "",
        description: group.description || "",
        color: group.color || "#14b8a6",
      });
    } else {
      setForm({ name: "", description: "", color: "#14b8a6" });
    }
  }, [group, open]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!form.name.trim()) return toast.error("Name required");
    onSubmit({ ...form, name: form.name.trim() });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit group" : "New group"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="VIP, Staff, Watchlist…"
              required
            />
          </div>
          <div>
            <Label>Description</Label>
            <Input
              value={form.description}
              onChange={(e) =>
                setForm((f) => ({ ...f, description: e.target.value }))
              }
            />
          </div>
          <div>
            <Label>Color</Label>
            <Input
              type="color"
              value={form.color}
              onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
              className="h-9 w-24 p-1"
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={pending}>
              {pending ? "Saving…" : isEdit ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default GroupsPage;
