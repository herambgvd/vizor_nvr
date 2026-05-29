import { LAYOUTS, slotCount, gridStyle, fitLayout, tourPages } from "./videoWall";

test("LAYOUTS are the supported wall sizes", () => {
  expect(LAYOUTS).toEqual([1, 4, 6, 8, 9, 16, 25, 36, 49, 64]);
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
  expect(gridStyle(64).gridTemplateColumns).toBe("repeat(8, 1fr)");
  expect(gridStyle(36).gridTemplateColumns).toBe("repeat(6, 1fr)");
});

test("fitLayout picks the smallest layout that holds n cameras", () => {
  expect(fitLayout(1)).toBe(1);
  expect(fitLayout(3)).toBe(4);
  expect(fitLayout(10)).toBe(16);
  expect(fitLayout(40)).toBe(49);
  expect(fitLayout(64)).toBe(64);
});

test("fitLayout caps at the largest layout and handles empty input", () => {
  expect(fitLayout(100)).toBe(64);
  expect(fitLayout(0)).toBe(1);
  expect(fitLayout(undefined)).toBe(1);
});

test("tourPages splits cameras into padded pages of the layout size", () => {
  const ids = ["a", "b", "c", "d", "e"];
  const pages = tourPages(ids, 4);
  expect(pages).toEqual([
    ["a", "b", "c", "d"],
    ["e", null, null, null],
  ]);
});

test("tourPages yields a single page when cameras fit the layout", () => {
  expect(tourPages(["a", "b"], 4)).toEqual([["a", "b", null, null]]);
});

test("tourPages returns no pages for empty input", () => {
  expect(tourPages([], 9)).toEqual([]);
  expect(tourPages(undefined, 9)).toEqual([]);
});

test("tourPages ignores falsy ids and uses fallback slot size", () => {
  // unsupported layout falls back to 4 slots
  expect(tourPages(["a", null, "b"], 7)).toEqual([["a", "b", null, null]]);
});
