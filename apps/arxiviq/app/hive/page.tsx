export const metadata = {
  title: { absolute: "The hive — dottie-os local floor" },
  description:
    "How dottie-os runs a team of agents on plain files: a registry, a shared blackboard, mailboxes, fail-closed delivery, autonomy gates, and budgets. Local-first, stdlib core. Not a train dashboard.",
};

const TREE = `hive/
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
    cursor.json    # where I am in my inbox, so nothing is read twice`;

function Heading({ n, children }: { n: string; children: React.ReactNode }) {
  return (
    <h2 className="reveal">
      <span className="label label--signal">{n}</span>
      {children}
    </h2>
  );
}

export default function HivePage() {
  return (
    <main className="main" id="main" tabIndex={-1}>
      <article className="folio container">
        <header className="folio__head">
          <p className="label seq">dottie-os — local multi-agent floor</p>
          <h1 className="display folio__title seq" style={{ "--i": 1 } as React.CSSProperties}>
            The hive
          </h1>
          <p className="lede seq" style={{ "--i": 2 } as React.CSSProperties}>
            One directory of plain files runs a whole team of agents: a roster, a
            shared blackboard, a task ledger, mailboxes, and append-only logs. No
            database, no watch-train theatrics — files you can read with{" "}
            <code>cat</code>. The System One sidecar decides; the hive keeps the
            floor on disk.
          </p>
        </header>

        <div className="prose">
          <Heading n="01">Why this exists</Heading>
          <p>
            Pair-programming still needs a roster, a blackboard, and a ledger.
            Those stay on your machine as plain files — next to the local
            sidecar, not as a public train dashboard or a chat control plane.
          </p>
          <p>
            Every job still lands in one place. Choice / Score / Noul decide the
            next move. The hive records who did what. That is the floor. It is
            not a public train dashboard.
          </p>

          <Heading n="02">What the hive is</Heading>
          <p>
            A directory on your machine. The design was audited from the Munder
            Difflin project and rebuilt for Dottie&apos;s stdlib-local world —
            the reusable core turned out to be the plain-file coordination, not
            the Electron app around it.
          </p>
          <pre className="codeblock" tabIndex={0} aria-label="Hive directory layout">
            {TREE}
          </pre>
          <p>
            Three rules keep it from falling apart. One process commits to git —
            agents never touch it, so concurrent writers can&apos;t corrupt the
            repo. Each agent writes only inside its own directory. And messages
            move by a router that picks files out of one agent&apos;s{" "}
            <code>outbox/</code> and drops them into another agent&apos;s{" "}
            <code>inbox/</code>, written atomically — no file is ever written by
            two processes at once.
          </p>

          <Heading n="03">How messages move — and what happens when they can&apos;t</Heading>
          <p>
            An agent that needs something writes a message file to its outbox.
            The router — polling about every 1.5 seconds — delivers it to the
            recipient&apos;s inbox and appends the event to the log. When an
            agent finishes a turn, it drains its inbox before stopping, so work
            keeps flowing without anyone watching.
          </p>
          <p>Delivery is fail-closed. Nothing is silently dropped:</p>
          <ul>
            <li>
              A message that can&apos;t be delivered bounces to the orchestrator,
              which decides what to do with it.
            </li>
            <li>
              A malformed message is quarantined and logged — never delivered,
              never deleted quietly.
            </li>
            <li>
              Conversations carry a hop count. Past the cap (12), the
              orchestrator steps in instead of letting two agents loop forever.
            </li>
            <li>
              Only requests, queries, and proposals obligate a reply. Plain
              notifications are terminal — they can&apos;t start a ping-pong.
            </li>
          </ul>

          <Heading n="04">Four autonomy gates</Heading>
          <p>Agents run on their own, but four layers decide how far that goes:</p>
          <ol className="gates">
            <li>
              <h3>Orchestrator triage</h3>
              <p>
                A standing orchestrator reads cross-agent traffic and resolves the
                routine stuff itself — clarifications, data requests, plan tweaks.
                Only the critical items escalate. The escalation policy lives in
                its prompt, so you tune the prompt, not the code.
              </p>
            </li>
            <li>
              <h3>Tool permissions are the human gate</h3>
              <p>
                Agents ask permission to use tools the way a single assistant
                would. Those prompts are the human-in-the-loop checkpoint — and
                they work from a phone, not just a desk.
              </p>
            </li>
            <li>
              <h3>Pause / gate / steer / halt at the boundary</h3>
              <p>
                A control registry enforces four states on any agent at the
                boundary, regardless of what the agent wants to do. Policy is
                enforced where actions cross into the world, not inside the
                agent&apos;s head.
              </p>
            </li>
            <li>
              <h3>Destructive ops need explicit confirm words</h3>
              <p>
                Deleting, spending, or changing scope requires a deliberate
                confirmation — a bare &ldquo;yeah&rdquo; or &ldquo;ok&rdquo; never
                authorizes anything, mass targets are forbidden, and a
                confirmation expires after two minutes.
              </p>
            </li>
          </ol>

          <Heading n="05">Budgets and the breaker</Heading>
          <p>
            Every agent runs on a work-token budget — counted on real work, not
            cache re-reads. When an agent misbehaves, a circuit breaker walks a
            ladder: <strong>steer</strong> (nudge it back on track), then{" "}
            <strong>constrain</strong> (narrow what it may do), then{" "}
            <strong>stop</strong>. One level per tick, and it de-escalates on
            recovery. It never kills an agent unless a human opts in.
          </p>
          <p>
            Spawning new agents is off by default, and any spawn request runs
            isolated unless you say otherwise.
          </p>

          <Heading n="06">What&apos;s in, what&apos;s out</Heading>
          <div className="ledger">
            <div>
              <p className="label">In</p>
              <ul>
                <li>File-based hive layout and message contract</li>
                <li>Fail-closed routing and append-only ledgers</li>
                <li>The breaker ladder and work-token budgets</li>
                <li>Confirm tiers for destructive operations</li>
                <li>Boundary-enforced pause / gate / steer / halt</li>
                <li>Isolate-by-default spawn queue</li>
              </ul>
            </div>
            <div>
              <p className="label">Out — deliberately</p>
              <ul>
                <li>Electron app and the 2D office theatrics</li>
                <li>Voice control</li>
                <li>Provider-shim sprawl</li>
                <li>Auto-approve mode</li>
                <li>Heavyweight vector memory at this scale — markdown first</li>
              </ul>
            </div>
          </div>

          <Heading n="07">One open question</Heading>
          <div className="callout">
            <p>
              <strong>Where should human approvals surface?</strong>
            </p>
            <p>
              The gates above need a human at the other end. That surface is
              configurable — the dashboard, a chat app, the terminal — and
              it&apos;s your call. Nothing here hard-codes one channel.
            </p>
          </div>

          <Heading n="08">The shape of it</Heading>
          <p>
            Lean stdlib core. Local-first — the hive lives on your machine, in
            files you own. The website, the local runtime, and the orchestrator
            harness are one project, built in that order. This page is step one.
          </p>
          <p className="fine">
            Design audited from the Munder Difflin project (read-only) and
            rebuilt for Dottie&apos;s stdlib-local world. Spec numbers above —
            the 1.5s router poll, the 12-hop cap, the 2-minute confirm expiry —
            come from that audit.
          </p>
        </div>
      </article>
    </main>
  );
}
