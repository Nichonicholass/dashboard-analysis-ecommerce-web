import type { Metadata } from "next";
import { Nav } from "@/components/nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Penasihat Alokasi & Margin Marketplace",
  description:
    "Peraga untuk Account Manager: risiko kehabisan stok dan penjualan di bawah HPP di Shopee dan TikTok Shop.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <Nav />
        <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
        <footer className="mx-auto max-w-7xl px-6 pb-8 text-xs text-slate-400">
          Analisis dihitung oleh <code className="font-mono">src/metrics.py</code>, divalidasi 39 checkpoint di{" "}
          <code className="font-mono">checkpoint.json</code>. Hanya rekomendasi — tidak ada marketplace yang diubah.
        </footer>
      </body>
    </html>
  );
}