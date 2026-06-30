// =============================================================================
// Go2RTC Embed Player — embeds go2rtc's OWN built-in player (stream.html) in an
// iframe instead of re-implementing WebRTC/MSE in the browser.
// =============================================================================
// go2rtc ships a robust player at /go2rtc/stream.html?src=<streamId> that does
// WebRTC with an automatic MSE fallback. Our hand-rolled WebRTCPlayer / Go2RTCPlayer
// hit ICE/mDNS issues (cross-subnet) and MSE codec/buffer races; the built-in player
// handles all of that. It's served through the nginx /go2rtc/ proxy, so it works
// same-origin (no CORS) and across subnets over plain HTTP/WS.
// =============================================================================

import React from "react";
import { cn } from "../../lib/utils";

// Mirrors the WebRTCPlayer/Go2RTCPlayer prop surface so it's a drop-in replacement
// everywhere (NVR grid, Live page, camera detail, AI scenario Live tabs). Props that
// only made sense for the hand-rolled player (cameraId, onError, onPlay, controls…)
// are accepted and ignored — the embedded go2rtc player manages its own lifecycle.
export const Go2RTCEmbedPlayer = ({ streamId, className, controls = false }) => {
  const base = process.env.REACT_APP_GO2RTC_URL || "/go2rtc";
  // stream.html lives at the go2rtc ROOT (not under /api). go2rtc query params:
  //   mode=mse → MSE only (fMP4 over a WebSocket, all TCP). Chosen over webrtc/auto
  //     for TWO reasons:
  //     1. It works EVERYWHERE the page loads — MSE rides the same TCP/WS the app
  //        already uses, so it crosses subnets / proxies (the client's Windows box on
  //        a different subnet) where WebRTC's UDP/ICE host candidates can't pair.
  //     2. It's quiet — go2rtc's default webrtc,mse races both transports and tears
  //        the loser down mid-connect, spamming the console with AbortError /
  //        "SourceBuffer removed" (video-rtc.js). MSE-only never starts that race.
  //     Trade-off vs WebRTC: ~1-2s more latency. Fine for surveillance monitoring.
  //   muted → autoplay-friendly tile; controls follows the caller (grid tiles pass
  //     controls=false → no chrome; detail/AI views may want the scrubber).
  const src = streamId
    ? `${base}/stream.html?src=${encodeURIComponent(streamId)}&mode=mse&muted=1&controls=${controls ? 1 : 0}`
    : null;

  if (!src) {
    return (
      <div className={cn("w-full h-full bg-black flex items-center justify-center", className)}>
        <span className="text-[10px] text-zinc-600">No stream</span>
      </div>
    );
  }

  return (
    <iframe
      key={streamId}
      title={`stream-${streamId}`}
      src={src}
      className={cn("w-full h-full border-0 bg-black", className)}
      allow="autoplay; fullscreen"
      // No sandbox attribute: the player is served same-origin from our own nginx
      // /go2rtc/ proxy, so it is fully trusted. (allow-scripts + allow-same-origin
      // together defeats the sandbox anyway and only emits a console warning.)
      scrolling="no"
    />
  );
};

export default Go2RTCEmbedPlayer;
