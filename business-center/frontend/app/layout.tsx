import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "AI Business Center", description: "YouTube + Etsy yönetim merkezi" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body className="min-h-screen font-sans antialiased">{children}</body>
    </html>
  );
}
