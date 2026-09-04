"use client";

import { useCallback, useEffect, useState } from "react";
import Header from "@/components/Header";
import SignInGate from "@/components/SignInGate";
import { useAuth } from "@/lib/auth-context";
import { adminListEntitlements, adminListUsers, adminSetEntitlements, adminSetUserStatus, ApiError } from "@/lib/api";
import { AdminUser, EntitlementInfo, UserStatus } from "@/lib/types";

const STATUS_COLOR: Record<UserStatus, string> = {
  pending: "var(--accent)",
  approved: "var(--accent-2)",
  rejected: "var(--danger)",
};

function AdminConsole() {
  const { getIdToken } = useAuth();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [entitlements, setEntitlements] = useState<EntitlementInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyUid, setBusyUid] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const token = await getIdToken();
      if (!token) throw new ApiError(401, "Not signed in");
      const [u, e] = await Promise.all([adminListUsers(token), adminListEntitlements(token).catch(() => [])]);
      setUsers(u);
      setEntitlements(e);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load users.");
    }
  }, [getIdToken]);

  useEffect(() => {
    load();
  }, [load]);

  const act = async (uid: string, action: "approve" | "reject") => {
    setBusyUid(uid);
    try {
      const token = await getIdToken();
      if (!token) throw new ApiError(401, "Not signed in");
      await adminSetUserStatus(token, uid, action);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't go through — try again.");
    } finally {
      setBusyUid(null);
    }
  };

  // Finance pack, use case D: data entitlements. Approval says "may use
  // Atlas"; an entitlement says "may be offered this private source".
  // Toggling one rewrites the user's whole list; it applies on their next
  // request.
  const toggleEntitlement = async (u: AdminUser, ent: string) => {
    setBusyUid(u.uid);
    try {
      const token = await getIdToken();
      if (!token) throw new ApiError(401, "Not signed in");
      const current = new Set(u.entitlements || []);
      if (current.has(ent)) current.delete(ent);
      else current.add(ent);
      await adminSetEntitlements(token, u.uid, Array.from(current));
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't go through — try again.");
    } finally {
      setBusyUid(null);
    }
  };

  if (error) {
    return (
      <div className="container" style={{ padding: "60px 0" }}>
        <div style={{ background: "var(--danger-soft)", color: "var(--danger)", borderRadius: 10, padding: "16px 18px" }}>{error}</div>
      </div>
    );
  }

  if (!users) {
    return (
      <div className="container" style={{ padding: "60px 0", color: "var(--ink-dim)" }}>
        Loading users…
      </div>
    );
  }

  const pending = users.filter((u) => u.status === "pending");
  const others = users.filter((u) => u.status !== "pending");

  return (
    <div className="container" style={{ padding: "40px 0 80px" }}>
      <h2 style={{ fontSize: "1.4rem", marginBottom: 4 }}>Approval console</h2>
      <p style={{ color: "var(--ink-dim)", fontSize: "0.9rem", marginTop: 0, marginBottom: 28 }}>
        {pending.length} waiting on approval · {users.length} total account{users.length === 1 ? "" : "s"}
      </p>

      {pending.length > 0 && (
        <UserTable title="Pending" rows={pending} onApprove={(uid) => act(uid, "approve")} onReject={(uid) => act(uid, "reject")} busyUid={busyUid} />
      )}
      <div style={{ height: 28 }} />
      <UserTable
        title="Everyone else"
        rows={others}
        onApprove={(uid) => act(uid, "approve")}
        onReject={(uid) => act(uid, "reject")}
        busyUid={busyUid}
        entitlements={entitlements}
        onToggleEntitlement={toggleEntitlement}
      />
      {entitlements.length > 0 && (
        <p style={{ color: "var(--ink-dim)", fontSize: "0.8rem", marginTop: 18, maxWidth: "70ch" }}>
          Data entitlements unlock private catalog sources for an approved account (finance pack, use case D). Without one, a
          private source is withheld from discovery and the user sees a refusal that names it. Currently defined:{" "}
          {entitlements.map((e) => (
            <span key={e.id}>
              <span className="mono">{e.id}</span> ({e.sources.length} source{e.sources.length === 1 ? "" : "s"}){" "}
            </span>
          ))}
        </p>
      )}
    </div>
  );
}

function UserTable({
  title,
  rows,
  onApprove,
  onReject,
  busyUid,
  entitlements = [],
  onToggleEntitlement,
}: {
  title: string;
  rows: AdminUser[];
  onApprove: (uid: string) => void;
  onReject: (uid: string) => void;
  busyUid: string | null;
  entitlements?: EntitlementInfo[];
  onToggleEntitlement?: (u: AdminUser, ent: string) => void;
}) {
  if (!rows.length) return null;
  return (
    <div>
      <div style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--ink-dim)", marginBottom: 10 }}>{title}</div>
      <div style={{ border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
        {rows.map((u, i) => (
          <div
            key={u.uid}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "12px 16px",
              borderTop: i === 0 ? "none" : "1px solid var(--border)",
              background: "var(--surface)",
            }}
          >
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: STATUS_COLOR[u.status], flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "0.9rem" }}>{u.display_name || u.email}</div>
              <div style={{ fontSize: "0.78rem", color: "var(--ink-dim)" }}>{u.email}</div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
              {u.status === "approved" &&
                onToggleEntitlement &&
                entitlements.map((e) => {
                  const on = (u.entitlements || []).includes(e.id);
                  return (
                    <button
                      key={e.id}
                      type="button"
                      onClick={() => onToggleEntitlement(u, e.id)}
                      disabled={busyUid === u.uid}
                      title={on ? `Revoke ${e.id}` : `Grant ${e.id} (${e.sources.length} private sources)`}
                      className={`trust-chip private${on ? "" : " locked"}`}
                      style={{ cursor: busyUid === u.uid ? "default" : "pointer", border: "none" }}
                    >
                      🔒 {e.id} {on ? "· granted" : "· off"}
                    </button>
                  );
                })}
              {u.status !== "approved" && (
                <ActionButton label="Approve" onClick={() => onApprove(u.uid)} busy={busyUid === u.uid} kind="accept" />
              )}
              {u.status !== "rejected" && (
                <ActionButton label="Reject" onClick={() => onReject(u.uid)} busy={busyUid === u.uid} kind="reject" />
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActionButton({ label, onClick, busy, kind }: { label: string; onClick: () => void; busy: boolean; kind: "accept" | "reject" }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      style={{
        fontSize: "0.8rem",
        padding: "6px 12px",
        borderRadius: 6,
        border: `1px solid ${kind === "accept" ? "var(--accent-2)" : "var(--border)"}`,
        background: kind === "accept" ? "var(--accent-2-soft)" : "transparent",
        color: kind === "accept" ? "var(--accent-2)" : "var(--ink-dim)",
        cursor: busy ? "default" : "pointer",
        opacity: busy ? 0.6 : 1,
      }}
    >
      {label}
    </button>
  );
}

export default function AdminPage() {
  return (
    <>
      <Header />
      <SignInGate>
        <AdminConsole />
      </SignInGate>
    </>
  );
}
