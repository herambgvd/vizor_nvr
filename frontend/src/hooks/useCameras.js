// =============================================================================
// useCameras — Shared camera queries & mutations
// =============================================================================

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  getAllCameras,
  createCamera,
  updateCamera,
  deleteCamera,
  startRecording,
  stopRecording,
  testConnection,
} from "../api/cameras";
import { friendlyError } from "../lib/utils";

/**
 * Central camera list query (shared across Dashboard, Cameras, etc.)
 */
export const useCamerasQuery = (options = {}) => {
  return useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
    refetchInterval: 10000,
    ...options,
  });
};

/**
 * All camera CRUD mutations in one hook.
 * Returns { create, update, remove, start, stop, test, isPending }.
 */
export const useCameraMutations = () => {
  const qc = useQueryClient();

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["cameras"] });
  };

  const create = useMutation({
    mutationFn: createCamera,
    onSuccess: () => {
      invalidate();
      toast.success("Camera added");
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't add the camera")),
  });

  const update = useMutation({
    mutationFn: ({ id, data }) => updateCamera(id, data),
    onSuccess: () => {
      invalidate();
      toast.success("Camera updated");
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't update the camera")),
  });

  const remove = useMutation({
    mutationFn: deleteCamera,
    onSuccess: () => {
      invalidate();
      toast.success("Camera deleted");
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't delete the camera")),
  });

  const start = useMutation({
    mutationFn: startRecording,
    onSuccess: (_, cameraId) => {
      invalidate();
      toast.success("Recording started");
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't start recording")),
  });

  const stop = useMutation({
    mutationFn: stopRecording,
    onSuccess: () => {
      invalidate();
      toast.success("Recording stopped");
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't stop recording")),
  });

  const test = useMutation({
    mutationFn: testConnection,
    onSuccess: (result) => {
      invalidate();
      toast.success(
        `Connection OK: ${result.stream_info?.resolution || "connected"}`,
      );
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't connect to the camera")),
  });

  const isPending =
    create.isPending ||
    update.isPending ||
    remove.isPending ||
    start.isPending ||
    stop.isPending ||
    test.isPending;

  return { create, update, remove, start, stop, test, isPending };
};
