"use client";

import { useMemo, useRef, useState } from "react";
import { seed as SEED } from "@/lib/seed";
import { number, rupiah, rupiahCompact } from "@/lib/format";
import { Caveat, Card, Stat } from "@/components/ui";
import {
  analyseUpload,
  rankRows,
  LABEL_BUDGET,
  LABEL_SEVERITY,
  LABEL_STOKOUT,
  type BudgetStatus,
  type Severity,
  type StockoutStatus,
  type UploadResult,
  type UploadRow,
  type UploadedText,
} from "@/lib/upload";

type Zone = "internal" | "sales";

/* -------------------------------------------------------------------------- */
/* Badges                                                                      */
/* -------------------------------------------------------------------------- */

const badge = "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap";

const STOKOUT_STYLE: Record<StockoutStatus, string> = {
  OUT_OF_STOCK: "bg-red-100 text-red-800 ring-1 ring-red-200",
  AT_RISK: "bg-orange-100 text-orange-800 ring-1 ring-orange-200",
  HEALTHY: "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200",
  DORMANT: "bg-slate-100 text-slate-600 ring-1 ring-slate-200",
};

const SEVERITY_STYLE: Record<Severity, string> = {
  CRITICAL: "bg-red-100 text-red-800 ring-1 ring-red-200",
  AT_RISK: "bg-orange-100 text-orange-800 ring-1 ring-orange-200",
  WATCH: "bg-amber-100 text-amber-800 ring-1 ring-amber-200",
  OK: "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200",
};

function ChannelTag({ value }: { value: string }) {
  const style =
    value === "Shopee" ? "bg-orange-50 text-orange-700 ring-1 ring-orange-200" : "bg-slate-900 text-white";
  return <span className={`${badge} ${style}`}>{value}</span>;
}

function StockoutTag({ value }: { value: StockoutStatus }) {
  return <span className={`${badge} ${STOKOUT_STYLE[value]}`}>{LABEL_STOKOUT[value]}</span>;
}

function SeverityTag({ value }: { value: Severity }) {
  return <span className={`${badge} ${SEVERITY_STYLE[value]}`}>{LABEL_SEVERITY[value]}</span>;
}

/* -------------------------------------------------------------------------- */
/* Drop zone                                                                   */
/* -------------------------------------------------------------------------- */

