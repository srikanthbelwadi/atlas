"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import Logo from "@/components/Logo";

export default function Header() {
  const { user, signOutUser } = useAuth();

  return (
    <header
      style={{
        borderBottom: "1px solid var(--border)",
        padding: "18px 0",
      }}
    >
      <div className="container" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Link href="/" style={{ textDecoration: "none", color: "inherit", display: "flex", alignItems: "center", gap: 10 }}>
          <Logo size={26} />
          <h1 style={{ fontSize: "1.35rem" }}>Atlas</h1>
        </Link>
        {user && (
          <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: "0.85rem" }}>
            <Link href="/admin" style={{ color: "var(--ink-dim)" }}>
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
              }}
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
