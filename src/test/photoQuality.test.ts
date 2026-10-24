import { describe, expect, it } from "vitest";
import { averageBrightness, qualityFromGrayscale, varianceOfLaplacian } from "../lib/photoQuality";

describe("photo quality checks", () => {
  it("measures average grayscale brightness", () => {
    expect(averageBrightness(new Uint8ClampedArray([0, 50, 100, 250]))).toBe(100);
  });

  it("assigns zero Laplacian variance to a flat, blurry image", () => {
    const flat = new Uint8ClampedArray(25).fill(120);
    expect(varianceOfLaplacian(flat, 5, 5)).toBe(0);
    expect(qualityFromGrayscale(flat, 5, 5).isBlurry).toBe(true);
  });

  it("recognizes high-frequency edges as sharper than a flat image", () => {
    const checkerboard = new Uint8ClampedArray([
      0, 255, 0, 255, 0,
      255, 0, 255, 0, 255,
      0, 255, 0, 255, 0,
      255, 0, 255, 0, 255,
      0, 255, 0, 255, 0,
    ]);
    expect(varianceOfLaplacian(checkerboard, 5, 5)).toBeGreaterThan(100);
    expect(qualityFromGrayscale(checkerboard, 5, 5).isBlurry).toBe(false);
  });

  it("warns for dark images and reports measured values", () => {
    const dark = new Uint8ClampedArray(25).fill(20);
    const result = qualityFromGrayscale(dark, 5, 5);
    expect(result.isDark).toBe(true);
    expect(result.brightness).toBe(20);
    expect(result.blurScore).toBe(0);
  });

  it("returns a safe blur score for invalid tiny dimensions", () => {
    expect(varianceOfLaplacian(new Uint8ClampedArray([100]), 1, 1)).toBe(0);
  });
});
