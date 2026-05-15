// =============================================================================
// FRS Gallery — Face recognition persons + groups management.
//
// Style matches Events / Cameras pages: dark zinc backdrop, white/10
// borders, white/[0.03] surface, max 1600px container.
// =============================================================================

import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Loader2,
  Pencil,
  Plus,
  Search,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import {
  createFRSGroup,
  createFRSPerson,
  deleteFRSGroup,
  deleteFRSPerson,
  listFRSGroups,
  listFRSPersons,
  updateFRSPerson,
} from "../api/frs";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";


// ── Person dialog ──────────────────────────────────────────────────────


function PersonDialog({ open, onOpenChange, person, groups, onSubmit, submitting }) {
  const [name, setName] = useState(person?.name || "");
  const [externalId, setExternalId] = useState(person?.external_id || "");
  const [groupId, setGroupId] = useState(person?.group_id || "");

  React.useEffect(() => {
    setName(person?.name || "");
    setExternalId(person?.external_id || "");
    setGroupId(person?.group_id || "");
  }, [person]);

  const handleSubmit = () => {
    if (!name.trim()) {
      toast.error("Name required");
      return;
    }
    onSubmit({
      name: name.trim(),
      external_id: externalId.trim() || null,
      group_id: groupId || null,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{person ? "Edit person" : "Enroll new person"}</DialogTitle>
          <DialogDescription>
            Add a person to the FRS gallery. Upload reference photos from
            the person detail page once AI is enabled.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1">
            <Label>Full name *</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label>External ID (HR id, badge number…)</Label>
            <Input
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              placeholder="e.g. EMP-1234"
            />
          </div>
          <div className="space-y-1">
            <Label>Group</Label>
            <Select
              value={groupId || "_none"}
              onValueChange={(v) => setGroupId(v === "_none" ? "" : v)}
            >
              <SelectTrigger>
                <SelectValue placeholder="(no group)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="_none">(no group)</SelectItem>
                {groups.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : null}
            {person ? "Save" : "Enroll"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


// ── Group dialog ───────────────────────────────────────────────────────


function GroupDialog({ open, onOpenChange, onSubmit, submitting }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("");

  React.useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setColor("");
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create group</DialogTitle>
          <DialogDescription>
            Groups bucket persons for watchlist routing and per-camera filtering.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1">
            <Label>Name *</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Employees"
            />
          </div>
          <div className="space-y-1">
            <Label>Description</Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label>Color (hex)</Label>
            <Input
              value={color}
              onChange={(e) => setColor(e.target.value)}
              placeholder="#3b82f6"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => name.trim() && onSubmit({ name: name.trim(), description, color })}
            disabled={submitting}
          >
            {submitting ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}


// ── Main page ──────────────────────────────────────────────────────────


export default function FRSPersons() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [groupFilter, setGroupFilter] = useState(
    searchParams.get("group") || "all",
  );

  useEffect(() => {
    const q = searchParams.get("group");
    if (q && q !== groupFilter) setGroupFilter(q);
  }, [searchParams, groupFilter]);

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (groupFilter && groupFilter !== "all") next.set("group", groupFilter);
    else next.delete("group");
    if (next.toString() !== searchParams.toString()) setSearchParams(next, { replace: true });
  }, [groupFilter, searchParams, setSearchParams]);
  const [personDialogOpen, setPersonDialogOpen] = useState(false);
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [editingPerson, setEditingPerson] = useState(null);

  const { data: groups = [] } = useQuery({
    queryKey: ["frs-groups"],
    queryFn: listFRSGroups,
  });

  const { data: persons = [], isLoading } = useQuery({
    queryKey: ["frs-persons", search, groupFilter],
    queryFn: () =>
      listFRSPersons({
        q: search || undefined,
        group_id: groupFilter !== "all" ? groupFilter : undefined,
      }),
    keepPreviousData: true,
  });

  const createPerson = useMutation({
    mutationFn: createFRSPerson,
    onSuccess: () => {
      toast.success("Person enrolled");
      queryClient.invalidateQueries({ queryKey: ["frs-persons"] });
      setPersonDialogOpen(false);
    },
    onError: (e) => toast.error(`Failed: ${e.response?.data?.detail || e.message}`),
  });

  const updatePerson = useMutation({
    mutationFn: ({ id, data }) => updateFRSPerson(id, data),
    onSuccess: () => {
      toast.success("Person updated");
      queryClient.invalidateQueries({ queryKey: ["frs-persons"] });
      setPersonDialogOpen(false);
      setEditingPerson(null);
    },
    onError: (e) => toast.error(`Failed: ${e.response?.data?.detail || e.message}`),
  });

  const deletePerson = useMutation({
    mutationFn: deleteFRSPerson,
    onSuccess: () => {
      toast.success("Person removed");
      queryClient.invalidateQueries({ queryKey: ["frs-persons"] });
    },
    onError: (e) => toast.error(`Failed: ${e.response?.data?.detail || e.message}`),
  });

  const createGroup = useMutation({
    mutationFn: createFRSGroup,
    onSuccess: () => {
      toast.success("Group created");
      queryClient.invalidateQueries({ queryKey: ["frs-groups"] });
      setGroupDialogOpen(false);
    },
    onError: (e) => toast.error(`Failed: ${e.response?.data?.detail || e.message}`),
  });

  const deleteGroup = useMutation({
    mutationFn: deleteFRSGroup,
    onSuccess: () => {
      toast.success("Group deleted");
      queryClient.invalidateQueries({ queryKey: ["frs-groups"] });
      queryClient.invalidateQueries({ queryKey: ["frs-persons"] });
    },
    onError: (e) => toast.error(`Failed: ${e.response?.data?.detail || e.message}`),
  });

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-[1600px] mx-auto">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Users className="h-6 w-6" />
          <div>
            <h1 className="text-2xl font-semibold">FRS Gallery</h1>
            <p className="text-sm text-muted-foreground">
              {persons.length} {persons.length === 1 ? "person" : "persons"} in {groups.length}{" "}
              {groups.length === 1 ? "group" : "groups"}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setGroupDialogOpen(true)}>
            <Plus className="h-4 w-4 mr-1" />
            New group
          </Button>
          <Button
            onClick={() => {
              setEditingPerson(null);
              setPersonDialogOpen(true);
            }}
          >
            <UserPlus className="h-4 w-4 mr-1" />
            Enroll person
          </Button>
        </div>
      </div>

      {/* ── Groups strip ────────────────────────────────────────────── */}
      {groups.length > 0 ? (
        <div className="rounded-lg border border-border bg-card/40 p-3">
          <div className="flex flex-wrap gap-2">
            {groups.map((g) => (
              <div
                key={g.id}
                className="flex items-center gap-2 px-3 py-1.5 rounded border border-border bg-card/50 text-sm"
              >
                {g.color ? (
                  <span
                    className="w-3 h-3 rounded-full"
                    style={{ background: g.color }}
                  />
                ) : null}
                <span className="font-medium">{g.name}</span>
                <Badge className="bg-white/10 text-zinc-200 border border-border text-[10px]">
                  {g.person_count}
                </Badge>
                <button
                  onClick={() => {
                    if (
                      window.confirm(
                        `Delete group "${g.name}"? Persons will be unassigned but not deleted.`
                      )
                    ) {
                      deleteGroup.mutate(g.id);
                    }
                  }}
                  className="text-muted-foreground hover:text-rose-400 transition-colors"
                  title="Delete group"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* ── Filters ─────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-card/40 p-3">
        <Search className="h-4 w-4 text-muted-foreground mt-2.5" />
        <div className="w-72">
          <Label className="text-xs text-muted-foreground">Search</Label>
          <Input
            placeholder="Name or external ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="w-44">
          <Label className="text-xs text-muted-foreground">Group</Label>
          <Select value={groupFilter} onValueChange={setGroupFilter}>
            <SelectTrigger>
              <SelectValue placeholder="Group" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All groups</SelectItem>
              {groups.map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* ── Persons table ───────────────────────────────────────────── */}
      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
            <tr>
              <th className="text-left px-4 py-3 font-medium">Name</th>
              <th className="text-left px-4 py-3 font-medium">External ID</th>
              <th className="text-left px-4 py-3 font-medium">Group</th>
              <th className="text-left px-4 py-3 font-medium">Photos</th>
              <th className="text-left px-4 py-3 font-medium">Last seen</th>
              <th className="text-right px-4 py-3 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={6} className="text-center py-10 text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin inline mr-2" />
                  Loading…
                </td>
              </tr>
            ) : persons.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center py-12 text-muted-foreground">
                  No persons enrolled yet.
                </td>
              </tr>
            ) : (
              persons.map((p) => (
                <tr
                  key={p.id}
                  className="border-t border-white/5 hover:bg-card/50 transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-zinc-100">{p.name}</td>
                  <td className="px-4 py-3 text-zinc-400 font-mono text-xs">
                    {p.external_id || "—"}
                  </td>
                  <td className="px-4 py-3">
                    {p.group_name ? (
                      <Badge className="bg-blue-500/15 text-blue-300 border border-blue-500/30">
                        {p.group_name}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-zinc-300">{p.photo_count}</td>
                  <td className="px-4 py-3 text-zinc-400 text-xs">
                    {p.last_seen_at
                      ? new Date(p.last_seen_at).toLocaleString()
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditingPerson(p);
                        setPersonDialogOpen(true);
                      }}
                      title="Edit"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        if (
                          window.confirm(
                            `Remove person "${p.name}" and all photos?`
                          )
                        ) {
                          deletePerson.mutate(p.id);
                        }
                      }}
                      title="Remove"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-rose-400" />
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <PersonDialog
        open={personDialogOpen}
        onOpenChange={setPersonDialogOpen}
        person={editingPerson}
        groups={groups}
        submitting={createPerson.isPending || updatePerson.isPending}
        onSubmit={(data) =>
          editingPerson
            ? updatePerson.mutate({ id: editingPerson.id, data })
            : createPerson.mutate(data)
        }
      />
      <GroupDialog
        open={groupDialogOpen}
        onOpenChange={setGroupDialogOpen}
        submitting={createGroup.isPending}
        onSubmit={(data) => createGroup.mutate(data)}
      />
    </div>
  );
}
