import Link from "next/link";

import Mark from "./Mark";
import { DISCLAIMER } from "../../lib/system-one-copy";

export default function SiteFooter() {
  return (
    <footer className="foot">
      <div className="container foot__inner">
        <Mark className="foot__mark" />
        <ul className="foot__links">
          <li>
            <a href="https://github.com/jcdavis131/dottie">dottie on GitHub</a>
          </li>
          <li>
            <Link href="/hive">The hive</Link>
          </li>
          <li>
            <a href="/starter">Starter</a>
          </li>
        </ul>
        <p>{DISCLAIMER}</p>
      </div>
    </footer>
  );
}
