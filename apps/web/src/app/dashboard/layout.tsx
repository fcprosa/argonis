"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Alert Queue", icon: "▤" },
  { href: "/dashboard/upload", label: "Upload Alerts", icon: "↑" },
  { href: "/dashboard/settings", label: "Settings", icon: "⚙" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen overflow-hidden bg-[#F8F8F8]">
      {/* Sidebar */}
      <aside className="flex w-[220px] shrink-0 flex-col bg-[#111] text-white">
        {/* Logo */}
        <div className="flex h-14 items-center border-b border-white/10 px-5">
          <span className="text-sm font-semibold tracking-widest text-white/90 uppercase">
            Argonis
          </span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV_ITEMS.map((item) => {
            const active =
              item.href === "/dashboard"
                ? pathname === "/dashboard"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={[
                  "flex items-center gap-3 rounded px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-white/10 text-white"
                    : "text-white/50 hover:bg-white/5 hover:text-white/80",
                ].join(" ")}
              >
                <span className="text-xs opacity-60">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="border-t border-white/10 px-5 py-4">
          <p className="text-[11px] text-white/30 leading-relaxed">
            AML Investigation Platform
          </p>
          <p className="text-[11px] text-white/20">v0.1 · demo</p>
        </div>
      </aside>

      {/* Content */}
      <main className="flex flex-1 flex-col overflow-hidden">
        {children}
      </main>
    </div>
  );
}
