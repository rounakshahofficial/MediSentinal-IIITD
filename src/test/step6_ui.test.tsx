import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "@/App";

function openTab(name: string) {
  fireEvent.click(screen.getByRole("tab", { name: new RegExp(`^${name}`) }));
}

afterEach(() => {
  vi.useRealTimers();
});

describe("MediSentinel self-contained regulator demo", () => {
  it("explains the product in the overview with demo disclosure, counts, formulas and chart", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Compliance overview" })).toBeInTheDocument();
    expect(screen.getAllByText("Demo data").length).toBeGreaterThan(0);
    expect(screen.getByText("24 = 8 listings × 3 sites")).toBeInTheDocument();
    expect(screen.getByText("5 / 19 matched = 26.3%")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Bar chart of potential discrepancies by pharmacy site" }),
    ).toBeInTheDocument();
  });

  it("runs the five-stage mock scan timeline without making a network request", () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<App />);
    openTab("Scan");

    expect(screen.getByLabelText("Medicine family")).toHaveValue("Atorvastatin");
    fireEvent.click(screen.getByRole("button", { name: "Start scan" }));
    expect(screen.getByText("Scan in progress")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(3_500);
    });
    expect(screen.getByText("Demo scan complete")).toBeInTheDocument();
    expect(screen.getByText("Case created")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("supports photo upload review and editable extracted fields on the Photo Check tab", async () => {
    const user = userEvent.setup();
    render(<App />);
    openTab("Photo Check");

    expect(screen.getByAltText(/Demo Atorva medicine pack/)).toBeInTheDocument();
    const ingredient = screen.getByLabelText(/Ingredient/);
    await user.clear(ingredient);
    await user.type(ingredient, "Atorvastatin calcium");
    expect(ingredient).toHaveValue("Atorvastatin calcium");
    expect(screen.getByText("Photo check result")).toBeInTheDocument();
    expect(screen.getByText(/₹79.50 ÷ 10 = ₹7.95/)).toBeInTheDocument();
  });

  it("renders a responsive, sortable queue with explainable priority scores", async () => {
    const user = userEvent.setup();
    render(<App />);
    openTab("Case Queue");

    expect(screen.getByText("Reviewer queue")).toBeInTheDocument();
    expect(screen.getAllByText("MS-1042").length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText("Why this priority score").length).toBeGreaterThan(0);
    await user.selectOptions(screen.getByLabelText("Sort cases by"), "site");
    expect(screen.getByLabelText("Sort cases by")).toHaveValue("site");
    expect(screen.getAllByText("Potential discrepancy").length).toBeGreaterThan(0);
  });

  it("shows field-level checks, warnings and a safe calculation stop", () => {
    render(<App />);
    openTab("Match Check");

    expect(screen.getByText("Required-field comparison")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Fields agree").length).toBe(2);
    expect(screen.getByLabelText("Fields do not agree")).toBeInTheDocument();
    expect(screen.getByLabelText("Field needs verification")).toBeInTheDocument();
    expect(screen.getByText("Calculation stopped safely")).toBeInTheDocument();
  });

  it("shows a complete dossier and records all three local reviewer actions", async () => {
    const user = userEvent.setup();
    render(<App />);
    openTab("Dossier");

    expect(screen.getByAltText(/Demo screenshot of the Tata 1mg/)).toBeInTheDocument();
    expect(screen.getByText("Plain-language calculation")).toBeInTheDocument();
    expect(screen.getByText("Repeat observation history")).toBeInTheDocument();
    expect(screen.getByText(/₹5.71 × \(1 \+ 12 ÷ 100\)/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Need more evidence" }));
    expect(screen.getByRole("status")).toHaveTextContent("Need more evidence");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.getByRole("status")).toHaveTextContent("Dismissed");
    await user.click(screen.getByRole("button", { name: "Confirm for review" }));
    expect(screen.getByRole("status")).toHaveTextContent("Confirmed for review");
  });

  it("includes selectable loading, empty and error states with recovery actions", async () => {
    const user = userEvent.setup();
    render(<App />);
    const stateSelect = screen.getByLabelText("Preview state");

    await user.selectOptions(stateSelect, "loading");
    expect(screen.getByText("Loading demo records")).toBeInTheDocument();

    await user.selectOptions(stateSelect, "empty");
    expect(screen.getByText("No demo records in this view")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Restore demo data" }));

    await user.selectOptions(stateSelect, "error");
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(screen.getByRole("heading", { name: "Compliance overview" })).toBeInTheDocument();
  });
});
