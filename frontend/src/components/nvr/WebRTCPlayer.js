// =============================================================================
// WebRTCPlayer — compatibility shim.
// =============================================================================
// The hand-rolled WebRTC/MSE player this file used to hold hit ICE/mDNS host-
// candidate failures across subnets (client on a different subnet than the server)
// and MSE codec/buffer races. It is replaced everywhere by Go2RTCEmbedPlayer, which
// embeds go2rtc's OWN robust player (stream.html, mode=mse over TCP/WS through the
// nginx /go2rtc/ proxy) — works same-LAN and cross-subnet, console-clean.
//
// This file stays as a re-export so every existing import
//   import { WebRTCPlayer } from ".../components/nvr/WebRTCPlayer"
// (NVR grid, Live page, Events, camera detail, AND the AI scenario Live tabs)
// transparently uses the embedded player with no call-site changes.
//
// The original implementation is preserved in WebRTCPlayer.legacy.js.bak.
// =============================================================================

export { Go2RTCEmbedPlayer as WebRTCPlayer } from "./Go2RTCEmbedPlayer";
export { Go2RTCEmbedPlayer as default } from "./Go2RTCEmbedPlayer";
