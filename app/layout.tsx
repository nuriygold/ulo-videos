import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Ulo Videos", description: "Deterministic cloud video production workspace" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
