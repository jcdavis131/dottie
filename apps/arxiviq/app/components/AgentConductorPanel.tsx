"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import {
  getConductorSnapshot,
  sendConductorRpc,
  type ConductorRpc,
  type ConductorSnapshot,
} from "../../lib/conductor";

type NavTab = "Dashboard" | "Guardrails" | "Feedback" | "Scratchpad" | "Todos";
type FeedbackKind = "thumbs_up" | "thumbs_down" | "note";

const NAV: NavTab[] = ["Dashboard", "Guardrails", "Feedback", "Scratchpad", "Todos"];
const tabId = (tab: NavTab) => tab.toLowerCase();

export default function AgentConductorPanel({
  tandem = false,
}: { tandem?: boolean } = {}) {
  const [active, setActive] = useState<NavTab>("Dashboard");
  const [snap, setSnap] = useState<ConductorSnapshot | null>(null);
  const [todoInput, setTodoInput] = useState("");
  const [scratchInput, setScratchInput] = useState("");
  const [feedbackMsg, setFeedbackMsg] = useState("");
  const [rpcError, setRpcError] = useState("");
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const refresh = async () => {
      try {
        const next = await getConductorSnapshot();
        if (mounted.current) setSnap(next);
      } catch {
        if (mounted.current) {
          setSnap(null);
          setFeedbackMsg("");
          setScratchInput("");
          setTodoInput("");
        }
      }
    };
    const initial = window.setTimeout(() => void refresh(), 0);
    const interval = window.setInterval(() => void refresh(), 8000);
    return () => {
      mounted.current = false;
      window.clearTimeout(initial);
      window.clearInterval(interval);
    };
  }, []);

  const canWrite = useCallback(
    (method: ConductorRpc["method"]) =>
      Boolean(snap?.capabilities.write.includes(method)),
    [snap],
  );

  const rpc = useCallback(async (request: ConductorRpc) => {
    try {
      setRpcError("");
      const next = await sendConductorRpc(request);
      if (mounted.current) setSnap(next);
      return true;
    } catch (error) {
      if (mounted.current) {
        setRpcError(
          error instanceof Error ? error.message : "Conductor request failed.",
        );
      }
      return false;
    }
  }, []);

  const handleTabKey = (
    event: KeyboardEvent<HTMLButtonElement>,
    current: NavTab,
  ) => {
    const index = NAV.indexOf(current);
    const target =
      event.key === "ArrowRight"
        ? NAV[(index + 1) % NAV.length]
        : event.key === "ArrowLeft"
          ? NAV[(index - 1 + NAV.length) % NAV.length]
          : event.key === "Home"
            ? NAV[0]
            : event.key === "End"
              ? NAV[NAV.length - 1]
              : null;
    if (!target) return;
    event.preventDefault();
    setActive(target);
    document.getElementById(`conductor-tab-${tabId(target)}`)?.focus();
  };

  const handleFeedback = async (kind: FeedbackKind) => {
    if ((!feedbackMsg.trim() && kind === "note") || !canWrite("feedback.push")) {
      return;
    }
    const ok = await rpc({
      method: "feedback.push",
      params: {
        kind,
        message:
          feedbackMsg ||
          (kind === "thumbs_up"
            ? "This is working well"
            : kind === "thumbs_down"
              ? "Needs attention"
              : "Quick note"),
        strength: kind === "thumbs_up" ? 1 : kind === "thumbs_down" ? -0.6 : 0.2,
      },
    });
    if (ok) setFeedbackMsg("");
  };

  const handleScratchWrite = async () => {
    if (!scratchInput.trim() || !canWrite("scratchpad.write")) return;
    const ok = await rpc({
      method: "scratchpad.write",
      params: { text: scratchInput },
    });
    if (ok) setScratchInput("");
  };

  const handleTodoCreate = async () => {
    if (!todoInput.trim() || !canWrite("todo.create")) return;
    const ok = await rpc({
      method: "todo.create",
      params: { text: todoInput, priority: "mid" },
    });
    if (ok) setTodoInput("");
  };

  return (
    <div
      data-conductor-root
      style={{
        background: "#080A0F",
        border: "1px solid #1E3328",
        borderRadius: 16,
        color: "#E6F1EB",
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
        minHeight: 560,
        overflow: "hidden",
      }}
    >
      <header
        style={{
          alignItems: "center",
          background: "#0A1210",
          borderBottom: "1px solid #1E3328",
          display: "flex",
          gap: 16,
          minHeight: 48,
          padding: "0 12px",
        }}
      >
        <strong>Conductor</strong>
        <div
          aria-label="Conductor sections"
          role="tablist"
          style={{ display: "flex", gap: 6 }}
        >
          {NAV.map((tab) => (
            <button
              aria-controls="conductor-panel"
              aria-selected={active === tab}
              id={`conductor-tab-${tabId(tab)}`}
              key={tab}
              onClick={() => setActive(tab)}
              onKeyDown={(event) => handleTabKey(event, tab)}
              role="tab"
              tabIndex={active === tab ? 0 : -1}
              type="button"
            >
              {tab}
            </button>
          ))}
        </div>
        <span style={{ marginLeft: "auto", fontSize: 12 }}>
          {snap ? `jarvisd ${snap.daemon.version}` : "daemon unavailable"}
        </span>
      </header>

      {rpcError && (
        <div role="alert" style={{ background: "#2A1515", padding: "8px 12px" }}>
          {rpcError}
        </div>
      )}

      {!snap ? (
        <div style={{ color: "#B8A078", padding: 28 }}>
          Authenticated conductor transport is not connected. Feedback, scratchpad,
          todo, and guardrail controls are unavailable; no browser-local data is
          substituted.
        </div>
      ) : (
        <main
          aria-labelledby={`conductor-tab-${tabId(active)}`}
          id="conductor-panel"
          role="tabpanel"
          style={{ padding: 16 }}
        >
          <p style={{ color: "#8BA998", fontSize: 12 }}>
            {tandem ? "Paired web view · " : ""}
            Fixed mission: {snap.mission}. Repository: {snap.repo}.
          </p>

          {active === "Dashboard" && (
            <section>
              <h2>Measured daemon status</h2>
              <p>
                PID {snap.daemon.process_id} · uptime {snap.daemon.uptime_s}s ·{" "}
                {snap.persistence.kind}/{snap.persistence.journal_mode}
              </p>
              <p>
                Authenticated actor limit: {snap.auth.rates_per_minute.agent} requests
                per minute.
              </p>
            </section>
          )}

          {active === "Guardrails" && (
            <section>
              <h2>Read-only guardrail status</h2>
              <p>This view cannot mutate guardrails.</p>
              <ul>
                {snap.guardrails.map((guardrail) => (
                  <li key={guardrail.id}>
                    {guardrail.id.replaceAll("_", " ")}:{" "}
                    {guardrail.enabled ? "on" : "off"}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {active === "Feedback" && (
            <section>
              <h2>Feedback</h2>
              <label htmlFor="conductor-feedback">Feedback note</label>
              <textarea
                id="conductor-feedback"
                onChange={(event) => setFeedbackMsg(event.target.value)}
                value={feedbackMsg}
              />
              <div>
                <button
                  disabled={!canWrite("feedback.push")}
                  type="button"
                  onClick={() => void handleFeedback("thumbs_up")}
                >
                  Good
                </button>
                <button
                  disabled={!canWrite("feedback.push")}
                  type="button"
                  onClick={() => void handleFeedback("thumbs_down")}
                >
                  Needs attention
                </button>
                <button
                  disabled={!canWrite("feedback.push")}
                  type="button"
                  onClick={() => void handleFeedback("note")}
                >
                  Send note
                </button>
              </div>
              <ul>
                {snap.feedback.map((feedback) => (
                  <li key={feedback.id}>
                    {feedback.kind}: {feedback.message}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {active === "Scratchpad" && (
            <section>
              <h2>Shared notes</h2>
              <label htmlFor="conductor-scratchpad">Add a mission note</label>
              <input
                id="conductor-scratchpad"
                onChange={(event) => setScratchInput(event.target.value)}
                value={scratchInput}
              />
              <button
                disabled={!canWrite("scratchpad.write")}
                type="button"
                onClick={() => void handleScratchWrite()}
              >
                Add note
              </button>
              <ul>
                {snap.scratchpad.map((entry) => (
                  <li key={entry.id}>
                    {entry.agent}: {entry.text}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {active === "Todos" && (
            <section>
              <h2>Mission tasks</h2>
              <label htmlFor="conductor-todo">Add a task</label>
              <input
                id="conductor-todo"
                onChange={(event) => setTodoInput(event.target.value)}
                value={todoInput}
              />
              <button
                disabled={!canWrite("todo.create")}
                type="button"
                onClick={() => void handleTodoCreate()}
              >
                Add task
              </button>
              <ul>
                {snap.todos.map((todo) => (
                  <li key={todo.id}>
                    <label>
                      <input
                        aria-label={`Mark ${todo.text} ${
                          todo.status === "completed" ? "open" : "completed"
                        }`}
                        checked={todo.status === "completed"}
                        disabled={!canWrite("todo.move")}
                        onChange={() =>
                          void rpc({
                            method: "todo.move",
                            params: {
                              id: todo.id,
                              status:
                                todo.status === "completed" ? "open" : "completed",
                            },
                          })
                        }
                        type="checkbox"
                      />
                      {todo.text} ({todo.status})
                    </label>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </main>
      )}
    </div>
  );
}
