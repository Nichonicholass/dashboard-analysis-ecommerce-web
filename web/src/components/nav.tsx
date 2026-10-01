import Link from "next/link";

const links = [
  { href: "/", label: "Daftar Tindakan" },
  { href: "/upload", label: "Unggah Data" },
  { href: "/brands", label: "Merek" },
];

export function Nav() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
        <Link href="/" className="text-sm font-semibold tracking-tight text-slate-900">
          Penasihat Alokasi &amp; Margin Marketplace
        </Link>
        <nav className="flex gap-1">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-md px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <span className="ml-auto rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
          Peraga · hanya saran
        </span>
      </div>
    </header>
  );
}