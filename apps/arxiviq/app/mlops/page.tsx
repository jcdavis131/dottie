import Link from "next/link";

export const metadata = {
  title: "MLOps pipeline — arxiviq",
  description:
    "Live line of sight into the arxiviq MLOps program: the seven-stage loop, both model tracks, the data flywheel, curation standard, benchmarks, and open decisions.",
};

type StageStatus = "green" | "yellow" | "red";

const STATUS_STYLE: Record<StageStatus, React.CSSProperties> = {
  green: { color: "#9DC08B", borderColor: "#3A5A34", background: "#12200F" },
  yellow: { color: "#E5C07B", borderColor: "#5A4A22", background: "#221A0C" },
  red: { color: "#E08A7B", borderColor: "#5A2A24", background: "#22100E" },
};

const STATUS_LABEL: Record<StageStatus, string> = {
  green: "flowing",
  yellow: "in progress",
  red: "gated",
};

const stages: {
  n: string;
  name: string;
  status: StageStatus;
  line: string;
  detail: string;
}[] = [
  {
    n: "01",
    name: "Collect",
    status: "green",
    line: "Feeds are live and flowing.",
    detail:
      "NBA game logs (1,350 player-seasons, 91,458 rows), sidecar agent traces (13,678 scored), Kalshi listings, EIA gas data — all scheduled and verified. HF dataset curation in progress.",
  },
  {
    n: "02",
    name: "Curate",
    status: "green",
    line: "QA gates coded; dev-data curation building.",
    detail:
      "Fail-closed validation, transcription gates, and anti-synthetic promotion rules (ML-11) are live in code. The dev-model curation pipeline — license filter, dedup, quality gates, PII/secret scrub, train/val/test splits — is being built now.",
  },
  {
    n: "03",
    name: "Prep",
    status: "yellow",
    line: "HF dataset shortlist in progress.",
    detail:
      "Real public Hugging Face datasets for code, review, debugging, docs, and DevOps are being curated. Needs Cameron's sign-off on the shortlist, then download to the GPU box (disk/bandwidth word needed).",
  },
  {
    n: "04",
    name: "Architecture",
    status: "yellow",
    line: "Base-model pick is open.",
    detail:
      "Dev model: open-weights code LM + LoRA/QLoRA (the only fit for 12 GB VRAM). Entailment model: SOTA NLI architecture under review. MTNN v5 champion still serving vector search, untouched.",
  },
  {
    n: "05",
    name: "Train",
    status: "red",
    line: "Gated — needs Cameron's word.",
    detail:
      "GPU runner is healthy and idle. Blocked on: dataset sign-off, disk/bandwidth, base-model pick, pip approval (transformers/peft/trl), and the explicit GPU dispatch word. Synthetic-data job permanently retired.",
  },
  {
    n: "06",
    name: "Serve",
    status: "yellow",
    line: "Inference stack decision open.",
    detail:
      "Options: transformers + adapter serve, or llama.cpp GGUF export. Decided alongside the training-stack call. Nothing serves until a held-out eval win.",
  },
  {
    n: "07",
    name: "Eval",
    status: "yellow",
    line: "Benchmark suites being defined.",
    detail:
      "Dev model: code-task benchmarks on frozen eval sets. Entailment: MNLI/SNLI plus ANLI and FEVER held eval-only. Promotion rule: beat the baseline on held-out data, no regressions — then the loop feeds back into collection and retraining.",
  },
];

const page: React.CSSProperties = {
  background: "#080A0F",
  color: "#EDEAE2",
  fontFamily: "ui-sans-system, -apple-system, Segoe UI, Roboto, Inter, sans-serif",
  lineHeight: 1.65,
};

const wrap: React.CSSProperties = {
  maxWidth: 960,
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
  maxWidth: 680,
};

const h2: React.CSSProperties = {
  fontSize: 24,
  margin: "64px 0 12px",
  fontWeight: 700,
};

const p: React.CSSProperties = { color: "#B9B4A7", margin: "12px 0", maxWidth: 720 };

const card: React.CSSProperties = {
  border: "1px solid #232B26",
  borderRadius: 12,
  background: "#0D1117",
  padding: "18px 18px 16px",
};

