// =============================================================================
// Camera Card Component - Individual Camera Display
// =============================================================================
// Displays camera feed with status, controls, and recording indicator.
// Designed for grid layout with hover controls.
// =============================================================================

import React, { useState, useEffect, memo } from "react";
import {
  Video,
  VideoOff,
  Settings,
  Maximize2,
  Camera,
  Play,
  Square,
  RefreshCw,
  WifiOff,
  Eye,
  Image as ImageIcon,
  PlayCircle,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { StatusBadge, RecordingIndicator } from "./StatusBadge";
import { WebRTCPlayer } from "./WebRTCPlayer";
import { getStreamUrls } from "../../api/cameras";
import { Button } from "../ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";
import useLicense from "../../hooks/useLicense";

/**
 * Camera Card Component
 * Displays a single camera with status, controls, and recording indicator.
 * Can toggle between thumbnail and live stream view.
 */
export const CameraCard = ({
  camera,
  onClick,
  onStartRecording,
  onStopRecording,
  onTestConnection,
  onSettings,
  onFullscreen,
  onInstantPlayback, // new — called with (camera) to jump to live playback
  isLoading = false,
  showLiveByDefault = false,
  className,
  // When true the card fills its parent height instead of forcing a
  // 16:9 aspect ratio. Used by CameraGrid which gives each tile a
  // fixed slice of the viewport so all cells stay equal size.
  fitParent = false,
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const [showLive, setShowLive] = useState(showLiveByDefault);
  const [isRegisteringStream, setIsRegisteringStream] =
    useState(showLiveByDefault);
  const [streamRegistered, setStreamRegistered] = useState(false);
  const [liveStreamId, setLiveStreamId] = useState(null);

  const isOnline = camera.status === "online";
  const isRecording = camera.is_recording;
  const isEnabled = camera.is_enabled;
  const { hasFeature } = useLicense();
  const canRecord = hasFeature("recording");
  const canPlayback = hasFeature("playback");

  // Get thumbnail URL from API - thumbnail_path already contains /thumbnails/camera_id/snapshot.jpg
  const API_BASE = process.env.REACT_APP_BACKEND_URL || "";
  const thumbnailUrl = camera.thumbnail_path
    ? `${API_BASE}${camera.thumbnail_path}`
    : null;

  // Register camera with go2rtc when live view is toggled
  useEffect(() => {
    let mounted = true;

    const registerStream = async () => {
      if (showLive && isOnline) {
        setIsRegisteringStream(true);
        try {
          const streamUrls = await getStreamUrls(camera.id);
          if (mounted) {
            // Use the live_stream_id returned by backend (sub stream if available)
            setLiveStreamId(streamUrls.live_stream_id || camera.id);
            setStreamRegistered(true);
            setIsRegisteringStream(false);
          }
        } catch (error) {
          if (mounted) {
            // Still allow player to try even if registration fails
            setLiveStreamId(camera.id);
            setStreamRegistered(true);
            setIsRegisteringStream(false);
          }
        }
      }
    };

    registerStream();

    return () => {
      mounted = false;
    };
  }, [showLive, isOnline, camera.id]);

  // Toggle between live stream and thumbnail
  const handleToggleLive = (e) => {
    e.stopPropagation();
    const next = !showLive;
    if (!next) {
      setStreamRegistered(false);
      setLiveStreamId(null);
    }
    setShowLive(next);
  };

  return (
    <div
      data-testid={`camera-card-${camera.id}`}
      className={cn(
        "relative overflow-hidden rounded-lg border border-border bg-black group",
        "hover:ring-2 hover:ring-[var(--console-accent)] transition-all duration-200",
        !isEnabled && "opacity-60",
        // When fitParent the card stretches to its grid cell; otherwise
        // it keeps a 16:9 aspect so tile flows naturally in column layouts.
        fitParent && "h-full w-full flex flex-col",
        className,
      )}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={() => onClick?.(camera)}
    >
      {/* Video Feed / Placeholder */}
      <div
        className={cn(
          "relative",
          fitParent ? "flex-1 min-h-0" : "aspect-video",
        )}
      >
        {isOnline &&
        showLive &&
        streamRegistered &&
        !isRegisteringStream &&
        liveStreamId ? (
          // Live Stream View (WebRTC via go2rtc)
          <WebRTCPlayer
            streamId={liveStreamId}
            cameraId={camera.id}
            autoPlay={true}
            muted={true}
            controls={false}
            className="w-full h-full"
          />
        ) : isOnline && thumbnailUrl && !showLive ? (
          // Thumbnail View
          <img
            src={thumbnailUrl}
            alt={camera.name}
            className="w-full h-full object-cover"
            onError={(e) => {
              // Fallback to camera icon if thumbnail fails to load
              e.target.style.display = "none";
              e.target.nextSibling.style.display = "flex";
            }}
          />
        ) : null}
        <div
          className="w-full h-full flex items-center justify-center"
          style={{
            backgroundColor: "var(--console-panel)",
            display:
              isOnline &&
              ((thumbnailUrl && !showLive) ||
                (showLive && streamRegistered && !isRegisteringStream))
                ? "none"
                : "flex",
          }}
        >
          <div className="text-center text-muted-foreground">
            {isRegisteringStream ? (
              <>
                <RefreshCw className="h-12 w-12 mx-auto mb-2 opacity-50 animate-spin" />
                <p className="text-sm">Starting Stream...</p>
              </>
            ) : isOnline ? (
              <>
                <Camera className="h-12 w-12 mx-auto mb-2 opacity-50" />
                <p className="text-sm">Loading Preview...</p>
              </>
            ) : (
              <>
                <WifiOff className="h-12 w-12 mx-auto mb-2 opacity-50" />
                <p className="text-sm">No Signal</p>
              </>
            )}
          </div>
        </div>

        {/* Loading Overlay */}
        {isLoading && (
          <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
            <RefreshCw className="h-8 w-8 text-white animate-spin" />
          </div>
        )}

        {/* Top Status Bar */}
        <div className="absolute top-0 left-0 right-0 p-2 flex justify-between items-start">
          {/* Recording Indicator */}
          <RecordingIndicator isRecording={isRecording} />

          {/* Status Badge */}
          <StatusBadge
            status={camera.status}
            showIcon={false}
            className="bg-black/60 backdrop-blur-sm text-white border-transparent"
          />
        </div>

        {/* Bottom Info Bar */}
        <div className="absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/80 to-transparent">
          <h3 className="text-white font-medium text-sm truncate">
            {camera.name}
          </h3>
          {camera.location && (
            <p className="text-white/70 text-xs truncate">{camera.location}</p>
          )}
          {isOnline && camera.resolution && (
            <p className="text-white/50 text-xs mt-1">
              {camera.resolution} • {camera.fps}fps
            </p>
          )}
        </div>

        {/* Hover Controls */}
        {isHovered && (
          <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px] flex items-center justify-center gap-2 transition-opacity">
            <TooltipProvider>
              {/* Live/Thumbnail Toggle */}
              {isOnline && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      data-testid={`camera-${camera.id}-view-toggle`}
                      size="icon"
                      variant="ghost"
                      className="h-10 w-10 bg-white/10 hover:bg-white/20 text-white"
                      onClick={handleToggleLive}
                      disabled={isLoading}
                    >
                      {showLive ? (
                        <ImageIcon className="h-5 w-5" />
                      ) : (
                        <Eye className="h-5 w-5" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {showLive ? "Show Thumbnail" : "View Live"}
                  </TooltipContent>
                </Tooltip>
              )}

              {/* Recording Toggle */}
              {canRecord && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      data-testid={`camera-${camera.id}-recording-toggle`}
                      size="icon"
                      variant="ghost"
                      className="h-10 w-10 bg-white/10 hover:bg-white/20 text-white"
                      onClick={(e) => {
                        e.stopPropagation();
                        isRecording
                          ? onStopRecording?.(camera)
                          : onStartRecording?.(camera);
                      }}
                      disabled={!isOnline || isLoading}
                    >
                      {isRecording ? (
                        <Square className="h-5 w-5 fill-current" />
                      ) : (
                        <Video className="h-5 w-5" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {isRecording ? "Stop Recording" : "Start Recording"}
                  </TooltipContent>
                </Tooltip>
              )}

              {/* Test Connection */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    data-testid={`camera-${camera.id}-test-connection`}
                    size="icon"
                    variant="ghost"
                    className="h-10 w-10 bg-white/10 hover:bg-white/20 text-white"
                    onClick={(e) => {
                      e.stopPropagation();
                      onTestConnection?.(camera);
                    }}
                    disabled={isLoading}
                  >
                    <RefreshCw
                      className={cn("h-5 w-5", isLoading && "animate-spin")}
                    />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Test Connection</TooltipContent>
              </Tooltip>

              {/* Instant Playback */}
              {isRecording && canPlayback && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      data-testid={`camera-${camera.id}-instant-playback`}
                      size="icon"
                      variant="ghost"
                      className="h-10 w-10 bg-white/10 hover:bg-white/20 text-white"
                      onClick={(e) => {
                        e.stopPropagation();
                        onInstantPlayback?.(camera);
                      }}
                    >
                      <PlayCircle className="h-5 w-5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Instant Playback</TooltipContent>
                </Tooltip>
              )}

              {/* Fullscreen */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    data-testid={`camera-${camera.id}-fullscreen`}
                    size="icon"
                    variant="ghost"
                    className="h-10 w-10 bg-white/10 hover:bg-white/20 text-white"
                    onClick={(e) => {
                      e.stopPropagation();
                      onFullscreen?.(camera);
                    }}
                    disabled={!isOnline}
                  >
                    <Maximize2 className="h-5 w-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Fullscreen</TooltipContent>
              </Tooltip>

              {/* Settings */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    data-testid={`camera-${camera.id}-settings`}
                    size="icon"
                    variant="ghost"
                    className="h-10 w-10 bg-white/10 hover:bg-white/20 text-white"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSettings?.(camera);
                    }}
                  >
                    <Settings className="h-5 w-5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Settings</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        )}
      </div>
    </div>
  );
};

// Wrap with memo to prevent unnecessary re-renders when parent re-renders
// CameraCard only re-renders when its own props change
export const MemoizedCameraCard = memo(CameraCard);
export default MemoizedCameraCard;
