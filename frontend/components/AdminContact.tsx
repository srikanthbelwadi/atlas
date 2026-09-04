"use client";

import { ADMIN_CONTACT, adminMailto } from "@/lib/admin-contact";

/** "contact your Atlas administrator", as a mailto link when one is configured. */
export default function AdminContact({ subject, body, children }: { subject: string; body?: string; children?: React.ReactNode }) {
  const href = adminMailto(subject, body);
  const label = children ?? "your Atlas administrator";
  if (!href) return <>{label}</>;
  return (
    <a href={href} className="nav-link" style={{ textDecoration: "underline" }} title={ADMIN_CONTACT}>
      {label}
    </a>
  );
}
