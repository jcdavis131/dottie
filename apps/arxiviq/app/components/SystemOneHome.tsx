import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import {
  CHAMPION,
  CHOICE_OPTIONS,
  FLYWHEEL_STEPS,
  HERO_LEDE,
  HERO_SUBHEAD,
  HERO_TITLE,
  LAB_ARCHIVE,
  NOT_CHAT_ARCHIVE,
  NOT_CHAT_LEAD,
  NOT_CHAT_VERB,
  NOT_CHAT_VERB_GLOSS,
  PRIMITIVES,
  REFUSALS,
} from "../../lib/system-one-copy";

const SECTIONS = 5;

/** Stagger index for the title sequence and reveals. */
const seq = (i: number) => ({ "--i": i }) as CSSProperties;

/** One-point field behind the title: nested frames and rays meeting at the centre. */
function PerspectiveField() {
  const w = 1600;
  const h = 1000;
  const cx = w / 2;
  const cy = h / 2;
  const frames = [0.86, 0.62, 0.44, 0.3];
  const edge = [0, 0.25, 0.5, 0.75, 1];
  const rays: Array<[number, number]> = [];
  for (const t of edge) {
    rays.push([t * w, 0], [t * w, h]);
  }
  for (const t of [0.25, 0.5, 0.75]) {
    rays.push([0, t * h], [w, t * h]);
  }
  const inner = 0.3;
  return (
    <svg
      className="hero__field"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <g stroke="currentColor" strokeWidth="1" fill="none">
        {frames.map((s, i) => (
          <rect
            className="frame"
            key={s}
            style={seq(i)}
            x={cx - (w * s) / 2}
            y={cy - (h * s) / 2}
            width={w * s}
            height={h * s}
          />
        ))}
        {rays.map(([x, y]) => (
          <line
            className="ray"
            key={`${x}-${y}`}
            pathLength={1}
            x1={x}
            y1={y}
            x2={cx + (x - cx) * inner}
            y2={cy + (y - cy) * inner}
          />
        ))}
      </g>
    </svg>
  );
}

function PlateHead({
  n,
  eyebrow,
  title,
  id,
  children,
}: {
  n: number;
  eyebrow: string;
  title: string;
  id: string;
  children?: ReactNode;
}) {
  return (
    <header className="plate__head reveal">
      <p className="plate__num" aria-hidden="true">
        <span>
          <b>{String(n).padStart(2, "0")}</b> / {String(SECTIONS).padStart(2, "0")}
        </span>
      </p>
      <p className="label">{eyebrow}</p>
      <h2 className="h2" id={id}>
        {title}
      </h2>
      {children}
    </header>
  );
}