function DropZone({
  step,
  title,
  subtitle,
  accept,
  hint,
  files,
  onAdd,
  onRemove,
}: {
  step: string;
  title: string;
  subtitle: string;
  accept: string;
  hint: string;
  files: UploadedText[];
  onAdd: (files: File[]) => void;
  onRemove: (name: string) => void;
}) {
  const [active, setActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="flex flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex items-start gap-3 border-b border-slate-100 px-4 py-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">
          {step}
        </span>
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
        </div>
      </div>

      <div className="flex grow flex-col gap-3 p-4">
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragEnter={(e) => {
            e.preventDefault();
            setActive(true);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setActive(true);
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            setActive(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setActive(false);
            onAdd(Array.from(e.dataTransfer.files));
          }}
          className={`cursor-pointer rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 ${
            active ? "border-slate-900 bg-slate-100" : "border-slate-300 bg-slate-50 hover:bg-slate-100"
          }`}
        >
          <p className="text-sm font-medium text-slate-700">Taruh berkas di sini</p>
          <p className="mt-1 text-xs text-slate-500">atau klik untuk memilih · bisa beberapa berkas sekaligus</p>
          <span className="mt-3 inline-block rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white">
            Pilih berkas
          </span>
          <input
            ref={inputRef}
            type="file"
            accept={accept}
            multiple
            className="hidden"
            onChange={(e) => {
              onAdd(Array.from(e.target.files ?? []));
              e.target.value = "";
            }}
          />
        </div>

        <p className="text-xs text-slate-500">{hint}</p>

        {files.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {files.map((file) => (
              <li
                key={file.name}
                className="inline-flex items-center gap-2 rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700"
              >
                <span className="max-w-56 truncate font-medium">{file.name}</span>
                <button
                  type="button"
                  aria-label={`Hapus ${file.name}`}
                  onClick={() => onRemove(file.name)}
                  className="text-slate-400 transition-colors hover:text-red-600"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Result                                                                      */
/* -------------------------------------------------------------------------- */

function ResultTable({ rows }: { rows: UploadRow[] }) {
  if (!rows.length) {
    return (
      <div className="px-4 py-10 text-center text-sm text-slate-500">
        Tidak ada SKU yang perlu tindakan dari berkas yang diunggah.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
            <th className="px-3 py-2 font-medium">Produk</th>
            <th className="px-3 py-2 font-medium">Marketplace</th>
            <th className="px-3 py-2 font-medium">Stok</th>
            <th className="px-3 py-2 font-medium">Margin</th>
            <th className="px-3 py-2 text-right font-medium">Tayang</th>
            <th className="px-3 py-2 text-right font-medium">Terjual 7h</th>
            <th className="px-3 py-2 text-right font-medium">Cadangan</th>
            <th className="px-3 py-2 text-right font-medium">Rugi/unit</th>
            <th className="px-3 py-2 text-right font-medium">Total rugi</th>
            <th className="px-3 py-2 text-right font-medium">Harga saran</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.sku}|${row.channel}`} className="border-t border-slate-100 align-top hover:bg-slate-50">
              <td className="px-3 py-2">
                <span className="font-medium text-slate-900">{row.name}</span>
                <span className="mt-0.5 block font-mono text-xs text-slate-400">{row.sku}</span>
              </td>
              <td className="px-3 py-2">
                <ChannelTag value={row.channel} />
              </td>
              <td className="px-3 py-2">
                <StockoutTag value={row.stockout_status} />
              </td>
              <td className="px-3 py-2">
                <SeverityTag value={row.severity} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-700">{number(row.allocated)}</td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                {row.sold_units_window > 0 ? number(row.sold_units_window) : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                {row.cover_days === null ? "—" : `${number(row.cover_days, 1)} hari`}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                {row.under_cogs_per_unit > 0 ? rupiah(row.under_cogs_per_unit) : "—"}
              </td>
              <td className="px-3 py-2 text-right font-medium tabular-nums text-red-700">
                {row.under_cogs_total > 0 ? rupiah(row.under_cogs_total) : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                {row.under_cogs_per_unit > 0 && row.recommended_price > 0 ? rupiah(row.recommended_price) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FileReports({ result }: { result: UploadResult }) {
  if (!result.files.length) return null;
  return (
    <ul className="divide-y divide-slate-100">
      {result.files.map((file, index) => (
        <li key={`${file.name}-${index}`} className="flex items-center justify-between gap-4 px-4 py-2 text-sm">
          <span className="min-w-0">
            <span className="block truncate font-medium text-slate-800">{file.name}</span>
            <span className="text-xs text-slate-500">
              {file.zone === "internal" ? "Data internal" : "Penjualan & inventori"}
              {file.marketplace ? ` · ${file.marketplace}` : ""}
              {file.kind === "inventory" ? " · inventori" : file.kind === "sales" ? " · pesanan" : ""}
            </span>
          </span>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
              file.ok ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-red-50 text-red-700 ring-red-200"
            }`}
          >
            {file.message}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function UploadPage() {
  const [internal, setInternal] = useState<UploadedText[]>([]);
  const [sales, setSales] = useState<UploadedText[]>([]);

  const result = useMemo<UploadResult | null>(() => {
    if (!internal.length && !sales.length) return null;
    try {
      return analyseUpload(internal, sales, SEED);
    } catch {
      return null;
    }
  }, [internal, sales]);

  const add = async (zone: Zone, files: File[]) => {
    if (!files.length) return;
    const read = await Promise.all(files.map(async (file) => ({ name: file.name, text: await file.text() })));
    const setter = zone === "internal" ? setInternal : setSales;
    setter((previous) => {
      const merged = [...previous];
      for (const item of read) {
        const existing = merged.findIndex((f) => f.name === item.name);
        if (existing === -1) merged.push(item);
        else merged[existing] = item; // re-dropping the same filename replaces it
      }
      return merged;
    });
  };

  const remove = (zone: Zone, name: string) => {
    const setter = zone === "internal" ? setInternal : setSales;
    setter((previous) => previous.filter((f) => f.name !== name));
  };

  const hasFiles = internal.length > 0 || sales.length > 0;
  const actionable = result ? rankRows(result.rows) : [];
  const summary = result?.summary;

  const budgetTone = (status: BudgetStatus) =>
    status === "HEALTHY" ? "good" : status === "CAUTION" ? "warn" : "bad";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Unggah Data</h1>
          <p className="mt-0.5 max-w-2xl text-sm text-slate-500">
            Unggah hasil ekspor dari seller centre. Analisis langsung dihitung di peramban dari berkas yang Anda
            pilih — tidak ada berkas yang dikirim ke mana pun.
          </p>
        </div>
        {hasFiles && (
          <button
            type="button"
            onClick={() => {
              setInternal([]);
              setSales([]);
            }}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
          >
            Bersihkan
          </button>
        )}
      </div>

      <Caveat>
        Peraga ini bersifat <strong>advisory</strong> — tidak ada marketplace yang ikut diubah. Angka komisi dan
        biaya masih placeholder, dan HPP diambil dari berkas <em>Data internal</em> Anda (atau dari contoh bawaan
        bila kolom tidak diunggah).
      </Caveat>

      {/* Dua tempat unggah, langkah jelas. */}
      <div className="grid gap-4 lg:grid-cols-2">
        <DropZone
          step="1"
          title="Data internal"
          subtitle="HPP / harga pokok per SKU (kolom: Seller SKU + Current Cost)"
          accept=".csv,text/csv"
          hint="Opsional. Tanpa berkas ini, HPP memakai contoh bawaan sehingga margin tetap bisa dihitung."
          files={internal}
          onAdd={(files) => add("internal", files)}
          onRemove={(name) => remove("internal", name)}
        />
        <DropZone
          step="2"
          title="Data penjualan & inventori"
          subtitle="Ekspor pesanan dan inventori dari Shopee / TikTok Shop"
          accept=".csv,text/csv"
          hint="Jenis berkas dideteksi dari nama kolom, bukan nama berkas. Beberapa berkas boleh diunggah sekaligus."
          files={sales}
          onAdd={(files) => add("sales", files)}
          onRemove={(name) => remove("sales", name)}
        />
      </div>

      {/* Ringkasan hasil unggahan */}
      {summary && (
        <>
          <Card
            title="Ringkasan hasil unggahan"
            subtitle={`${number(summary.rows)} baris SKU × marketplace dianalisis`}
          >
            <div className="grid grid-cols-2 gap-3 p-4 lg:grid-cols-4">
              <Stat
                label="Perlu tindakan"
                value={number(actionable.length)}
                hint={`${summary.critical} kritis · ${summary.at_risk + summary.out_of_stock} masalah stok`}
                tone={summary.critical > 0 ? "bad" : "neutral"}
              />
              <Stat
                label="Di bawah HPP"
                value={number(summary.below_cost)}
                hint={`dari ${number(summary.rows)} baris`}
                tone={summary.below_cost > 0 ? "warn" : "good"}
              />
              <Stat
                label="Total kerugian"
                value={rupiahCompact(summary.gross_exposure)}
                hint="kerugian saja; laba tidak mengurangi"
                tone={summary.gross_exposure > 0 ? "bad" : "good"}
              />
              <Stat
                label="Sisa anggaran kampanye"
                value={rupiahCompact(summary.budget_safe)}
                hint={`${number(summary.budget_remaining_pct, 1)}% · ${LABEL_BUDGET[summary.budget_status]}`}
                tone={budgetTone(summary.budget_status)}
              />
            </div>
          </Card>

          <Card title="Berkas yang dibaca">
            <FileReports result={result} />
          </Card>

          {result!.used_seed_catalogue && (
            <Caveat>
              Belum ada berkas <em>Data internal</em>, jadi HPP memakai contoh bawaan ({number(SEED.products.length)}{" "}
              SKU). Margin akan lebih akurat bila Anda mengunggah berkas HPP sendiri.
            </Caveat>
          )}

          {result!.orphan_skus.length > 0 && (
            <Caveat>
              {number(result!.orphan_skus.length)} SKU muncul di ekspor tetapi tidak ada di tabel HPP, sehingga
              diabaikan: {result!.orphan_skus.slice(0, 4).join(", ")}
              {result!.orphan_skus.length > 4 ? ", …" : ""}
            </Caveat>
          )}

          <Card
            title="Daftar tindakan"
            subtitle={`${number(actionable.length)} baris perlu tindakan, diurutkan dari risiko terbesar`}
          >
            <ResultTable rows={actionable} />
          </Card>
        </>
      )}

      {/* Sebelum ada berkas: jelaskan konteks bawaan supaya halaman tidak kosong. */}
      {!hasFiles && (
        <Card title="Data contoh yang sedang aktif" subtitle={`Per tanggal ${SEED.as_of}`}>
          <div className="grid grid-cols-2 gap-3 p-4 lg:grid-cols-4">
            <Stat label="SKU tersedia" value={number(SEED.products.length)} hint="tabel HPP bawaan" />
            <Stat label="Baris listing" value={number(SEED.listings.length)} hint="SKU × marketplace" />
            <Stat label="Jendela run-rate" value={`${SEED.config.run_rate_window_hours} jam`} hint="7 hari terakhir" />
            <Stat
              label="Anggaran kampanye"
              value={rupiahCompact(SEED.config.campaign_budget)}
              hint="cadangan, bukan uang terpakai"
            />
          </div>
        </Card>
      )}
    </div>
  );
}