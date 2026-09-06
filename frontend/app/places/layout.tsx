import { notFound } from "next/navigation";
import { PLACES_ENABLED } from "@/lib/places";

// Same guard as /finance: Firebase App Hosting deploys `main` automatically,
// so with the flag off every /places/* route must 404 until the backend has
// the places pack enabled (ATLAS_PACKS_ENABLED) and a Data Commons key.
export default function PlacesLayout({ children }: { children: React.ReactNode }) {
  if (!PLACES_ENABLED) notFound();
  return <>{children}</>;
}
