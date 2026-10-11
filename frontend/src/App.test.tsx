/** Integration test: renders the real App against the LIVE FastAPI backend (http://localhost:8000).
 *  Runs in jsdom (not a real browser). Start the backend first. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";
import { API_BASE_URL } from "./api/client";

const T = { timeout: 25000 };

describe("App against live backend", () => {
  it("shows connection status and values that match the backend response", async () => {
    render(<App />);
    expect(await screen.findByText("API connected", {}, T)).toBeTruthy();
    await screen.findByText("Predicted passengers", {}, T);
    // the KPI number must equal the sum of totals from a direct API call with the same default params
    const fest = (await (await fetch(`${API_BASE_URL}/api/festivals`)).json()).festivals.find((f: any) => f.split_role === "test");
    const day = fest.days[3];
    const origin = day.slots.find((s: string) => s.slice(11, 16) === "21:00") ?? day.slots[0];
    const direct = await (await fetch(`${API_BASE_URL}/api/predict`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ festival_id: fest.festival_id, forecast_origin: origin, horizon_steps: 8 }) })).json();
    const total = Math.round(direct.totals_by_step.reduce((a: number, s: any) => a + s.predicted_demand, 0));
    const kpi = screen.getByText("Predicted passengers").closest("div")!;
    expect(within(kpi).getByText(total.toLocaleString("en-US"))).toBeTruthy();
    expect(await screen.findByText(/ADVISORY ONLY/, {}, T)).toBeTruthy();
    expect(await screen.findByText(/human dispatcher must review/i, {}, T)).toBeTruthy();
  }, 60000);

  it("filters, simulates and asks the assistant (demo mode)", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Predicted passengers", {}, T);
    const rows = () => screen.getAllByRole("row").length;
    const all = rows();
    await user.click(screen.getByLabelText("High only"));
    await waitFor(() => expect(rows()).toBeLessThan(all), T);
    await user.click(screen.getByLabelText("All"));
    // what-if
    const run = screen.getByRole("button", { name: "Run simulation" }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "S06" }));
    expect(run.disabled).toBe(false);
    await user.click(run);
    expect(await screen.findByText(/not verified real-world outcomes/i, {}, T)).toBeTruthy();
    expect(screen.getByText("Scenario (simulated)", { selector: "th" })).toBeTruthy();
    // assistant
    await user.type(screen.getByLabelText("Message to assistant"), "Where should buses move?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/Demo mode · rule-based, not an LLM/, {}, T)).toBeTruthy();
    expect(await screen.findByText(/used get_deployment_recommendations/, {}, T)).toBeTruthy();
  }, 90000);

  it("generates an AI shift briefing (template in demo mode)", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Predicted passengers", {}, T);
    await user.click(screen.getByRole("button", { name: /Generate briefing/ }));
    expect(await screen.findByText(/Template · not an LLM|AI · /, {}, T)).toBeTruthy();
    expect(await screen.findByText("Highest-risk stops", {}, T)).toBeTruthy();
  }, 60000);

  it("drafts multilingual announcements and logs a dispatch approval", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Predicted passengers", {}, T);
    await user.click(screen.getByRole("button", { name: /Draft announcements/ }));
    expect(await screen.findByText("Hindi", { selector: "b" }, T)).toBeTruthy();
    expect(await screen.findByText("Tamil", { selector: "b" }, T)).toBeTruthy();
    const approves = await screen.findAllByRole("button", { name: "Approve" }, T);
    await user.click(approves[0]);
    expect(await screen.findByText(/DSP-001/, {}, T)).toBeTruthy();
  }, 90000);

  it("runs the Chaos Lab stress test and shows the resilience gauge", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Predicted passengers", {}, T);
    await user.click(screen.getByRole("button", { name: /Run stress test/ }));
    expect(await screen.findByText("Red-team debrief", {}, { timeout: 60000 })).toBeTruthy();
    expect(screen.getByRole("img", { name: /Resilience score/ })).toBeTruthy();
  }, 120000);

  it("time machine starts on the allocation slot", async () => {
    render(<App />);
    await screen.findByText("Predicted passengers", {}, T);
    expect((screen.getByLabelText("Time machine slot") as HTMLInputElement).value).toBe("3");
  }, 60000);
});
