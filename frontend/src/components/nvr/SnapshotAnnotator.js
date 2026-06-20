// =============================================================================
// SnapshotAnnotator — canvas-based blur/rect/arrow/text annotation editor
// =============================================================================
//
// Props:
//   cameraId   — string
//   sourceUrl  — string  (relative /cameras/... URL of the source snapshot)
//   onClose    — () => void
//   onSaved    — (savedUrl: string) => void
// =============================================================================

import React, { useRef, useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { Button } from "../ui/button";
import { BACKEND_URL } from "../../api/client";
import { friendlyError } from "../../lib/utils";
import { annotateSnapshot, annotateAndSaveSnapshot } from "../../api/cameras";

const TOOLS = ["blur", "rect", "arrow", "text", "eraser"];

const TOOL_LABELS = {
  blur: "Blur",
  rect: "Rectangle",
  arrow: "Arrow",
  text: "Text",
  eraser: "Eraser",
};

const TOOL_CURSORS = {
  blur: "crosshair",
  rect: "crosshair",
  arrow: "crosshair",
  text: "text",
  eraser: "cell",
};

export default function SnapshotAnnotator({ cameraId, sourceUrl, onClose, onSaved }) {
  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const previewUrlRef = useRef(null);
  const [activeTool, setActiveTool] = useState("blur");
  const [color, setColor] = useState("#ef4444");
  const [textInput, setTextInput] = useState("");
  const [operations, setOperations] = useState([]);
  const [history, setHistory] = useState([[]]);   // for undo
  const [historyIdx, setHistoryIdx] = useState(0);
  const [drawing, setDrawing] = useState(false);
  const [startPt, setStartPt] = useState(null);
  const [previewOp, setPreviewOp] = useState(null);
  const [previewDataUrl, setPreviewDataUrl] = useState(null);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [savedUrl, setSavedUrl] = useState(null);
  const [showEvidenceDialog, setShowEvidenceDialog] = useState(false);
  const [evidenceRecordingId, setEvidenceRecordingId] = useState("");
  const [exportingEvidence, setExportingEvidence] = useState(false);

  const imgSrc = `${BACKEND_URL}${sourceUrl.startsWith("/api") ? "" : "/api"}${sourceUrl}`;

  // ── canvas helpers ──────────────────────────────────────────────────────────

  const getNormCoords = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return { nx: 0, ny: 0 };
    const rect = canvas.getBoundingClientRect();
    const nx = (e.clientX - rect.left) / rect.width;
    const ny = (e.clientY - rect.top) / rect.height;
    return { nx: Math.max(0, Math.min(1, nx)), ny: Math.max(0, Math.min(1, ny)) };
  }, []);

  const redrawCanvas = useCallback((ops) => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return;
    const ctx = canvas.getContext("2d");
    canvas.width = img.naturalWidth || img.width;
    canvas.height = img.naturalHeight || img.height;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const W = canvas.width;
    const H = canvas.height;

    ops.forEach((op) => {
      const px = (op.x ?? 0) * W;
      const py = (op.y ?? 0) * H;
      const pw = (op.w ?? 0.1) * W;
      const ph = (op.h ?? 0.1) * H;
      ctx.strokeStyle = op.color || "#ef4444";
      ctx.lineWidth = op.width || 3;

      if (op.type === "blur") {
        ctx.fillStyle = "rgba(0,0,0,0.35)";
        ctx.fillRect(px, py, pw, ph);
        ctx.strokeRect(px, py, pw, ph);
      } else if (op.type === "rect") {
        ctx.strokeRect(px, py, pw, ph);
      } else if (op.type === "arrow") {
        const x1 = (op.x1 ?? 0) * W;
        const y1 = (op.y1 ?? 0) * H;
        const x2 = (op.x2 ?? 0.1) * W;
        const y2 = (op.y2 ?? 0.1) * H;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        // Arrowhead
        const angle = Math.atan2(y2 - y1, x2 - x1);
        const size = 12;
        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(x2 - size * Math.cos(angle - Math.PI / 6), y2 - size * Math.sin(angle - Math.PI / 6));
        ctx.lineTo(x2 - size * Math.cos(angle + Math.PI / 6), y2 - size * Math.sin(angle + Math.PI / 6));
        ctx.closePath();
        ctx.fillStyle = op.color || "#ef4444";
        ctx.fill();
      } else if (op.type === "text") {
        ctx.fillStyle = op.color || "#ffffff";
        ctx.font = `bold ${op.size || 20}px sans-serif`;
        ctx.shadowColor = "black";
        ctx.shadowBlur = 3;
        ctx.fillText(op.text || "", px, py);
        ctx.shadowBlur = 0;
      }
    });
  }, []);

  useEffect(() => {
    const img = imgRef.current;
    if (!img) return;
    const draw = () => redrawCanvas(operations);
    if (img.complete) draw();
    else img.onload = draw;
  }, [operations, redrawCanvas]);

  // Revoke any outstanding preview blob URL when the annotator unmounts.
  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        try { URL.revokeObjectURL(previewUrlRef.current); } catch (_) {}
        previewUrlRef.current = null;
      }
    };
  }, []);

  // ── mouse handlers ──────────────────────────────────────────────────────────

  const onMouseDown = (e) => {
    if (activeTool === "text") return;  // handled on click
    const { nx, ny } = getNormCoords(e);
    setStartPt({ nx, ny });
    setDrawing(true);
  };

  const onMouseMove = (e) => {
    if (!drawing || !startPt) return;
    const { nx, ny } = getNormCoords(e);
    const w = nx - startPt.nx;
    const h = ny - startPt.ny;

    let preview = null;
    if (activeTool === "blur" || activeTool === "rect") {
      preview = { type: activeTool, x: Math.min(startPt.nx, nx), y: Math.min(startPt.ny, ny), w: Math.abs(w), h: Math.abs(h), color };
    } else if (activeTool === "arrow") {
      preview = { type: "arrow", x1: startPt.nx, y1: startPt.ny, x2: nx, y2: ny, color };
    }
    setPreviewOp(preview);
    if (preview) redrawCanvas([...operations, preview]);
  };

  const onMouseUp = (e) => {
    if (!drawing || !startPt) return;
    setDrawing(false);
    const { nx, ny } = getNormCoords(e);
    const w = nx - startPt.nx;
    const h = ny - startPt.ny;

    let newOp = null;
    if (activeTool === "eraser") {
      // Remove ops whose bounding box overlaps the click point
      const updated = operations.filter((op) => {
        if (op.type === "arrow") {
          return !(Math.abs(((op.x1 + op.x2) / 2) - nx) < 0.05 && Math.abs(((op.y1 + op.y2) / 2) - ny) < 0.05);
        }
        return !(nx >= (op.x ?? 0) && nx <= (op.x ?? 0) + (op.w ?? 0.1) && ny >= (op.y ?? 0) && ny <= (op.y ?? 0) + (op.h ?? 0.1));
      });
      pushOps(updated);
      setPreviewOp(null);
      return;
    }
    if (activeTool === "blur" || activeTool === "rect") {
      if (Math.abs(w) < 0.01 || Math.abs(h) < 0.01) { setPreviewOp(null); setStartPt(null); return; }
      newOp = { type: activeTool, x: Math.min(startPt.nx, nx), y: Math.min(startPt.ny, ny), w: Math.abs(w), h: Math.abs(h), color };
    } else if (activeTool === "arrow") {
      newOp = { type: "arrow", x1: startPt.nx, y1: startPt.ny, x2: nx, y2: ny, color };
    }

    setPreviewOp(null);
    setStartPt(null);
    if (newOp) pushOps([...operations, newOp]);
  };

  const onCanvasClick = (e) => {
    if (activeTool !== "text") return;
    const { nx, ny } = getNormCoords(e);
    const txt = textInput.trim();
    if (!txt) { toast.info("Enter text in the sidebar first"); return; }
    pushOps([...operations, { type: "text", x: nx, y: ny, text: txt, color, size: 22 }]);
  };

  // ── undo / redo ─────────────────────────────────────────────────────────────

  const pushOps = (newOps) => {
    const newHistory = history.slice(0, historyIdx + 1);
    newHistory.push(newOps);
    setHistory(newHistory);
    setHistoryIdx(newHistory.length - 1);
    setOperations(newOps);
  };

  const undo = () => {
    if (historyIdx <= 0) return;
    const idx = historyIdx - 1;
    setHistoryIdx(idx);
    setOperations(history[idx]);
    redrawCanvas(history[idx]);
  };

  const redo = () => {
    if (historyIdx >= history.length - 1) return;
    const idx = historyIdx + 1;
    setHistoryIdx(idx);
    setOperations(history[idx]);
    redrawCanvas(history[idx]);
  };

  // ── preview from backend ────────────────────────────────────────────────────

  const handlePreview = async () => {
    setPreviewing(true);
    try {
      const blob = await annotateSnapshot(cameraId, sourceUrl, operations);
      // Revoke any previous preview blob URL before replacing it.
      if (previewUrlRef.current) {
        try { URL.revokeObjectURL(previewUrlRef.current); } catch (_) {}
      }
      const url = URL.createObjectURL(blob);
      previewUrlRef.current = url;
      setPreviewDataUrl(url);
    } catch (e) {
      toast.error(friendlyError(e, "Couldn't generate the preview"));
    } finally {
      setPreviewing(false);
    }
  };

  // ── save ────────────────────────────────────────────────────────────────────

  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await annotateAndSaveSnapshot(cameraId, sourceUrl, operations);
      toast.success("Annotated snapshot saved");
      setSavedUrl(result.url);
      if (onSaved) onSaved(result.url);
      // Do NOT close — show the "Add to Evidence Export" offer
    } catch (e) {
      toast.error(friendlyError(e, "Couldn't save the annotated snapshot"));
    } finally {
      setSaving(false);
    }
  };

  const handleAddToEvidence = async () => {
    if (!evidenceRecordingId.trim()) {
      toast.error("Enter a recording ID");
      return;
    }
    setExportingEvidence(true);
    try {
      const { exportEvidence } = await import("../../api/cameras");
      const res = await exportEvidence(evidenceRecordingId.trim(), [savedUrl]);
      toast.success(`Evidence bundle created: ${res.data.filename}`);
      setShowEvidenceDialog(false);
    } catch (e) {
      toast.error(friendlyError(e, "Couldn't create the evidence bundle"));
    } finally {
      setExportingEvidence(false);
    }
  };

  // ── render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full bg-zinc-950 text-white" style={{ minHeight: 0 }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-card/30 flex-shrink-0">
        <h2 className="font-semibold text-sm">Snapshot Annotator</h2>
        <button onClick={onClose} className="text-zinc-400 hover:text-white text-lg leading-none">×</button>
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Sidebar */}
        <div className="w-44 flex-shrink-0 border-r border-border bg-card/20 p-3 flex flex-col gap-3 overflow-y-auto">
          {/* Tools */}
          <div>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5">Tool</p>
            <div className="flex flex-col gap-1">
              {TOOLS.map((t) => (
                <button
                  key={t}
                  onClick={() => setActiveTool(t)}
                  className={`px-2 py-1.5 rounded text-xs font-medium text-left transition-colors ${
                    activeTool === t
                      ? "bg-teal-600 text-white"
                      : "text-zinc-400 hover:bg-zinc-800 hover:text-white"
                  }`}
                >
                  {TOOL_LABELS[t]}
                </button>
              ))}
            </div>
          </div>

          {/* Color */}
          <div>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5">Color</p>
            <div className="flex flex-wrap gap-1.5">
              {["#ef4444", "#f97316", "#eab308", "#228B22", "#3b82f6", "#ffffff", "#000000"].map((c) => (
                <button
                  key={c}
                  onClick={() => setColor(c)}
                  style={{ background: c }}
                  className={`w-6 h-6 rounded-full border-2 transition-all ${
                    color === c ? "border-teal-400 scale-110" : "border-transparent"
                  }`}
                />
              ))}
              <input
                type="color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="w-6 h-6 rounded cursor-pointer bg-transparent border border-zinc-600"
                title="Custom colour"
              />
            </div>
          </div>

          {/* Text input (only for text tool) */}
          {activeTool === "text" && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5">Text</p>
              <input
                type="text"
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                placeholder="Label text…"
                className="w-full px-2 py-1 text-xs bg-zinc-900 border border-border rounded text-white"
              />
              <p className="text-[10px] text-zinc-500 mt-1">Then click on image</p>
            </div>
          )}

          {/* Undo / Redo */}
          <div className="flex gap-1">
            <button onClick={undo} disabled={historyIdx <= 0} className="flex-1 px-2 py-1.5 rounded text-xs bg-zinc-800 text-zinc-300 disabled:opacity-40 hover:bg-zinc-700">
              Undo
            </button>
            <button onClick={redo} disabled={historyIdx >= history.length - 1} className="flex-1 px-2 py-1.5 rounded text-xs bg-zinc-800 text-zinc-300 disabled:opacity-40 hover:bg-zinc-700">
              Redo
            </button>
          </div>

          <div className="border-t border-border pt-2 flex flex-col gap-1.5">
            <Button size="sm" variant="outline" onClick={handlePreview} disabled={previewing} className="w-full text-xs">
              {previewing ? "…" : "Preview"}
            </Button>
            <Button size="sm" onClick={handleSave} disabled={saving} className="w-full text-xs">
              {saving ? "Saving…" : "Save"}
            </Button>
            {savedUrl && !showEvidenceDialog && (
              <Button
                size="sm"
                variant="outline"
                className="w-full text-xs border-amber-500 text-amber-400 hover:bg-amber-950"
                onClick={() => setShowEvidenceDialog(true)}
              >
                Add to Evidence Export
              </Button>
            )}
            {showEvidenceDialog && (
              <div className="flex flex-col gap-2 mt-2 p-3 bg-zinc-900 border border-amber-700 rounded">
                <p className="text-xs text-zinc-300">Recording ID to attach snapshot to:</p>
                <input
                  className="px-2 py-1 rounded bg-zinc-800 border border-zinc-600 text-xs text-white focus:outline-none focus:border-amber-500"
                  placeholder="recording-uuid"
                  value={evidenceRecordingId}
                  onChange={(e) => setEvidenceRecordingId(e.target.value)}
                />
                <div className="flex gap-2">
                  <Button size="sm" disabled={exportingEvidence} onClick={handleAddToEvidence} className="text-xs">
                    {exportingEvidence ? "Exporting…" : "Export Evidence"}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-xs" onClick={() => setShowEvidenceDialog(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Canvas area */}
        <div className="flex-1 min-w-0 overflow-auto bg-zinc-900 flex items-start justify-center p-4">
          <div className="relative max-w-full">
            {/* Hidden original image for canvas source */}
            <img
              ref={imgRef}
              src={imgSrc}
              alt="source"
              className="hidden"
              crossOrigin="anonymous"
              onLoad={() => redrawCanvas(operations)}
            />
            {previewDataUrl ? (
              <div className="flex flex-col items-center gap-2">
                <p className="text-xs text-zinc-400">Server-rendered preview</p>
                <img src={previewDataUrl} alt="annotated preview" className="max-w-full rounded border border-border" />
                <Button size="sm" variant="outline" onClick={() => setPreviewDataUrl(null)} className="text-xs">
                  Back to Editor
                </Button>
              </div>
            ) : (
              <canvas
                ref={canvasRef}
                className="max-w-full rounded border border-border block"
                style={{ cursor: TOOL_CURSORS[activeTool] || "crosshair", maxHeight: "70vh" }}
                onMouseDown={onMouseDown}
                onMouseMove={onMouseMove}
                onMouseUp={onMouseUp}
                onMouseLeave={() => { if (drawing) { setDrawing(false); setPreviewOp(null); } }}
                onClick={onCanvasClick}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
