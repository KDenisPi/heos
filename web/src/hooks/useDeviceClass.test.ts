import { describe, expect, it } from "vitest";
import { classify } from "./useDeviceClass";

describe("classify", () => {
  it("treats the Samsung Tab as a tablet in both orientations", () => {
    expect(classify(1280, 800)).toEqual({ phone: false, landscape: true });
    expect(classify(800, 1280)).toEqual({ phone: false, landscape: false });
  });
  it("treats a phone as a phone in both orientations", () => {
    expect(classify(412, 915)).toEqual({ phone: true, landscape: false });
    expect(classify(915, 412)).toEqual({ phone: true, landscape: true });
  });
});
