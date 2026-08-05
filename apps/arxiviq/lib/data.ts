export type Paper = {
  id: string;
  arxiv_id?: string;
  title: string;
  abstract?: string;
  authors?: string[];
  categories?: string[];
  cs_cats?: string[];
  query_tag?: string;
  published?: string;
  affinity?: number;
  url?: string;
};

export type GraphNodeType = "Person" | "Organization" | "Paper" | "Architecture" | "Topic";

export type GraphNode = {
  id: string;
  type: GraphNodeType;
  label: string;
  title?: string;
  abstract?: string;
  name?: string;
  orgs?: string[];
  description?: string;
  query_tag?: string;
  paper_ids?: string[];
  authors?: string[];
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  pinned?: boolean;
};

export type GraphEdgeKind =
  | "AUTHORED"
  | "AFFILIATED_WITH"
  | "USES_ARCHITECTURE"
  | "RELATED_TO"
  | "SAME_AS"
  | "MENTIONS"
  | "EXTRACTED_FROM"
  | string;

export type GraphEdge = {
  id?: string;
  source: string;
  target: string;
  kind: GraphEdgeKind;
  weight?: number;
};

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type Stats = {
  nodes?: number;
  graph_nodes?: number;
  edges?: number;
  docs?: number;
  papers?: number;
  people?: number;
  orgs?: number;
  architectures?: number;
  topics?: number;
  by_class?: Record<string, number>;
  cache?: string;
  timestamp?: string;
  checksum?: string;
  token_saving?: string;
};

export const TOPIC_TAGS = [
  "world_models",
  "jepa",
  "imagebind",
  "v_jepa",
  "pred_coding",
  "hamiltonian",
  "train_dynamics",
  "foundation_wm",
] as const;

export const ARCH_DESCRIPTIONS: Record<string, string> = {
  Dreamer: "latent world model for RL — RSSM + actor-critic in imagination",
  JEPA: "joint embedding predictive architecture: predicts in representation space, not pixels",
  "V-JEPA": "video JEPA: self-supervised video encoder learning temporal semantics via masking",
  ImageBind: "binds 6 modalities via images: vision as lingua franca for audio, depth, IMU, text",
  Hamiltonian: "Hamiltonian neural nets: conserve energy, symplectic structure for physics",
  "World Model": "VAE + MDN-RNN controller loop for learning dynamics",
  PredCoding: "predictive coding: hierarchical error minimization, top-down predictions",
  "Foundation WM": "foundation world model: large-scale latent dynamics pretraining",
};

export async function fetchJson<T>(path: string, fallback: T): Promise<T> {
  try {
    if (typeof window === "undefined") return fallback;
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as T;
    return data ?? fallback;
  } catch {
    return fallback;
  }
}

export async function loadGraph(): Promise<GraphData> {
  return fetchJson<GraphData>("/data/graph.json", { nodes: [], edges: [] });
}
export async function loadPapers(): Promise<Paper[]> {
  return fetchJson<Paper[]>("/data/papers.json", []);
}
export async function loadStats(): Promise<Stats> {
  return fetchJson<Stats>("/data/stats.json", {});
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("");
}

export function idealLength(kind: string): number {
  if (kind === "AUTHORED" || kind === "AFFILIATED_WITH" || kind === "SAME_AS") return 70;
  if (kind === "RELATED_TO") return 85;
  if (kind === "USES_ARCHITECTURE") return 100;
  return 85;
}

export function edgeStyle(kind: string) {
  // returns stroke, dash, width
  switch (kind) {
    case "AUTHORED":
      return { stroke: "#38bdf8", dash: "", width: 1.2 };
    case "USES_ARCHITECTURE":
      return { stroke: "#f59e0b", dash: "4 4", width: 1.1 };
    case "RELATED_TO":
      return { stroke: "#71717a", dash: "2 6", width: 0.9 };
    case "AFFILIATED_WITH":
      return { stroke: "#8b5cf6", dash: "1 3", width: 0.9 };
    case "SAME_AS":
      return { stroke: "#10b981", dash: "6 2", width: 1 };
    default:
      return { stroke: "#a1a1aa", dash: "3 3", width: 0.8 };
  }
}