function Dial({ name }: { name: string }) {
  if (name === "Choice") {
    return (
      <div className="dial">
        <ul className="segments" aria-label="The four Choice labels">
          {CHOICE_OPTIONS.map((option) => (
            <li key={option}>{option}</li>
          ))}
        </ul>
      </div>
    );
  }
  if (name === "Score") {
    return (
      <div className="dial" aria-hidden="true">
        <div className="axis axis--ramp">
          <div className="axis__rule" />
          <div className="axis__ends">
            <span>lower</span>
            <span>higher</span>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="dial" aria-hidden="true">
      <div className="axis">
        <div className="axis__rule" />
        {[0, 25, 50, 75, 100].map((pct) => (
          <span className="axis__tick" key={pct} style={{ left: `${pct}%` }} />
        ))}
        <div className="axis__ends">
          <span>0</span>
          <span>0.5</span>
          <span>1</span>
        </div>
      </div>
    </div>
  );
}

export default function SystemOneHome() {
  const readout: Array<[string, string]> = [
    ["Helper", CHAMPION.helper],
    ["Mode", CHAMPION.mode],
    ["/decide smoke", CHAMPION.smoke],
    ["Surface", `${CHAMPION.decide} · ${CHAMPION.surface}`],
    ["Ckpt id", CHAMPION.ckpt_id],
    ["Pack row counts", CHAMPION.pack_rows],
    ["Provenance", `${CHAMPION.provenance} · ${CHAMPION.as_of}`],
  ];

  return (
    <main className="main" id="main" tabIndex={-1}>
      <section className="hero" aria-labelledby="title">
        <PerspectiveField />
        <div className="hero__inner">
          <div className="hero__meta seq" style={seq(0)}>
            <span className="label">System One sidecar</span>
            <span className="label">local-first</span>
            <span className="label">solo · MIT · free-tier</span>
          </div>
          <h1 className="display hero__title seq" id="title" style={seq(1)}>
            {HERO_TITLE}
          </h1>
          <p className="hero__sub seq" style={seq(2)}>
            {HERO_SUBHEAD}
          </p>
          <p className="lede hero__lede seq" style={seq(3)}>
            {HERO_LEDE}
          </p>
          <div className="actions seq" style={seq(4)}>
            <a className="btn btn--primary" href="https://github.com/jcdavis131/dottie">
              GitHub — dottie <span className="btn__arrow" aria-hidden="true">→</span>
            </a>
            <Link className="btn" href="/conductor">
              Conductor
            </Link>
            <Link className="btn" href="/dottie">
              Pair
            </Link>
          </div>
        </div>
        <div className="hero__foot" aria-hidden="true">
          <span />
        </div>
      </section>

      <section className="plate" aria-labelledby="primitives">
        <div className="container">
          <PlateHead n={1} eyebrow="Primitives" title="Choice · Score · Noul" id="primitives" />
          <div className="tri">
            {PRIMITIVES.map((item, i) => (
              <article className="instrument reveal" key={item.name} style={seq(i)}>
                <div className="instrument__top">
                  <h3 className="instrument__name">{item.name}</h3>
                  <p className="instrument__sym">{item.symbol}</p>
                </div>
                <Dial name={item.name} />
                <p className="instrument__body">{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="plate" aria-labelledby="champion">
        <div className="container">
          <PlateHead n={2} eyebrow="Local champion" title="Laya, on your tailnet" id="champion">
            <p className="plate__lede">
              Laya is the local System One champion. <code>/decide</code> lives on your
              tailnet. This page does not publish a MagicDNS URL and does not curl a
              private host for visitors.
            </p>
          </PlateHead>
          <div className="console reveal">
            <div className="console__head">
              <p className="label" style={{ color: "var(--ink)" }}>
                Champion stamp
              </p>
              <p className="console__state label">
                <span className="dot dot--signal" aria-hidden="true" />
                {CHAMPION.mode}
              </p>
            </div>
            <dl className="readout">
              {readout.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <p className="console__note">{CHAMPION.note}</p>
          </div>
        </div>
      </section>

      <section className="plate" aria-labelledby="flywheel">
        <div className="container">
          <PlateHead n={3} eyebrow="How data becomes decisions" title="HF → factory → stamp" id="flywheel" />
          <ol className="steps">
            {FLYWHEEL_STEPS.map((step, i) => (
              <li className="step reveal" key={step.n} style={seq(i)}>
                <span className="step__n" aria-hidden="true">
                  {step.n}
                </span>
                <h3 className="h3">{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="plate" aria-labelledby="not-chat">
        <div className="container">
          <PlateHead n={4} eyebrow="What this is not" title="Not a chat model" id="not-chat" />
          <p className="statement reveal">
            {NOT_CHAT_LEAD} The verb is <em>{NOT_CHAT_VERB}</em> — {NOT_CHAT_VERB_GLOSS}
          </p>
          <p className="statement-note reveal">{NOT_CHAT_ARCHIVE}</p>
        </div>
      </section>

      <section className="plate" aria-labelledby="refuse">
        <div className="container">
          <PlateHead n={5} eyebrow="What we refuse" title="No silent promote" id="refuse" />
          <ul className="refusals tri">
            {REFUSALS.map((item, i) => (
              <li className="refusal reveal" key={item} style={seq(i)}>
                <span className="refusal__mark" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
          <p className="archive" style={{ marginTop: "var(--s5)" }}>
            {LAB_ARCHIVE}
          </p>
        </div>
      </section>
    </main>
  );
}
