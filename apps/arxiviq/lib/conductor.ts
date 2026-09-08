export type ConductorMethod =
  | "feedback.push"
  | "scratchpad.write"
  | "todo.create"
  | "todo.move";

export type ConductorRpc =
  | {
      method: "feedback.push";
      params: {
        kind: "thumbs_up" | "thumbs_down" | "note";
        message: string;
        strength: number;
      };
    }
  | { method: "scratchpad.write"; params: { text: string } }
  | {
      method: "todo.create";
      params: { text: string; priority: "low" | "mid" | "high" };
    }
  | {
      method: "todo.move";
      params: { id: number; status: "open" | "in_progress" | "completed" };
    };

type ScopedRow = {
  id: number;
  ts: string;
  repo: string;
  agent: string;
  mission: string;
};

export type ConductorSnapshot = {
  ok: true;
  repo: string;
  mission: string;
  daemon: { version: string; uptime_s: number; process_id: number };
  persistence: {
    enabled: boolean;
    kind: "sqlite";
    journal_mode: "wal" | "memory";
  };
  auth: {
    enabled: boolean;
    read_only: true;
    rates_per_minute: { ip: number; key: number; agent: number };
  };
  capabilities: {
    read: Array<"feedback" | "scratchpad" | "todos" | "guardrails">;
    write: ConductorMethod[];
  };
  guardrails: Array<{
    id: string;
    enabled: boolean;
    mutable: false;
  }>;
  feedback: Array<
    ScopedRow & {
      kind: "thumbs_up" | "thumbs_down" | "note";
      message: string;
      strength: number;
    }
  >;
  scratchpad: Array<ScopedRow & { text: string }>;
  todos: Array<
    ScopedRow & {
      updated_ts: string;
      text: string;
      priority: "low" | "mid" | "high";
      status: "open" | "in_progress" | "completed";
    }
  >;
};

async function readSnapshot(response: Response): Promise<ConductorSnapshot> {
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.ok) {
    throw new Error(body?.error || "Conductor unavailable.");
  }
  return body as ConductorSnapshot;
}

export async function getConductorSnapshot(): Promise<ConductorSnapshot> {
  return readSnapshot(
    await fetch("/api/conductor/snapshot", {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
    }),
  );
}

export async function sendConductorRpc(
  request: ConductorRpc,
): Promise<ConductorSnapshot> {
  const response = await fetch("/api/conductor/rpc", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.ok || !body?.snapshot) {
    throw new Error(body?.error || "Conductor request failed.");
  }
  return body.snapshot as ConductorSnapshot;
}
