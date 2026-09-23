import Link from "next/link";

export const metadata = {
  title: { absolute: "Not found — dottie-os · arxiviq.com" },
};

export default function NotFound() {
  return (
    <main className="main void" id="main" tabIndex={-1}>
      <div className="container void__inner">
        <p className="label seq">Nothing is filed at this address</p>
        <p className="void__code seq" style={{ "--i": 1 } as React.CSSProperties} aria-hidden="true">
          404
        </p>
        <h1 className="h2 seq" style={{ "--i": 2 } as React.CSSProperties}>
          This page does not exist
        </h1>
        <span className="void__rule" aria-hidden="true" />
        <p className="seq" style={{ "--i": 3 } as React.CSSProperties}>
          Conductor and Pair run on the server build of this site. If you followed a link
          to either and landed here, this deployment is serving the static edition, which
          carries the homepage, The hive, and Starter.
        </p>
        <div className="actions seq" style={{ "--i": 4 } as React.CSSProperties}>
          <Link className="btn btn--primary" href="/">
            Return to dottie-os
          </Link>
          <Link className="btn" href="/hive">
            The hive
          </Link>
        </div>
      </div>
    </main>
  );
}
