import {
  DAY_SECONDS,
  MIN_SPAN,
  parseUtc,
  dayOffset,
  fmtClock,
  clampView,
  timeToPct,
  pctToTime,
  segmentBars,
  eventTicks,
  zoomView,
  chooseStep,
  gridTicks,
} from "./timeline";

const DATE = "2026-05-29";
const view = { start: 0, end: DAY_SECONDS };

test("parseUtc appends Z to naive timestamps", () => {
  expect(parseUtc("2026-05-29T01:00:00").getTime()).toBe(
    new Date("2026-05-29T01:00:00Z").getTime(),
  );
});

test("dayOffset advances one hour for a one-hour-later timestamp", () => {
  const a = dayOffset("2026-05-29T04:00:00", DATE);
  const b = dayOffset("2026-05-29T05:00:00", DATE);
  expect(b - a).toBe(3600);
});

test("fmtClock formats seconds-since-midnight as HH:MM:SS", () => {
  expect(fmtClock(3661)).toBe("01:01:01");
  expect(fmtClock(0)).toBe("00:00:00");
});

test("clampView enforces the minimum span", () => {
  const v = clampView({ start: 1000, end: 1100 });
  expect(v.end - v.start).toBeCloseTo(MIN_SPAN);
});

test("clampView keeps the window inside the day", () => {
  const v = clampView({ start: 86000, end: 90000 });
  expect(v.end).toBe(DAY_SECONDS);
  expect(v.start).toBeCloseTo(DAY_SECONDS - 4000);
});

test("timeToPct/pctToTime are inverse", () => {
  expect(timeToPct(0, view)).toBe(0);
  expect(timeToPct(DAY_SECONDS, view)).toBe(100);
  expect(pctToTime(timeToPct(3600, view), view)).toBeCloseTo(3600);
});

test("segmentBars positions and clips a recording segment", () => {
  const off = dayOffset("2026-05-29T10:00:00", DATE);
  const segs = [{ id: "a", start_time: "2026-05-29T10:00:00", duration: 3600 }];
  const bars = segmentBars(segs, view, DATE);
  expect(bars).toHaveLength(1);
  expect(bars[0].id).toBe("a");
  expect(bars[0].left).toBeCloseTo(timeToPct(off, view));
  expect(bars[0].width).toBeCloseTo(
    timeToPct(off + 3600, view) - timeToPct(off, view),
  );
  expect(segmentBars(segs, { start: off + 7200, end: off + 10000 }, DATE)).toHaveLength(0);
});

test("eventTicks positions in-view events and drops out-of-view ones", () => {
  const off = dayOffset("2026-05-29T10:00:00", DATE);
  const events = [
    { id: "e1", triggered_at: "2026-05-29T10:00:00", severity: "alarm", event_type: "motion_detected" },
  ];
  const ticks = eventTicks(events, view, DATE);
  expect(ticks).toHaveLength(1);
  expect(ticks[0].severity).toBe("alarm");
  expect(ticks[0].left).toBeCloseTo(timeToPct(off, view));
  expect(eventTicks(events, { start: off + 10, end: off + 20 }, DATE)).toHaveLength(0);
});

test("zoomView zooms in around an anchor and clamps to MIN_SPAN", () => {
  const z = zoomView(view, 0.5, 43200);
  expect(z.end - z.start).toBeCloseTo(43200);
  expect((z.start + z.end) / 2).toBeCloseTo(43200);
  const zin = zoomView(view, 0.0001, 43200);
  expect(zin.end - zin.start).toBeCloseTo(MIN_SPAN);
});

test("chooseStep picks a readable tick step for the span", () => {
  expect(chooseStep(DAY_SECONDS)).toBe(7200);
  expect(chooseStep(3600)).toBe(300);
  expect(chooseStep(MIN_SPAN)).toBe(60);
});

test("gridTicks spans the viewport with HH:MM labels", () => {
  const ticks = gridTicks(view);
  expect(ticks[0]).toMatchObject({ t: 0, label: "00:00" });
  expect(ticks.some((x) => x.label === "12:00")).toBe(true);
});
