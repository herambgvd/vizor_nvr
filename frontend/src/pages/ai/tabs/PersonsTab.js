// =============================================================================
// AI · Persons tab (FRS) — person gallery + enrollment.
// =============================================================================
// Paginated, searchable person list with group filter. "Add person" dialog
// (createPerson). Clicking a person opens a detail drawer: photos grid with
// authenticated thumbnails (photoImageUrl → object URL), upload (uploadPhoto,
// multipart) with per-photo status (pending/enrolled/failed) + quality/liveness,
// delete photo, enrollment_status badge, and edit / delete person.
//
// NOTE: the photo image endpoint is gated by an Authorization header (no
// ?token= query support), so thumbnails are fetched as blobs via photoImageUrl
// and rendered as object URLs (revoked on unmount).
// =============================================================================

import React, { useEffect, useRef, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import {
  Users,
  Plus,
  Search,
  X,
  Pencil,
  Trash2,
  Upload,
  Loader2,
  ChevronLeft,
  ChevronRight,
  UserCircle2,
  ShieldCheck,
  ShieldAlert,
  Clock,
} from "lucide-react";
import { toast } from "sonner";

import {
  listPersons,
  createPerson,
  updatePerson,
  deletePerson,
  listGroups,
  listPhotos,
  uploadPhoto,
  deletePhoto,
  photoImageUrl,
} from "../../../api/ai";

const CATEGORIES = ["standard", "vip", "monitored", "restricted", "banned"];
const PAGE_SIZE = 24;

// ---------------------------------------------------------------------------
// shared primitives
// ---------------------------------------------------------------------------

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};
const inputCls = "w-full rounded px-2.5 py-1.5 font-telemetry text-[12px] outline-none";

const ENROLL_META = {
  enrolled: { color: "var(--console-accent)", Icon: ShieldCheck, label: "Enrolled" },
  pending: { color: "#f59e0b", Icon: Clock, label: "Pending" },
  failed: { color: "var(--console-rec)", Icon: ShieldAlert, label: "Failed" },
  unenrolled: { color: "var(--console-muted)", Icon: UserCircle2, label: "Unenrolled" },
};

const EnrollBadge = ({ status }) => {
  const meta = ENROLL_META[status] || ENROLL_META.unenrolled;
  const { color, Icon, label } = meta;
  return (
    <span
      className="inline-flex items-center gap-1 font-telemetry text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded border"
      style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color }}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
};

const Field = ({ label, children }) => (
  <div className="flex flex-col gap-1.5">
    <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
      {label}
    </label>
    {children}
  </div>
);

const Modal = ({ title, onClose, children }) => (
  <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }}>
    <div
      className="w-full max-w-md rounded p-5 flex flex-col gap-4"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      <div className="flex items-center justify-between">
        <h3 className="font-telemetry text-[13px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
          {title}
        </h3>
        <button type="button" onClick={onClose} className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70" style={{ color: "var(--console-muted)" }}>
          <X className="h-4 w-4" />
        </button>
      </div>
      {children}
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// authenticated photo thumbnail
// ---------------------------------------------------------------------------

