"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import Mark from "./Mark";

const LINKS = [
  { href: "/conductor", label: "Conductor" },
  { href: "/hive", label: "The hive" },
  { href: "/dottie", label: "Pair" },
] as const;

export default function SiteNav() {
  const pathname = usePathname();
  return (
    <nav className="nav" aria-label="Site">
      <div className="container nav__inner">
        <Link className="brand" href="/" aria-current={pathname === "/" ? "page" : undefined}>
          <Mark />
          <span>
            dottie-os <span className="brand__domain">· arxiviq</span>
          </span>
        </Link>
        <ul className="nav__links">
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                aria-current={pathname === link.href ? "page" : undefined}
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}
