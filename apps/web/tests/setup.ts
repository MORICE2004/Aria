/**
 * Test setup, run before every test file.
 *
 * Two jobs: load the DOM matchers, and reset the browser state that leaks
 * between tests. localStorage holds the login token and jsdom keeps it for the
 * whole file, so a test that logs in would silently authenticate the next one.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
});
