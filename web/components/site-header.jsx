"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Simulator" },
  { href: "/compare", label: "Compare" },
  { href: "/docs", label: "Documentation" },
  { href: "/cli", label: "CLI" },
];

function isActive(pathname, href) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function SiteHeader({ status = null }) {
  const pathname = usePathname();

  return (
    <nav className="topbar">
      <div className="topbar-brand">
        <span className="brand-dot" />
        <span className="brand-title">Consensus-Driven Drone Simulation</span>
        <span className="brand-sub">Distributed Swarm Coordination</span>
      </div>

      <div className="topbar-nav">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`topbar-link ${isActive(pathname, item.href) ? "active" : ""}`}
          >
            {item.label}
          </Link>
        ))}
      </div>

      {status ? <span className="status-pill">{status}</span> : null}
    </nav>
  );
}
