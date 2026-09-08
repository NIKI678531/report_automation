// @vitest-environment jsdom
import { StrictMode } from "react";
import { cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import RemoteApp from "./RemoteApp";
import { api } from "./api";
import { artifactUrl } from "./remoteConfig";

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

it("keeps host history/language untouched and cleans up on strict-mode unmount", async () => {
  vi.spyOn(api, "listReports").mockResolvedValue([]);
  vi.spyOn(api, "listProducts").mockResolvedValue([]);
  window.history.replaceState({ host: true, idx: 3 }, "", "/fund-cmt-auto?host=1#host");
  document.documentElement.lang = "fr";
  const hostState = window.history.state;
  const view = render(<StrictMode><RemoteApp /></StrictMode>);
  const shadow = view.container.querySelector("[data-fund-cmt-auto]")!.shadowRoot!;
  const remote = within(shadow as unknown as HTMLElement);
  await remote.findByRole("heading", { name: "Report center" });
  expect(view.container.querySelector("h1")).toBeNull();
  fireEvent.change(remote.getByLabelText("Language"), { target: { value: "zh-Hans" } });
  await waitFor(() => expect(localStorage.getItem("commentary.locale")).toBe("zh-Hans"));
  expect(document.documentElement.lang).toBe("fr");
  expect(window.location.pathname + window.location.search + window.location.hash).toBe("/fund-cmt-auto?host=1#host");
  expect(window.history.state).toEqual(hostState);
  expect(document.querySelectorAll("[data-fund-cmt-fonts]")).toHaveLength(1);
  view.unmount();
  expect(document.querySelectorAll("[data-fund-cmt-fonts]")).toHaveLength(0);
  expect(document.documentElement.lang).toBe("fr");
});

it("preserves the signed download query and refuses off-site download URLs", () => {
  const signed = "/api/v1/artifacts/a/content?expires=123&signature=a%2Bb%3D";
  expect(artifactUrl(signed)).toBe(`/remote/fund-cmt-auto${signed}`);
  for (const url of ["https://example.com/file", "//example.com/file", "/api/v1/reports"]) {
    expect(() => artifactUrl(url)).toThrow("Invalid artifact download URL");
  }
});