const pillBase: React.CSSProperties = {
  display: "inline-block",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 11,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  border: "1px solid",
  borderRadius: 999,
  padding: "3px 10px",
};

const incomingTag: React.CSSProperties = {
  ...pillBase,
  color: "#8A9A8B",
  borderColor: "#2E3A32",
  background: "#101512",
  marginLeft: 8,
  verticalAlign: "middle",
};

const provenance: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 12,
  color: "#8A9A8B",
  border: "1px dashed #2E3A32",
  borderRadius: 8,
  padding: "10px 14px",
  marginTop: 20,
  maxWidth: 720,
};

function StatusPill({ status }: { status: StageStatus }) {
  return (
    <span style={{ ...pillBase, ...STATUS_STYLE[status] }}>{STATUS_LABEL[status]}</span>
  );
}

function Incoming() {
  return <span style={incomingTag}>incoming</span>;
}

export default function PipelinePage() {
  return (
    <div style={page}>
      <div style={wrap}>
        <div style={eyebrow}>arxiviq · MLOps</div>
        <h1 style={h1}>The pipeline</h1>
        <p style={lede}>
          One loop ships our models: collect, curate, prep, architecture, train,
          serve, eval — then back to collect. This page is the team's shared
          view of where the loop stands, what's blocked, and what Cameron needs
          to decide.
        </p>
        <div style={provenance}>
          Statuses from the 2026-10-08 pipeline audit. Items still being
          researched are marked <span style={{ color: "#EDEAE2" }}>incoming</span> —
          nothing here is invented.
        </div>

        <h2 style={h2}>The loop</h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 12,
          }}
        >
          {stages.map((s) => (
            <div key={s.n} style={card}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                  marginBottom: 10,
                }}
              >
                <span
                  style={{
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                    fontSize: 12,
                    color: "#8A9A8B",
                  }}
                >
                  {s.n}
                </span>
                <StatusPill status={s.status} />
              </div>
              <div style={{ fontWeight: 700, fontSize: 17, marginBottom: 4 }}>
                {s.name}
              </div>
              <div style={{ color: "#EDEAE2", fontSize: 14, marginBottom: 8 }}>
                {s.line}
              </div>
              <div style={{ color: "#8F8A7E", fontSize: 13 }}>{s.detail}</div>
            </div>
          ))}
        </div>

        <h2 style={h2}>Two model tracks</h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 12,
          }}
        >
          <div style={card}>
            <div style={{ ...eyebrow, marginBottom: 8 }}>Track A</div>
            <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 6 }}>
              Dev assistant <Incoming />
            </div>
            <p style={{ ...p, margin: "0 0 8px" }}>
              A work/job/skill model: code, code review, debugging, docs,
              testing, DevOps. Fine-tuned from an open-weights code LM with
              LoRA/QLoRA on curated real Hugging Face datasets.
            </p>
            <p style={{ ...p, margin: 0, fontSize: 13 }}>
              Status: dataset shortlist in curation; base-model pick and
              training stack open.
            </p>
          </div>
          <div style={card}>
            <div style={{ ...eyebrow, marginBottom: 8 }}>Track B</div>
            <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 6 }}>
              Entailment model <Incoming />
            </div>
            <p style={{ ...p, margin: "0 0 8px" }}>
              A state-of-the-art entailment model: does the evidence entail the
              claim? It powers the agent harness's verify step. Trained on
              real NLI and fact-verification data.
            </p>
            <p style={{ ...p, margin: 0, fontSize: 13 }}>
              Status: NLI dataset review and SOTA survey in progress; ANLI /
              FEVER reserved eval-only.
            </p>
          </div>
        </div>

        <h2 style={h2}>The data flywheel</h2>
        <p style={p}>
          The system gets smarter every day. Real work flowing through the
          swarm — agent trajectories, git history, PRs and reviews, team chat —
          is collected continuously, passes the same curation gates as public
          data, lands in versioned datasets, and triggers retraining only when
          eval says we can do better.
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: 12,
          }}
        >
          {[
            {
              t: "Collect, always",
              d: "Swarm trajectories, commits, PRs, reviews, chat — watermarked incremental collectors, secrets scrubbed at the source.",
            },
            {
              t: "Curate to the bar",
              d: "Dedup, contamination screening, PII/secret scrub, license manifest on every row. Synthetic data can never promote.",
            },
            {
              t: "Version the data",
              d: "Append-only dataset versions with row counts, source breakdown, content hashes, and gate results.",
            },
            {
              t: "Eval-gated retrain",
              d: "Retrain when benchmarks regress or new data can beat SOTA — never on a timer, never without a held-out win.",
            },
          ].map((f) => (
            <div key={f.t} style={card}>
              <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }}>
                {f.t}
              </div>
              <div style={{ color: "#8F8A7E", fontSize: 13 }}>{f.d}</div>
            </div>
          ))}
        </div>

        <h2 style={h2}>Curation standard</h2>
        <p style={p}>
          Every row that reaches training clears the same bar — public or
          first-party:
        </p>
        <ul style={{ ...p, paddingLeft: 20, margin: "8px 0" }}>
          {[
            "Real data only — no synthetic examples, ever (enforced in code: ML-11).",
            "Exact and near-duplicate dedup, within and across datasets.",
            "Train/test contamination screening against all held-out eval sets.",
            "PII and secret scrubbing before anything is stored.",
            "License manifest on every row: source dataset plus SPDX identifier.",
            "Teacher labeling (Jev) grades real examples only — it never generates training data.",
          ].map((item) => (
            <li key={item} style={{ margin: "8px 0", color: "#B9B4A7" }}>
              {item}
            </li>
          ))}
        </ul>

        <h2 style={h2}>
          Eval &amp; benchmarks <Incoming />
        </h2>
        <p style={p}>
          Eval is the last stage of the loop — and the gate everything passes
          through before serving. Nothing promotes without a held-out win.
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 12,
          }}
        >
          <div style={card}>
            <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }}>
              Dev assistant benchmarks
            </div>
            <div style={{ color: "#8F8A7E", fontSize: 13 }}>
              Code-task benchmarks on frozen eval sets — generation, repair,
              review quality. Promotion requires beating the baseline by a
              margin, with no regressions elsewhere. Suite being finalized.
            </div>
          </div>
          <div style={card}>
            <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 6 }}>
              Entailment benchmarks
            </div>
            <div style={{ color: "#8F8A7E", fontSize: 13 }}>
              MNLI / SNLI for training signal; ANLI and FEVER held eval-only.
              Target: state of the art, with published baseline numbers to
              beat. SOTA survey in progress.
            </div>
          </div>
        </div>

        <h2 style={h2}>Decisions needed</h2>
        <p style={p}>
          These need Cameron's word — merges, GPU dispatch, and promotions
          never move without it:
        </p>
        <ul style={{ paddingLeft: 20, margin: "8px 0" }}>
          {[
            "Sign off the Hugging Face dataset shortlist.",
            "Disk and bandwidth for the dataset download (box has ~9.5 GB free — external storage?).",
            "Pick the base code LM from the recommendation.",
            "Approve pip install of transformers / peft / trl on the GPU box.",
            "Dispatch word for the fine-tune run.",
            "Serve and promote the dev model — after the held-out eval win.",
            "Dispatch the embedding_v3 rebuild (vector lane).",
            "Push the dottie-local backup (64 uncommitted commits) to a private repo.",
          ].map((item) => (
            <li key={item} style={{ margin: "10px 0", color: "#EDEAE2" }}>
              <span
                style={{
                  display: "inline-block",
                  width: 14,
                  height: 14,
                  border: "1px solid #C17C60",
                  borderRadius: 4,
                  marginRight: 10,
                  verticalAlign: "-2px",
                }}
              />
              {item}
            </li>
          ))}
        </ul>

        <div style={provenance}>
          Page built 2026-10-08 from the pipeline audit
          (workspace/mlops-pipeline-audit/UNBLOCK_PLAN.md) and Cameron's
          strategy decisions. Update it as stages flip — the loop only moves
          forward.
        </div>

        <div style={{ marginTop: 32 }}>
          <Link
            href="/"
            style={{
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              fontSize: 13,
              color: "#8A9A8B",
              textDecoration: "none",
            }}
          >
            ← back to arxiviq
          </Link>
        </div>
      </div>
    </div>
  );
}
