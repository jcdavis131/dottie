import Link from "next/link";
import "../system-one.css";
import {
  CHAMPION,
  DISCLAIMER,
  FLYWHEEL_STEPS,
  HERO_LEDE,
  HERO_SUBHEAD,
  HERO_TITLE,
  LAB_ARCHIVE,
  NOT_CHAT,
  PRIMITIVES,
  REFUSALS,
} from "../../lib/system-one-copy";

export default function SystemOneHome() {
  return (
    <div className="s1">
      <div className="wrap">
        <div className="kicker">
          <span>dottie-os</span>
          <span>System One sidecar</span>
          <span>local-first</span>
          <span>solo · MIT · free-tier</span>
        </div>
        <h1>{HERO_TITLE}</h1>
        <p className="subhead">{HERO_SUBHEAD}</p>
        <p className="lede">{HERO_LEDE}</p>
        <div className="btns">
          <a className="btn primary" href="https://github.com/jcdavis131/dottie">
            GitHub — dottie
          </a>
          <Link className="btn" href="/conductor">
            Conductor
          </Link>
          <Link className="btn" href="/dottie">
            Pair
          </Link>
        </div>

        <section aria-labelledby="primitives">
          <p className="eyebrow">Primitives</p>
          <h2 id="primitives">Choice · Score · Noul</h2>
          <div className="cards tri">
            {PRIMITIVES.map((item) => (
              <article className="card" key={item.name}>
                <h3>{item.name}</h3>
                <p className="sym">{item.symbol}</p>
                <p>{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="champion">
          <p className="eyebrow">Local champion</p>
          <h2 id="champion">Laya, on your tailnet</h2>
          <p className="lede" style={{ maxWidth: "46ch" }}>
            Laya is the local System One champion. <code>/decide</code> lives on
            your tailnet. This page does not publish a MagicDNS URL and does not
            curl a private host for visitors.
          </p>
          <div className="stamp">
            <div className="stamp-head">
              <strong>Champion stamp</strong>
              <span>{CHAMPION.mode}</span>
            </div>
            <dl>
              <dt>Helper</dt>
              <dd>{CHAMPION.helper}</dd>
              <dt>Mode</dt>
              <dd>{CHAMPION.mode}</dd>
              <dt>/decide smoke</dt>
              <dd>{CHAMPION.smoke}</dd>
              <dt>Surface</dt>
              <dd>
                {CHAMPION.decide} · {CHAMPION.surface}
              </dd>
              <dt>Ckpt id</dt>
              <dd>{CHAMPION.ckpt_id}</dd>
              <dt>Pack row counts</dt>
              <dd>{CHAMPION.pack_rows}</dd>
              <dt>Provenance</dt>
              <dd>
                {CHAMPION.provenance} · {CHAMPION.as_of}
              </dd>
            </dl>
            <p className="note">{CHAMPION.note}</p>
          </div>
        </section>

        <section aria-labelledby="flywheel">
          <p className="eyebrow">How data becomes decisions</p>
          <h2 id="flywheel">HF → factory → stamp</h2>
          <div className="steps">
            {FLYWHEEL_STEPS.map((step) => (
              <article className="card step" key={step.n}>
                <div className="n">
                  {step.n} · {step.title}
                </div>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section aria-labelledby="not-chat">
          <p className="eyebrow">What this is not</p>
          <h2 id="not-chat">Not a chat model</h2>
          <p className="lede" style={{ maxWidth: "46ch" }}>
            {NOT_CHAT}
          </p>
        </section>

        <section aria-labelledby="refuse">
          <p className="eyebrow">What we refuse</p>
          <h2 id="refuse">No silent promote</h2>
          <ul className="refuse">
            {REFUSALS.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>

        <footer className="foot">
          <div>{DISCLAIMER}</div>
          <div>{LAB_ARCHIVE}</div>
          <div>
            <a href="https://github.com/jcdavis131/dottie">dottie on GitHub</a>
            {" · "}
            <Link href="/hive">The hive</Link>
            {" · "}
            <Link href="/starter">Starter</Link>
          </div>
        </footer>
      </div>
    </div>
  );
}
