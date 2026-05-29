import { LAYOUTS, slotCount, gridStyle } from "./videoWall";

test("LAYOUTS are the supported wall sizes", () => {
  expect(LAYOUTS).toEqual([1, 4, 6, 8, 9, 16, 25]);
});

test("slotCount returns the layout value when valid", () => {
  expect(slotCount(9)).toBe(9);
});

test("slotCount falls back to 4 for an unsupported value", () => {
  expect(slotCount(7)).toBe(4);
  expect(slotCount(undefined)).toBe(4);
});

test("gridStyle produces a square-ish grid template", () => {
  expect(gridStyle(9).gridTemplateColumns).toBe("repeat(3, 1fr)");
  expect(gridStyle(16).gridTemplateColumns).toBe("repeat(4, 1fr)");
  expect(gridStyle(6).gridTemplateColumns).toBe("repeat(3, 1fr)");
  expect(gridStyle(8).gridTemplateColumns).toBe("repeat(3, 1fr)");
});
