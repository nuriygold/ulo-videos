import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://ulo-videos.vercel.app"),
  title: "ulo-videos",
  description: "Deterministic cloud video production workspace",
  icons: { icon: "/ulo-videos-logo.svg" },
  openGraph: {
    title: "ulo-videos",
    description: "Deterministic cloud video production workspace",
    type: "website",
    images: [{ url: "/ulo-videos-logo.svg", alt: "ulo-videos" }],
  },
  twitter: {
    card: "summary",
    title: "ulo-videos",
    description: "Deterministic cloud video production workspace",
    images: ["/ulo-videos-logo.svg"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
