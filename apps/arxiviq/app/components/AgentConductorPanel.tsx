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
    <div className="panel" data-conductor-root>
      <div className="panel__bar">
        <div
          aria-label="Conductor sections"
          className="tabs"
          role="tablist"
        >
          {NAV.map((tab) => (
            <button
              aria-controls="conductor-panel"
              aria-selected={active === tab}
              className="tab"
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
        <span className="chip" role="status">
          <span
            aria-hidden="true"
            className={snap ? "dot dot--ok dot--live" : "dot"}
          />
          {snap ? `jarvisd ${snap.daemon.version}` : "daemon unavailable"}
        </span>
      </div>

      {rpcError && (
        <div className="notice" role="alert">
          {rpcError}
        </div>
      )}

      {!snap ? (
        <div className="offline">
          <p className="label">Transport offline</p>
          <p>
            Authenticated conductor transport is not connected. Feedback, scratchpad,
            todo, and guardrail controls are unavailable; no browser-local data is
            substituted.
          </p>
          <a className="btn" href="/dottie">
            Pair with jarvisd
          </a>
        </div>
      ) : (
        <div
          aria-labelledby={`conductor-tab-${tabId(active)}`}
          className="panel__body"
          id="conductor-panel"
          role="tabpanel"
          tabIndex={0}
        >
          <p className="label">
            {tandem ? "Paired web view · " : ""}
            Fixed mission: {snap.mission}. Repository: {snap.repo}.
          </p>

          {active === "Dashboard" && (
            <section>
              <h2>Measured daemon status</h2>
              <dl className="readout">
                <div>
                  <dt>Process</dt>
                  <dd>PID {snap.daemon.process_id}</dd>
                </div>
                <div>
                  <dt>Uptime</dt>
                  <dd>{snap.daemon.uptime_s}s</dd>
                </div>
                <div>
                  <dt>Persistence</dt>
                  <dd>
                    {snap.persistence.kind}/{snap.persistence.journal_mode}
                  </dd>
                </div>
                <div>
                  <dt>Rate limit</dt>
                  <dd>
                    Authenticated actor limit: {snap.auth.rates_per_minute.agent} requests
                    per minute.
                  </dd>
                </div>
              </dl>
            </section>
          )}

          {active === "Guardrails" && (
            <section>
              <h2>Read-only guardrail status</h2>
              <p className="muted">This view cannot mutate guardrails.</p>
              {snap.guardrails.length === 0 ? (
                <p className="empty">The daemon reported no guardrails.</p>
              ) : (
                <ul className="list">
                  {snap.guardrails.map((guardrail) => (
                    <li key={guardrail.id}>
                      <span
                        aria-hidden="true"
                        className={guardrail.enabled ? "dot dot--ok" : "dot"}
                      />
                      <span style={{ flex: 1 }}>{guardrail.id.replaceAll("_", " ")}</span>
                      <span className="chip">{guardrail.enabled ? "on" : "off"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {active === "Feedback" && (
            <section>
              <h2>Feedback</h2>
              <div className="field">
                <label htmlFor="conductor-feedback">Feedback note</label>
                <textarea
                  className="textarea"
                  id="conductor-feedback"
                  onChange={(event) => setFeedbackMsg(event.target.value)}
                  value={feedbackMsg}
                />
              </div>
              <div className="row" style={{ marginTop: "var(--s1)" }}>
                <button
                  className="btn"
                  disabled={!canWrite("feedback.push")}
                  type="button"
                  onClick={() => void handleFeedback("thumbs_up")}
                >
                  Good
                </button>
                <button
                  className="btn"
                  disabled={!canWrite("feedback.push")}
                  type="button"
                  onClick={() => void handleFeedback("thumbs_down")}
                >
                  Needs attention
                </button>
                <button
                  className="btn btn--primary"
                  disabled={!canWrite("feedback.push")}
                  type="button"
                  onClick={() => void handleFeedback("note")}
                >
                  Send note
                </button>
              </div>
              {snap.feedback.length === 0 ? (
                <p className="empty">No feedback recorded yet.</p>
              ) : (
                <ul className="list">
                  {snap.feedback.map((feedback) => (
                    <li key={feedback.id}>
                      <span className="list__key">{feedback.kind}</span>
                      <span>{feedback.message}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {active === "Scratchpad" && (
            <section>
              <h2>Shared notes</h2>
              <div className="row">
                <div className="field">
                  <label htmlFor="conductor-scratchpad">Add a mission note</label>
                  <input
                    className="input"
                    id="conductor-scratchpad"
                    onChange={(event) => setScratchInput(event.target.value)}
                    value={scratchInput}
                  />
                </div>
                <button
                  className="btn btn--primary"
                  disabled={!canWrite("scratchpad.write")}
                  type="button"
                  onClick={() => void handleScratchWrite()}
                >
                  Add note
                </button>
              </div>
              {snap.scratchpad.length === 0 ? (
                <p className="empty">No shared notes yet.</p>
              ) : (
                <ul className="list">
                  {snap.scratchpad.map((entry) => (
                    <li key={entry.id}>
                      <span className="list__key">{entry.agent}</span>
                      <span>{entry.text}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {active === "Todos" && (
            <section>
              <h2>Mission tasks</h2>
              <div className="row">
                <div className="field">
                  <label htmlFor="conductor-todo">Add a task</label>
                  <input
                    className="input"
                    id="conductor-todo"
                    onChange={(event) => setTodoInput(event.target.value)}
                    value={todoInput}
                  />
                </div>
                <button
                  className="btn btn--primary"
                  disabled={!canWrite("todo.create")}
                  type="button"
                  onClick={() => void handleTodoCreate()}
                >
                  Add task
                </button>
              </div>
              {snap.todos.length === 0 ? (
                <p className="empty">No mission tasks yet.</p>
              ) : (
                <ul className="list">
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
                        {todo.text} <span className="muted">({todo.status})</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  );
}
