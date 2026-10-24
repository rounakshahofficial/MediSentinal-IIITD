import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppShell } from "../components/AppShell";
import type { Screen } from "../types";

function Harness() {
  const [active, setActive] = useState<Screen>("overview");
  return <AppShell screen={active} demoState="ready" queueCount={7} onScreenChange={setActive} onDemoStateChange={() => undefined}><p>Panel body</p></AppShell>;
}

describe("AppShell tab accessibility", () => {
  it("links the selected tab to its tab panel and exposes a skip link", () => {
    render(<Harness />);
    const tab = screen.getByRole("tab", { name: "Overview" });
    const panel = screen.getByRole("tabpanel");
    expect(tab).toHaveAttribute("aria-controls", "panel-overview");
    expect(panel).toHaveAttribute("id", "panel-overview");
    expect(panel).toHaveAttribute("aria-labelledby", "tab-overview");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main-content");
  });

  it("uses roving tabindex and supports Arrow, Home, and End navigation", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Scan" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Scan" })).toHaveAttribute("tabindex", "0");
    expect(overview).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("heading", { name: "Start a compliance scan" })).toHaveFocus();

    screen.getByRole("tab", { name: "Scan" }).focus();
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Dossier" })).toHaveAttribute("aria-selected", "true");

    screen.getByRole("tab", { name: "Dossier" }).focus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  });
});
