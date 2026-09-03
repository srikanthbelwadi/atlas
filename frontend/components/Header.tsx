"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import Logo from "@/components/Logo";
import { FINANCE_ENABLED } from "@/lib/finance";

const GITHUB_URL = "https://github.com/srikanthbelwadi/atlas";

export default function Header() {
  const { user, signOutUser } = useAuth();

  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        padding: "18px 0",
      }}
    >
      <div className="container" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <Link href="/" style={{ textDecoration: "none", color: "inherit", display: "flex", alignItems: "center", gap: 10 }}>
          <Logo size={26} />
          <h1 style={{ fontSize: "1.35rem" }}>Atlas</h1>
        </Link>

        <nav style={{ display: "flex", alignItems: "center", gap: 20, fontSize: "0.85rem" }}>
          {/* Only meaningful pre-sign-in: the "how it works" section lives inside
              SignInGate's own signed-out markup, so it only exists in the DOM
              on whatever page is currently rendering that gate — which, for a
              signed-out visitor, is every page (SignInGate ignores its
              children and renders the same marketing gate regardless of which
              page invoked it). The absolute "/#how-it-works" href, rather than
              a bare "#how-it-works", is what makes this work correctly from
              /implementation too, which never renders SignInGate at all. */}
          {!user && (
            <a href="/#how-it-works" className="nav-link">
              How it works
            </a>
          )}
          {FINANCE_ENABLED && (
            <Link href="/finance" className="nav-link">
              Finance
            </Link>
          )}
          <Link href="/implementation" className="nav-link">
            Implementation
          </Link>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="nav-link">
            GitHub
          </a>

          {user && (
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <Link href="/admin" className="nav-link">
                Admin
              </Link>
              <span style={{ color: "var(--ink-dim)" }}>{user.email}</span>
              <button
                onClick={() => signOutUser()}
                style={{
                  background: "none",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  padding: "6px 12px",
                  cursor: "pointer",
                  color: "var(--ink)",
                  fontSize: "0.85rem",
                }}
              >
                Sign out
              </button>
            </div>
          )}
        </nav>
      </div>
    </header>
  );
}
