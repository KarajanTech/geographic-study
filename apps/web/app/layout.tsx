import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Sentinel Planner",
  description: "Geospatial planning of wildfire surveillance tower networks.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>): React.ReactElement {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
