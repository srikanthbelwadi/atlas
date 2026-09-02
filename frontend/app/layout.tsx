import type { Metadata } from "next";
import { AuthProvider } from "@/lib/auth-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "Atlas — ask large-scale data a question",
  description: "A natural-language front door to large-scale data — any warehouse or API described in OKF, discovered via ARD, answered by Gemini under hard cost guardrails.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
