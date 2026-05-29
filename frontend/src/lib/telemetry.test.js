import { fmtPct, fmtBytes, fmtBitrate } from "./telemetry";

test("fmtPct clamps and rounds to whole percent", () => {
  expect(fmtPct(0.1234, true)).toBe("12%");
  expect(fmtPct(57.6)).toBe("58%");
  expect(fmtPct(-5)).toBe("0%");
  expect(fmtPct(140)).toBe("100%");
  expect(fmtPct(null)).toBe("—");
});

test("fmtBytes renders human units", () => {
  expect(fmtBytes(0)).toBe("0 B");
  expect(fmtBytes(1024)).toBe("1.0 KB");
  expect(fmtBytes(1536)).toBe("1.5 KB");
  expect(fmtBytes(1048576)).toBe("1.0 MB");
  expect(fmtBytes(null)).toBe("—");
});

test("fmtBitrate renders kbps/Mbps", () => {
  expect(fmtBitrate(800)).toBe("800 kbps");
  expect(fmtBitrate(4500)).toBe("4.5 Mbps");
  expect(fmtBitrate(null)).toBe("—");
});
