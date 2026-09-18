export const metadata = {
  title: "The hive — Dottie's multi-agent floor",
  description:
    "How Dottie runs a team of agents on plain files: a registry, a shared blackboard, mailboxes, fail-closed delivery, autonomy gates, and budgets. Local-first, stdlib core.",
};

const page: React.CSSProperties = {
  background: "#080A0F",
  color: "#EDEAE2",
  fontFamily: "ui-sans-system, -apple-system, Segoe UI, Roboto, Inter, sans-serif",
  lineHeight: 1.65,
};

const wrap: React.CSSProperties = {
  maxWidth: 760,
  margin: "0 auto",
  padding: "56px 20px 96px",
};

const eyebrow: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 12,
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  color: "#8A9A8B",
};

const h1: React.CSSProperties = {
  fontSize: "clamp(34px, 6vw, 52px)",
  lineHeight: 1.12,
  letterSpacing: "-0.01em",
  margin: "12px 0 16px",
  fontWeight: 700,
};

const lede: React.CSSProperties = {
  fontSize: 18,
  color: "#C9C4B8",
  maxWidth: 640,
};

const h2: React.CSSProperties = {
  fontSize: 24,
  margin: "56px 0 12px",
  fontWeight: 700,
};

const p: React.CSSProperties = { color: "#B9B4A7", margin: "12px 0" };

const li: React.CSSProperties = { color: "#B9B4A7", margin: "8px 0" };

const code: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: "0.86em",
  background: "#121A17",
  border: "1px solid #1E3328",
  borderRadius: 6,
  padding: "1px 6px",
  color: "#D8D2C4",
  whiteSpace: "nowrap",
};

const block: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 13,
  background: "#0A1210",
  border: "1px solid #1E3328",
  borderRadius: 12,
  padding: "18px 20px",
  overflowX: "auto",
  color: "#CFC9BB",
  lineHeight: 1.7,
  margin: "16px 0",
};

const card: React.CSSProperties = {
  background: "#0A1210",
  border: "1px solid #1E3328",
  borderRadius: 12,
  padding: "18px 20px",
  margin: "12px 0",
};

const cardTitle: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 13,
  color: "#8A9A8B",
  marginBottom: 8,
};

const twoCol: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
  gap: 16,
  margin: "16px 0",
};

const callout: React.CSSProperties = {
  borderLeft: "3px solid #C17C60",
  padding: "4px 0 4px 18px",
  margin: "24px 0",
};

