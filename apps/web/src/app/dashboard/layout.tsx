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
    <>
      {/* Mobile fallback — dashboard is desktop-first (≥1024px) */}
      <div className="flex min-h-screen items-center justify-center bg-surface-base px-6 lg:hidden">
        <div className="max-w-xs text-center">
          <div className="mb-4 font-mono text-2xl text-accent-DEFAULT">⬡</div>
          <p className="text-sm font-medium text-white">Desktop required</p>
          <p className="mt-2 text-xs text-text-muted leading-relaxed">
            Argonis is optimised for desktop browsers (1024px+). Please open
            this page on a larger screen.
          </p>
        </div>
      </div>

      {/* Desktop layout */}
      <div className="hidden h-screen overflow-hidden bg-surface-base lg:flex">
        {/* Sidebar */}
        <aside className="flex w-[200px] shrink-0 flex-col border-r border-border bg-surface-1">
          {/* Logo */}
          <div className="flex h-12 items-center border-b border-border px-4">
            <span className="font-mono text-[13px] font-medium tracking-widest text-accent-DEFAULT uppercase">
              Argonis
            </span>
          </div>

          {/* Nav */}
          <nav className="flex-1 px-2 py-3 space-y-px">
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
                    "flex items-center gap-2.5 rounded px-2.5 py-1.5 text-xs transition-colors",
                    active
                      ? "bg-surface-3 text-white"
                      : "text-text-muted hover:bg-surface-2 hover:text-white",
                  ].join(" ")}
                >
                  <span className="text-[10px] opacity-50">{item.icon}</span>
                  {item.label}
                </Link>
              );
            })}
          </nav>

          {/* Footer */}
          <div className="border-t border-border px-4 py-3">
            <p className="text-[10px] uppercase tracking-wider text-text-faint">
              AML Platform
            </p>
            <p className="text-[10px] text-text-faint opacity-50">v0.1 · demo</p>
          </div>
        </aside>

        {/* Content */}
        <main className="flex flex-1 flex-col overflow-hidden">{children}</main>
      </div>
    </>
  );
}
