#!/usr/bin/env bash
# =============================================================================
# FRS 64-camera load-test harness.
#
# Simulates N camera streams by fan-out-looping a sample video into go2rtc as
# RTSP sources, lets the FRS plugin analyse them, and samples pipeline + system
# metrics (events/sec, Triton model stats, GPU/CPU/mem) over a window.
#
# Usage:
#   scripts/frs_loadtest.sh <num_cameras> <duration_sec> [sample.mp4]
# Example (Monday, on the 5070):
#   scripts/frs_loadtest.sh 64 300 /data/recordings/sample_faces.mp4
#
# Prereqs: go2rtc reachable (gvd_go2rtc), Triton up, FRS up, a sample video that
# contains faces. The script does NOT clean up cameras in the NVR — it only
# pushes RTSP sources + samples metrics, so it's safe to re-run.
# =============================================================================
set -euo pipefail

N="${1:-8}"
DURATION="${2:-120}"
SAMPLE="${3:-/data/recordings/sample.mp4}"
GO2RTC="${GO2RTC_HOST:-localhost:1984}"     # go2rtc API
INTERVAL=10                                  # metrics sample interval (s)

echo "=== FRS load test: ${N} cameras, ${DURATION}s, sample=${SAMPLE} ==="

# 1. Register N looping RTSP publishers in go2rtc (loadtest_0 .. loadtest_{N-1}).
#    Each is the sample video looped forever via ffmpeg, exposed as an RTSP src.
echo "--- registering ${N} synthetic streams in go2rtc ---"
for i in $(seq 0 $((N-1))); do
  name="loadtest_${i}"
  # go2rtc 'exec' source: ffmpeg loops the sample → RTSP-readable stream.
  src="ffmpeg:${SAMPLE}#input=file#loop#video=h264"
  curl -fsS -X PUT "http://${GO2RTC}/api/streams?name=${name}&src=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$src")" \
    >/dev/null 2>&1 && echo "  + ${name}" || echo "  ! ${name} (already exists / go2rtc err)"
done

echo "--- NOTE: assign these loadtest_* cameras to FRS via the Cameras tab (or"
echo "    the NVR API) so workers spin up. This harness only generates load +"
echo "    samples metrics; camera assignment is a deliberate manual gate. ---"

# 2. Sample metrics over the window.
echo "--- sampling metrics every ${INTERVAL}s for ${DURATION}s ---"
samples=$((DURATION / INTERVAL))
printf "%-8s %-10s %-10s %-12s %-10s %-10s\n" "t(s)" "gpu_util%" "gpu_mem" "cpu%" "frs_mem" "events"
for s in $(seq 1 "$samples"); do
  t=$((s * INTERVAL))
  gpu=$(docker exec gvd_ai_triton nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  gpu_util="${gpu%%,*}"; gpu_mem="${gpu##*,}"
  cpu=$(docker stats --no-stream --format '{{.CPUPerc}}' gvd_ai_frs 2>/dev/null | tr -d '%')
  mem=$(docker stats --no-stream --format '{{.MemUsage}}' gvd_ai_frs 2>/dev/null | awk '{print $1}')
  # FRS events in the last interval (rough throughput signal).
  events=$(docker exec gvd_ai_frs_db psql -U frs -d frs -tA -c \
    "SELECT count(*) FROM frs_events WHERE triggered_at > now() - interval '${INTERVAL} seconds';" 2>/dev/null | tr -d ' ' || echo "?")
  printf "%-8s %-10s %-10s %-12s %-10s %-10s\n" "$t" "${gpu_util:-?}" "${gpu_mem:-?}" "${cpu:-?}" "${mem:-?}" "${events:-?}"
  sleep "$INTERVAL"
done

# 3. Triton per-model inference stats (success count + queue/compute latency).
echo "--- Triton model stats (cumulative) ---"
for m in scrfd_10g arcface_r50 fairface antispoofing; do
  docker exec gvd_ai_triton curl -fsS "http://localhost:8000/v2/models/${m}/stats" 2>/dev/null \
    | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)['model_stats'][0]['inference_stats']
    succ=d.get('success',{}).get('count',0)
    comp=d.get('compute_infer',{})
    n=comp.get('count',1) or 1
    print(f\"  ${m}: success={succ} avg_compute_us={int(comp.get('ns',0)/1000/n)}\")
except Exception as e:
    print(f'  ${m}: stats unavailable')" || echo "  ${m}: stats unavailable"
done

echo "=== load test complete ==="
echo "Cleanup synthetic streams: for i in \$(seq 0 $((N-1))); do curl -X DELETE \"http://${GO2RTC}/api/streams?name=loadtest_\${i}\"; done"