export default function HivePage() {
  return (
    <main style={page}>
      <div style={wrap}>
        <div style={eyebrow}>Dottie — multi-agent floor</div>
        <h1 style={h1}>The hive</h1>
        <p style={lede}>
          One directory of plain files runs a whole team of agents: a roster, a
          shared blackboard, a task ledger, mailboxes, and append-only logs. No
          database, no dashboard theatrics — files you can read with{" "}
          <code style={code}>cat</code>.
        </p>

        <h2 style={h2}>Why this exists</h2>
        <p style={p}>
          Handshake turned its student network into a ~$2B business selling
          RL data — reportedly 70% of AI training spend is now reinforcement
          learning. The bottleneck is no longer models; it&apos;s expert
          workflow data: real tasks, done by real workers, with every step
          recorded.
        </p>
        <p style={p}>
          That&apos;s the bet behind the hive. Every job Dottie runs already
          passes through one place — the ledger. Each task, each message, each
          cost entry lands in append-only files. The coordination layer and the
          training-data layer are the same files. The more the team works, the
          richer the record of how the work got done. That&apos;s the flywheel.
        </p>

        <h2 style={h2}>What the hive is</h2>
        <p style={p}>
          A directory on your machine. The design was audited from the Munder
          Difflin project and rebuilt for Dottie&apos;s stdlib-local world —
          the reusable core turned out to be the plain-file coordination, not
          the Electron app around it.
        </p>
        <pre style={block}>
{`hive/
  registry.json    # roster: every agent, role, capabilities, status
  board.md         # shared blackboard — one designated scribe writes it
  tasks.json       # task ledger: id, assignee, spec, status, result
  log.jsonl        # append-only event feed (drives the activity stream)
  costs.jsonl      # append-only cost ledger
  agents/<id>/
    identity.md    # who I am, my role, my capabilities
    memory.md      # long-term memory — read at start, appended as I learn
    inbox/         # messages delivered to me, one JSON file each
    outbox/        # messages I want to send — the router drains these
    cursor.json    # where I am in my inbox, so nothing is read twice`}
        </pre>
        <p style={p}>
          Three rules keep it from falling apart. One process commits to git —
          agents never touch it, so concurrent writers can&apos;t corrupt the
          repo. Each agent writes only inside its own directory. And messages
          move by a router that picks files out of one agent&apos;s{" "}
          <code style={code}>outbox/</code> and drops them into another
          agent&apos;s <code style={code}>inbox/</code>, written atomically —
          no file is ever written by two processes at once.
        </p>

        <h2 style={h2}>How messages move — and what happens when they can&apos;t</h2>
        <p style={p}>
          An agent that needs something writes a message file to its outbox.
          The router — polling about every 1.5 seconds — delivers it to the
          recipient&apos;s inbox and appends the event to the log. When an
          agent finishes a turn, it drains its inbox before stopping, so work
          keeps flowing without anyone watching.
        </p>
        <p style={p}>Delivery is fail-closed. Nothing is silently dropped:</p>
        <ul style={{ paddingLeft: 20, margin: "8px 0" }}>
          <li style={li}>
            A message that can&apos;t be delivered bounces to the orchestrator,
            which decides what to do with it.
          </li>
          <li style={li}>
            A malformed message is quarantined and logged — never delivered,
            never deleted quietly.
          </li>
          <li style={li}>
            Conversations carry a hop count. Past the cap (12), the
            orchestrator steps in instead of letting two agents loop forever.
          </li>
          <li style={li}>
            Only requests, queries, and proposals obligate a reply. Plain
            notifications are terminal — they can&apos;t start a ping-pong.
          </li>
        </ul>

        <h2 style={h2}>Four autonomy gates</h2>
        <p style={p}>
          Agents run on their own, but four layers decide how far that goes:
        </p>
        <div style={card}>
          <div style={cardTitle}>1 · Orchestrator triage</div>
          <p style={{ ...p, margin: 0 }}>
            A standing orchestrator reads cross-agent traffic and resolves the
            routine stuff itself — clarifications, data requests, plan tweaks.
            Only the critical items escalate. The escalation policy lives in
            its prompt, so you tune the prompt, not the code.
          </p>
        </div>
        <div style={card}>
          <div style={cardTitle}>2 · Tool permissions are the human gate</div>
          <p style={{ ...p, margin: 0 }}>
            Agents ask permission to use tools the way a single assistant
            would. Those prompts are the human-in-the-loop checkpoint — and
            they work from a phone, not just a desk.
          </p>
        </div>
        <div style={card}>
          <div style={cardTitle}>3 · Pause / gate / steer / halt at the boundary</div>
          <p style={{ ...p, margin: 0 }}>
            A control registry enforces four states on any agent at the
            boundary, regardless of what the agent wants to do. Policy is
            enforced where actions cross into the world, not inside the
            agent&apos;s head.
          </p>
        </div>
        <div style={card}>
          <div style={cardTitle}>4 · Destructive ops need explicit confirm words</div>
          <p style={{ ...p, margin: 0 }}>
            Deleting, spending, or changing scope requires a deliberate
            confirmation — a bare &ldquo;yeah&rdquo; or &ldquo;ok&rdquo; never
            authorizes anything, mass targets are forbidden, and a
            confirmation expires after two minutes.
          </p>
        </div>

        <h2 style={h2}>Budgets and the breaker</h2>
        <p style={p}>
          Every agent runs on a work-token budget — counted on real work, not
          cache re-reads. When an agent misbehaves, a circuit breaker walks a
          ladder: <strong style={{ color: "#EDEAE2" }}>steer</strong> (nudge it
          back on track), then <strong style={{ color: "#EDEAE2" }}>constrain</strong>{" "}
          (narrow what it may do), then{" "}
          <strong style={{ color: "#EDEAE2" }}>stop</strong>. One level per
          tick, and it de-escalates on recovery. It never kills an agent unless
          a human opts in.
        </p>
        <p style={p}>
          Spawning new agents is off by default, and any spawn request runs
          isolated unless you say otherwise.
        </p>

        <h2 style={h2}>What&apos;s in, what&apos;s out</h2>
        <div style={twoCol}>
          <div style={card}>
            <div style={cardTitle}>In</div>
            <ul style={{ paddingLeft: 18, margin: 0 }}>
              <li style={li}>File-based hive layout and message contract</li>
              <li style={li}>Fail-closed routing and append-only ledgers</li>
              <li style={li}>The breaker ladder and work-token budgets</li>
              <li style={li}>Confirm tiers for destructive operations</li>
              <li style={li}>Boundary-enforced pause / gate / steer / halt</li>
              <li style={li}>Isolate-by-default spawn queue</li>
            </ul>
          </div>
          <div style={card}>
            <div style={cardTitle}>Out — deliberately</div>
            <ul style={{ paddingLeft: 18, margin: 0 }}>
              <li style={li}>Electron app and the 2D office theatrics</li>
              <li style={li}>Voice control</li>
              <li style={li}>Provider-shim sprawl</li>
              <li style={li}>Auto-approve mode</li>
              <li style={li}>Heavyweight vector memory at this scale — markdown first</li>
            </ul>
          </div>
        </div>

        <h2 style={h2}>One open question</h2>
        <div style={callout}>
          <p style={{ ...p, marginTop: 0 }}>
            <strong style={{ color: "#EDEAE2" }}>
              Where should human approvals surface?
            </strong>
          </p>
          <p style={p}>
            The gates above need a human at the other end. That surface is
            configurable — the dashboard, a chat app, the terminal — and
            it&apos;s your call. Nothing here hard-codes one channel.
          </p>
        </div>

        <h2 style={h2}>The shape of it</h2>
        <p style={p}>
          Lean stdlib core. Local-first — the hive lives on your machine, in
          files you own. The website, the local runtime, and the orchestrator
          harness are one project, built in that order. This page is step one.
        </p>
        <p style={{ ...p, color: "#7A756A", fontSize: 13 }}>
          Design audited from the Munder Difflin project (read-only) and
          rebuilt for Dottie&apos;s stdlib-local world. Spec numbers above —
          the 1.5s router poll, the 12-hop cap, the 2-minute confirm expiry —
          come from that audit.
        </p>
      </div>
    </main>
  );
}