const PhotoThumb = ({ photoId, className }) => {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let active = true;
    let objUrl = null;
    photoImageUrl(photoId).then((u) => {
      if (!active) {
        if (u) URL.revokeObjectURL(u);
        return;
      }
      objUrl = u;
      setUrl(u);
    });
    return () => {
      active = false;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [photoId]);

  if (!url) {
    return (
      <div className={className} style={{ background: "var(--console-raised)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Loader2 className="h-4 w-4 animate-spin" style={{ color: "var(--console-muted)" }} />
      </div>
    );
  }
  return <img src={url} alt="" className={className} style={{ objectFit: "cover" }} />;
};

// ---------------------------------------------------------------------------
// person create / edit form
// ---------------------------------------------------------------------------

const PersonForm = ({ initial, groups, onClose, qc }) => {
  const editing = !!initial;
  const [form, setForm] = useState({
    full_name: initial?.full_name || "",
    external_id: initial?.external_id || "",
    group_id: initial?.group_id || "",
    category: initial?.category || "standard",
    priority: initial?.priority ?? 0,
  });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const mut = useMutation({
    mutationFn: () => {
      const payload = {
        full_name: form.full_name.trim(),
        external_id: form.external_id.trim() || null,
        group_id: form.group_id || null,
        category: form.category,
        priority: Number(form.priority) || 0,
      };
      return editing ? updatePerson(initial.id, payload) : createPerson(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-persons"] });
      if (editing) qc.invalidateQueries({ queryKey: ["frs-person", initial.id] });
      toast.success(editing ? "Person updated" : "Person created");
      onClose();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to save person"),
  });

  const submit = () => {
    if (!form.full_name.trim()) {
      toast.error("Full name is required");
      return;
    }
    mut.mutate();
  };

  return (
    <Modal title={editing ? "Edit person" : "Add person"} onClose={onClose}>
      <Field label="Full name">
        <input className={inputCls} style={inputStyle} value={form.full_name} onChange={(e) => set("full_name", e.target.value)} autoFocus />
      </Field>
      <Field label="External ID">
        <input className={inputCls} style={inputStyle} value={form.external_id} onChange={(e) => set("external_id", e.target.value)} placeholder="HR id, badge no…" />
      </Field>
      <Field label="Group">
        <select className={inputCls} style={inputStyle} value={form.group_id} onChange={(e) => set("group_id", e.target.value)}>
          <option value="">— none —</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Category">
          <select className={inputCls} style={inputStyle} value={form.category} onChange={(e) => set("category", e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Priority (0–10)">
          <input type="number" min={0} max={10} className={inputCls} style={inputStyle} value={form.priority} onChange={(e) => set("priority", e.target.value)} />
        </Field>
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onClose} className="font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}>
          Cancel
        </button>
        <button type="button" onClick={submit} disabled={mut.isPending} className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded disabled:opacity-50" style={{ background: "var(--console-accent)", color: "#fff" }}>
          {mut.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
          {editing ? "Save" : "Create"}
        </button>
      </div>
    </Modal>
  );
};

// ---------------------------------------------------------------------------
// photo card (inside drawer)
// ---------------------------------------------------------------------------

const PHOTO_STATUS_COLOR = {
  enrolled: "var(--console-accent)",
  pending: "#f59e0b",
  failed: "var(--console-rec)",
};

const PhotoCard = ({ photo, qc, personId }) => {
  const delMut = useMutation({
    mutationFn: () => deletePhoto(photo.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-photos", personId] });
      qc.invalidateQueries({ queryKey: ["frs-person", personId] });
      qc.invalidateQueries({ queryKey: ["frs-persons"] });
      toast.success("Photo deleted");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to delete photo"),
  });

  const color = PHOTO_STATUS_COLOR[photo.status] || "var(--console-muted)";

  return (
    <div className="rounded overflow-hidden flex flex-col" style={{ border: "1px solid var(--console-border)", background: "var(--console-raised)" }}>
      <div className="relative">
        <PhotoThumb photoId={photo.id} className="w-full aspect-square" />
        <button
          type="button"
          onClick={() => delMut.mutate()}
          disabled={delMut.isPending}
          className="absolute top-1 right-1 h-6 w-6 inline-flex items-center justify-center rounded disabled:opacity-50"
          style={{ background: "rgba(0,0,0,0.6)", color: "#fff" }}
          title="Delete photo"
        >
          {delMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
        </button>
        <span
          className="absolute bottom-1 left-1 font-telemetry text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded"
          style={{ background: "rgba(0,0,0,0.65)", color }}
        >
          {photo.status}
        </span>
      </div>
      <div className="px-2 py-1.5 flex flex-col gap-0.5">
        <div className="flex items-center justify-between font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          <span>Q</span>
          <span style={{ color: "var(--console-text)" }}>{photo.quality_score != null ? photo.quality_score.toFixed(2) : "—"}</span>
        </div>
        <div className="flex items-center justify-between font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          <span>Live</span>
          <span style={{ color: "var(--console-text)" }}>{photo.liveness_score != null ? photo.liveness_score.toFixed(2) : "—"}</span>
        </div>
        {photo.status === "failed" && photo.error && (
          <p className="font-telemetry text-[9px] leading-tight mt-0.5 break-all" style={{ color: "var(--console-rec)" }}>
            {photo.error}
          </p>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// person detail drawer
// ---------------------------------------------------------------------------

const PersonDrawer = ({ person, groups, onClose, qc }) => {
  const fileRef = useRef(null);
  const [editing, setEditing] = useState(false);

  const { data: photos = [], isLoading: photosLoading } = useQuery({
    queryKey: ["frs-photos", person.id],
    queryFn: () => listPhotos(person.id),
  });

  const uploadMut = useMutation({
    mutationFn: (file) => uploadPhoto(person.id, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-photos", person.id] });
      qc.invalidateQueries({ queryKey: ["frs-person", person.id] });
      qc.invalidateQueries({ queryKey: ["frs-persons"] });
      toast.success("Photo uploaded — enrollment pending");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Upload failed"),
  });

  const delMut = useMutation({
    mutationFn: () => deletePerson(person.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-persons"] });
      toast.success("Person deleted");
      onClose();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to delete person"),
  });

  const onPick = (e) => {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
    e.target.value = "";
  };

  const onDeletePerson = () => {
    if (window.confirm(`Delete ${person.full_name}? All photos and enrollment are removed.`)) delMut.mutate();
  };

  const groupName = groups.find((g) => g.id === person.group_id)?.name;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" style={{ background: "rgba(0,0,0,0.6)" }} onClick={onClose}>
      <div
        className="h-full w-full max-w-md flex flex-col"
        style={{ background: "var(--console-panel)", borderLeft: "1px solid var(--console-border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="p-5 flex items-start justify-between gap-3" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-11 w-11 rounded flex items-center justify-center shrink-0" style={{ background: "var(--console-raised)" }}>
              <UserCircle2 className="h-6 w-6" style={{ color: "var(--console-accent)" }} />
            </div>
            <div className="min-w-0">
              <h3 className="font-telemetry text-[14px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
                {person.full_name}
              </h3>
              <div className="font-telemetry text-[10px] uppercase tracking-widest truncate" style={{ color: "var(--console-muted)" }}>
                {person.category}
                {person.external_id ? ` · ${person.external_id}` : ""}
              </div>
            </div>
          </div>
          <button type="button" onClick={onClose} className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70 shrink-0" style={{ color: "var(--console-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* meta */}
        <div className="px-5 py-3 flex items-center flex-wrap gap-2" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <EnrollBadge status={person.enrollment_status} />
          {groupName && (
            <span className="font-telemetry text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}>
              {groupName}
            </span>
          )}
          <span className="font-telemetry text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}>
            P{person.priority}
          </span>
          <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            {person.enrolled_photo_count}/{person.photo_count} enrolled
          </span>
        </div>

        {/* actions */}
        <div className="px-5 py-3 flex items-center gap-2" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPick} />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploadMut.isPending}
            className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded disabled:opacity-50"
            style={{ background: "var(--console-accent)", color: "#fff" }}
          >
            {uploadMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            Upload photo
          </button>
          <button type="button" onClick={() => setEditing(true)} className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}>
            <Pencil className="h-3.5 w-3.5" />
            Edit
          </button>
          <button type="button" onClick={onDeletePerson} disabled={delMut.isPending} className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded border disabled:opacity-50 ml-auto" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-rec)" }}>
            {delMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            Delete
          </button>
        </div>

        {/* photos grid */}
        <div className="flex-1 overflow-auto p-5">
          <p className="font-telemetry text-[10px] uppercase tracking-widest mb-3" style={{ color: "var(--console-muted)" }}>
            Photos · {photos.length}
          </p>
          {photosLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
            </div>
          ) : photos.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-12 rounded" style={{ border: "1px dashed var(--console-border)" }}>
              <Upload className="h-5 w-5" style={{ color: "var(--console-muted)" }} />
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                No photos — upload to enroll
              </span>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {photos.map((p) => (
                <PhotoCard key={p.id} photo={p} personId={person.id} qc={qc} />
              ))}
            </div>
          )}
        </div>
      </div>

      {editing && (
        <div onClick={(e) => e.stopPropagation()}>
          <PersonForm initial={person} groups={groups} qc={qc} onClose={() => setEditing(false)} />
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// person row
// ---------------------------------------------------------------------------

const PersonRow = ({ person, groupName, onOpen }) => (
  <button
    type="button"
    onClick={() => onOpen(person)}
    className="text-left rounded p-3 flex items-center gap-3 transition-colors hover:brightness-110"
    style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
  >
    <div className="h-9 w-9 rounded flex items-center justify-center shrink-0" style={{ background: "var(--console-raised)" }}>
      <UserCircle2 className="h-5 w-5" style={{ color: "var(--console-accent)" }} />
    </div>
    <div className="min-w-0 flex-1">
      <div className="font-telemetry text-[12px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
        {person.full_name}
      </div>
      <div className="font-telemetry text-[10px] uppercase tracking-widest truncate" style={{ color: "var(--console-muted)" }}>
        {person.category}
        {groupName ? ` · ${groupName}` : ""}
        {person.external_id ? ` · ${person.external_id}` : ""}
      </div>
    </div>
    <EnrollBadge status={person.enrollment_status} />
  </button>
);

// ---------------------------------------------------------------------------
// tab
// ---------------------------------------------------------------------------

const PersonsTab = () => {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [page, setPage] = useState(0);
  const [showAdd, setShowAdd] = useState(false);
  const [openPersonId, setOpenPersonId] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(search.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data: groups = [] } = useQuery({ queryKey: ["frs-groups"], queryFn: listGroups });

  const { data, isLoading } = useQuery({
    queryKey: ["frs-persons", { search: debounced, group_id: groupFilter, page }],
    queryFn: () =>
      listPersons({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        search: debounced || undefined,
        group_id: groupFilter || undefined,
      }),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const groupName = (id) => groups.find((g) => g.id === id)?.name;

  // The drawer reads the (always-fresh) row from the current page list. The
  // detail/photo mutations invalidate ["frs-persons"], so this row reflects
  // counter/enrollment changes on the next refetch.
  const drawerPerson = items.find((p) => p.id === openPersonId) || null;

  return (
    <div className="p-6 flex flex-col gap-4">
      {/* toolbar */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Persons · {total}
          </span>
        </div>
        <div className="flex items-center gap-2 flex-1 justify-end flex-wrap">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5" style={{ color: "var(--console-muted)" }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name / id"
              className="rounded pl-7 pr-2.5 py-1.5 font-telemetry text-[12px] outline-none w-[200px]"
              style={inputStyle}
            />
          </div>
          <select
            value={groupFilter}
            onChange={(e) => {
              setGroupFilter(e.target.value);
              setPage(0);
            }}
            className="rounded px-2.5 py-1.5 font-telemetry text-[12px] outline-none"
            style={inputStyle}
          >
            <option value="">All groups</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded"
            style={{ background: "var(--console-accent)", color: "#fff" }}
          >
            <Plus className="h-3.5 w-3.5" />
            Add person
          </button>
        </div>
      </div>

      {/* list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
          <Users className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            No persons found
          </span>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {items.map((p) => (
            <PersonRow key={p.id} person={p} groupName={groupName(p.group_id)} onOpen={(pp) => setOpenPersonId(pp.id)} />
          ))}
        </div>
      )}

      {/* pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-3 pt-1">
          <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="h-7 w-7 inline-flex items-center justify-center rounded border disabled:opacity-40" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}>
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
            {page + 1} / {pages}
          </span>
          <button type="button" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)} className="h-7 w-7 inline-flex items-center justify-center rounded border disabled:opacity-40" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {showAdd && <PersonForm groups={groups} qc={qc} onClose={() => setShowAdd(false)} />}
      {drawerPerson && <PersonDrawer person={drawerPerson} groups={groups} qc={qc} onClose={() => setOpenPersonId(null)} />}
    </div>
  );
};

export default PersonsTab;
