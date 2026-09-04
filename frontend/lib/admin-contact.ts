// Who a user contacts when they need account approval or an entitlement
// (private data). Baked in at build time; when unset, copy falls back to
// "your Atlas administrator" with no link. Set in apphosting.yaml.
export const ADMIN_CONTACT = process.env.NEXT_PUBLIC_ATLAS_ADMIN_CONTACT || "";

export function adminMailto(subject: string, body?: string): string | null {
  if (!ADMIN_CONTACT) return null;
  const q = new URLSearchParams({ subject, ...(body ? { body } : {}) });
  return `mailto:${ADMIN_CONTACT}?${q.toString()}`;
}
