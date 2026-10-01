/* ==========================================================================
   Asisten AM — satu halaman, tanpa server.
   Semua perhitungan di bawah adalah port dari src/metrics.py (tech_spec.md §5-§8).
   Port ini diverifikasi agar menghasilkan angka identik dengan versi Python.
   ========================================================================== */

/* ---------------------------------------------------------------- konfigurasi */
// Sama dengan tech_spec.md §9. Horizon 168 jam (bukan 1 jam) karena data
// marketplace bergerak lambat — lihat tech_spec.md §6.4.
var KONFIG = {
  jendelaJam: 168,          // run rate = 7 hari terakhir
  jendelaCadanganJam: 720,  // 30 hari, untuk SKU yang jarang terjual
  horizonJam: 168,          // ambang peringatan stok
  targetCoverJam: 336,      // 14 hari cadangan saat memindahkan stok
  targetMargin: 0.15,
  anggaranKampanye: 50000000
};

// Tingkat komisi per marketplace — angka sementara (tech_spec.md §5.2).
var KOMISI = {
  "Shopee":      { komisi: 0.080, admin: 1250, pembayaran: 0.020, afiliasi: 0.00 },
  "TikTok Shop": { komisi: 0.065, admin: 1000, pembayaran: 0.020, afiliasi: 0.05 }
};

/* ------------------------------------------------------- §5 komisi & potongan */
function tarifVariabel(f) {
  return f.komisi + f.pembayaran + f.afiliasi;   // biaya admin tetap, bukan persen
}

/** Yang benar-benar diterima penjual per unit. `harga` = yang dibayar pembeli per unit. */
function diterimaPerUnit(harga, unit, f) {
  if (unit <= 0) return 0;
  return harga * (1 - tarifVariabel(f)) - (f.admin / unit);
}

/* ---------------------------------------------------- §6 run rate & stok habis */
function runRatePerJam(unitTerjual, jamObservasi) {
  if (jamObservasi <= 0) return 0;
  return unitTerjual / jamObservasi;
}

function jamSampaiHabis(dialokasikan, laju) {
  if (laju <= 0) return null;          // SKU tidur — tidak ada arti "waktu habis"
  return dialokasikan / laju;
}

/** Urutan penting: tidur diperiksa sebelum habis. */
function klasifikasiStok(dialokasikan, laju, horizonJam) {
  if (laju <= 0) return "TIDAK_TERJUAL";
  if (dialokasikan <= 0) return "HABIS";
  var sisa = jamSampaiHabis(dialokasikan, laju);
  return (sisa !== null && sisa <= horizonJam) ? "HAMPIR_HABIS" : "AMAN";
}

/* -------------------------------------------------- §7 di bawah HPP & margin */
function selisihPerUnit(hpp, harga, unit, f) {
  return hpp - diterimaPerUnit(harga, unit, f);
}

/** Ambang dihitung terhadap HPP, bukan harga jual. */
function klasifikasiTingkat(selisihUnit, hpp) {
  if (hpp <= 0) return "PROFIT";
  var rasio = selisihUnit / hpp;
  if (selisihUnit > 0) return rasio > 0.10 ? "KRITIS" : "BERISIKO";
  return rasio > -0.05 ? "PANTAU" : "PROFIT";
}

/** harga = (hpp x (1+margin) + admin/unit) / (1 - tarif variabel) */
function hargaSaran(hpp, margin, unit, f) {
  var tarif = tarifVariabel(f);
  if (tarif >= 1 || unit <= 0) return 0;
  return (hpp * (1 + margin) + f.admin / unit) / (1 - tarif);
}

/** Hanya kerugian yang dihitung — laba di SKU lain tidak mengembalikan anggaran. */
function eksposurKotor(daftar) {
  return daftar.reduce(function (t, v) { return t + (v > 0 ? v : 0); }, 0);
}

/* ------------------------------------------------------------ §8 anggaran aman */
function anggaranAman(anggaran, eksposur) { return anggaran - eksposur; }

function statusAnggaran(anggaran, eksposur) {
  var sisa = anggaranAman(anggaran, eksposur);
  if (sisa <= 0) return "TERLAMPAUI";
  return sisa > 0.5 * anggaran ? "AMAN" : "PERHATIAN";
}

/* ============================================================================
   Pembacaan CSV
   ============================================================================ */
function bacaCSV(teks) {
  teks = teks.replace(/^\uFEFF/, "");
  var baris = [], sel = [], isi = "", dalamKutip = false;
  for (var i = 0; i < teks.length; i++) {
    var c = teks[i];
    if (dalamKutip) {
      if (c === '"') {
        if (teks[i + 1] === '"') { isi += '"'; i++; }
        else dalamKutip = false;
      } else isi += c;
    } else if (c === '"') dalamKutip = true;
    else if (c === ",") { sel.push(isi); isi = ""; }
    else if (c === "\n") { sel.push(isi); baris.push(sel); sel = []; isi = ""; }
    else if (c !== "\r") isi += c;
  }
  if (isi !== "" || sel.length) { sel.push(isi); baris.push(sel); }
  if (!baris.length) return [];
  var kepala = baris[0].map(function (h) { return h.trim(); });
  return baris.slice(1).filter(function (b) {
    return b.length > 1 || (b[0] && b[0].trim() !== "");
  }).map(function (b) {
    var o = {};
    kepala.forEach(function (h, i) { o[h] = (b[i] || "").trim(); });
    return o;
  });
}

/**
 * Kenali marketplace dan jenis ekspor dari nama kolom, bukan dari nama file.
 *
 * Ekspor inventori memakai kolom yang berbeda dari ekspor pesanan, jadi kolom
 * inventori harus diperiksa lebih dulu — kalau tidak, file inventori selalu
 * ditolak dan jumlah tayang selalu nol.
 */
function kenaliEkspor(kepala) {
  var ada = function (k) { return kepala.indexOf(k) !== -1; };

  var inventori = ada("Available Inventory") || ada("Reserved Stock") || ada("Stock");

  var marketplace = null;
  if (ada("Order Substatus") || ada("SKU ID") || ada("Available Inventory")) {
    marketplace = "TikTok Shop";
  } else if (ada("SKU Reference No.") || ada("Deal Price") || ada("Parent SKU")) {
    marketplace = "Shopee";
  }

  return { marketplace: marketplace, jenis: inventori ? "inventori" : "penjualan" };
}

var STATUS_TERJUAL = {
  "Shopee": ["Completed", "Shipped"],
  "TikTok Shop": ["Completed", "In Transit"]
};

function ambilTanggal(teks) {
  if (!teks) return null;
  // Ekspor memakai "YYYY-MM-DD HH:MM:SS"; Safari butuh bentuk ISO.
  var t = new Date(teks.replace(" ", "T") + "+07:00");
  return isNaN(t.getTime()) ? null : t;
}

/* ============================================================================
   Perhitungan
   ============================================================================ */

/** Ubah baris CSV menjadi catatan penjualan + daftar jumlah tayang per SKU. */
function rangkumEkspor(berkas, hpp) {
  var hasil = {
    terjual: {},        // "sellerSku|marketplace" -> unit
    terjualLama: {},    // jendela cadangan 30 hari
    pendapatan: {},     // "sellerSku|marketplace" -> nilai bersih
    dialokasikan: {},   // sellerSku -> { marketplace: unit }
    berkas: [],
    bukanPenjualan: {}  // sellerSku -> true, muncul di ekspor tapi tidak di katalog HPP
  };

  var batasJendela = new Date(BATAS_DASAR.getTime() - KONFIG.jendelaJam * 3600000);
  var batasCadangan = new Date(BATAS_DASAR.getTime() - KONFIG.jendelaCadanganJam * 3600000);

  berkas.forEach(function (b) {
    var kunci = b.nama + "|" + b.marketplace;
    if (!b.terbaca) {
      hasil.berkas.push({ nama: b.nama, marketplace: b.marketplace, ok: false,
                          pesan: b.pesan || "tidak dikenali", baris: 0 });
      return;
    }

    var dikenali = b.baris.filter(function (r) { return hpp[r.sellerSku] !== undefined; });
    if (dikenali.length !== b.baris.length) {
      b.baris.forEach(function (r) {
        if (hpp[r.sellerSku] === undefined) hasil.bukanPenjualan[r.sellerSku] = true;
      });
    }
    hasil.berkas.push({ nama: b.nama, marketplace: b.marketplace, ok: true,
                        pesan: "", baris: dikenali.length });

    var statusSah = STATUS_TERJUAL[b.marketplace] || [];

    dikenali.forEach(function (r) {
      var k = b.marketplace + "|" + r.sellerSku;

      // Jumlah tayang diambil dari ekspor inventori.
      if (r.jenis === "inventori") {
        if (!hasil.dialokasikan[r.sellerSku]) hasil.dialokasikan[r.sellerSku] = {};
        hasil.dialokasikan[r.sellerSku][b.marketplace] =
          (hasil.dialokasikan[r.sellerSku][b.marketplace] || 0) + r.tersedia;
        return;
      }

      if (statusSah.indexOf(r.status) === -1 || r.unit <= 0) return;

      if (r.waktu && r.waktu >= batasJendela) hasil.terjual[k] = (hasil.terjual[k] || 0) + r.unit;
      if (r.waktu && r.waktu >= batasCadangan) hasil.terjualLama[k] = (hasil.terjualLama[k] || 0) + r.unit;

      // Nilai bersih = harga setelah diskon, per unit.
      hasil.pendapatan[k] = hasil.pendapatan[k] ||
        { total: 0, unit: 0, harga: 0, berbobot: 0 };
      hasil.pendapatan[k].total += r.nilaiPerUnit * r.unit;
      hasil.pendapatan[k].unit += r.unit;
      hasil.pendapatan[k].berbobot += r.nilaiPerUnit * r.unit;
    });
  });

  return hasil;
}

/** Satu baris analisis per (SKU, marketplace). */
function hitungBaris(rangkuman, hpp, namaBarang) {
  var baris = [];
  var semuaSku = {};

  Object.keys(rangkuman.dialokasikan).forEach(function (s) { semuaSku[s] = true; });
  Object.keys(rangkuman.terjual).forEach(function (k) { semuaSku[k.split("|")[1]] = true; });
  Object.keys(rangkuman.pendapatan).forEach(function (k) { semuaSku[k.split("|")[1]] = true; });

  Object.keys(semuaSku).forEach(function (sku) {
    var perMarket = rangkuman.dialokasikan[sku] || {};
    // SKU bisa muncul di ekspor penjualan tanpa ekspor inventori; tetap tampilkan.
    if (Object.keys(perMarket).length === 0) {
      Object.keys(rangkuman.terjual).forEach(function (k) {
        var pisah = k.split("|");
        if (pisah[1] === sku) perMarket[pisah[0]] = 0;
      });
      Object.keys(rangkuman.pendapatan).forEach(function (k) {
        var pisah = k.split("|");
        if (pisah[1] === sku) perMarket[pisah[0]] = perMarket[pisah[0]] || 0;
      });
    }

    Object.keys(perMarket).forEach(function (market) {
      var f = KOMISI[market];
      if (!f) return;
      var k = market + "|" + sku;
      var dialokasikan = perMarket[market];
      var hppUnit = hpp[sku];
      var u7 = rangkuman.terjual[k] || 0;
      var u30 = rangkuman.terjualLama[k] || 0;
      var pend = rangkuman.pendapatan[k];

      // §6.1 — run rate dengan cadangan 30 hari untuk SKU lambat.
      var laju = u7 > 0 ? runRatePerJam(u7, KONFIG.jendelaJam)
               : u30 > 0 ? runRatePerJam(u30, KONFIG.jendelaCadanganJam)
               : 0;

      var jam = jamSampaiHabis(dialokasikan, laju);
      var status = klasifikasiStok(dialokasikan, laju, KONFIG.horizonJam);

      // §7 — margin, hanya kalau SKU benar-benar terjual.
      var hargaUnit = pend && pend.unit > 0 ? pend.total / pend.unit : 0;
      var diterima = pend && pend.unit > 0 ? diterimaPerUnit(hargaUnit, pend.unit, f) : 0;
      var selisihUnit = pend && pend.unit > 0 ? hppUnit - diterima : 0;
      var selisihTotal = selisihUnit * (pend ? pend.unit : 0);
      var tingkat = pend && pend.unit > 0 ? klasifikasiTingkat(selisihUnit, hppUnit) : "PROFIT";
      var saran = pend && pend.unit > 0 ? hargaSaran(hppUnit, KONFIG.targetMargin, pend.unit, f) : 0;

      baris.push({
        sku: sku, nama: namaBarang[sku] || sku, market: market,
        dialokasikan: dialokasikan,
        terjual7: u7, terjual30: u30, terjualPeriode: pend ? pend.unit : 0,
        hpp: hppUnit, hargaUnit: hargaUnit, diterima: diterima,
        laju: laju, jam: jam,
        sisaHari: jam === null ? null : jam / 24,
        status: status,
        selisihUnit: selisihUnit, selisihTotal: selisihTotal,
        tingkat: tingkat, hargaSaran: saran
      });
    });
  });

  return baris;
}

/* ============================================================================
   Saran pemindahan stok (tech_spec.md §6.5)
   ============================================================================ */
function saranAlokasi(baris) {
  var perSku = {};
  baris.forEach(function (b) {
    (perSku[b.sku] = perSku[b.sku] || []).push(b);
  });

  var saran = [];
  Object.keys(perSku).forEach(function (sku) {
    var semua = perSku[sku];
    var perlu = semua.filter(function (b) {
      return (b.status === "HAMPIR_HABIS" || b.status === "HABIS") && b.laju > 0;
    });
    if (!perlu.length) return;

    perlu.sort(function (a, b) {
      var r = { HABIS: 2, HAMPIR_HABIS: 1 };
      return (r[b.status] || 0) - (r[a.status] || 0);
    });
    var tujuan = perlu[0];

    var calon = semua.filter(function (b) {
      return b !== tujuan && b.status !== "HAMPIR_HABIS" && b.status !== "HABIS";
    });

    var terpilih = null, jumlah = 0;
    calon.forEach(function (donor) {
      var surplus = donor.dialokasikan - KONFIG.targetCoverJam * donor.laju;
      if (surplus <= 0) return;
      var butuh = Math.max(0, KONFIG.targetCoverJam * tujuan.laju - tujuan.dialokasikan);
      var pindah = Math.floor(Math.min(butuh, surplus));
      if (pindah > jumlah) { jumlah = pindah; terpilih = donor; }
    });

    saran.push({
      sku: sku, nama: tujuan.nama,
      dari: terpilih ? terpilih.market : null,
      ke: tujuan.market,
      unit: jumlah,
      alasan: tujuan.sisaHari === null
        ? "sudah habis"
        : fmtHari(tujuan.sisaHari) + " cadangan di " + tujuan.market,
      terhalang: terpilih === null
    });
  });

  return saran;
}

/* ============================================================================
   Tampilan
   ============================================================================ */
function rupiah(n) {
  return "Rp " + Math.round(n).toLocaleString("id-ID");
}
function rupiahRingkas(n) {
  var a = Math.abs(n);
  if (a >= 1e9) return "Rp " + (n / 1e9).toFixed(1).replace(".", ",") + " M";
  if (a >= 1e6) return "Rp " + (n / 1e6).toFixed(1).replace(".", ",") + " jt";
  if (a >= 1e3) return "Rp " + Math.round(n / 1e3) + " rb";
  return rupiah(n);
}
function angkaID(n, d) {
  return n.toLocaleString("id-ID", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
}
function fmtHari(h) {
  if (h === null) return "—";
  if (h === 0) return "0";
  if (h < 1) return angkaID(h * 24, 1) + " jam";
  if (h > 365) return angkaID(h / 365, 1) + " thn";
  return angkaID(h, 1) + " hari";
}

var LABEL_STOK = {
  HABIS: ["Habis", "merah"],
  HAMPIR_HABIS: ["Hampir habis", "kuning"],
  AMAN: ["Aman", "hijau"],
  TIDAK_TERJUAL: ["Tidak terjual", "abu"]
};
var LABEL_TINGKAT = {
  KRITIS: ["KRITIS", "merah"],
  BERISIKO: ["BERISIKO", "kuning"],
  PANTAU: ["PANTAU", "kuning"],
  PROFIT: ["PROFIT", "hijau"]
};
var LABEL_ANGGARAN = { AMAN: "hijau", PERHATIAN: "kuning", TERLAMPAUI: "merah" };

function tag(teks, warna) {
  return '<span class="tag ' + warna + '">' + teks + "</span>";
}
function tagMarket(m) {
  return tag(m, m === "Shopee" ? "kuning" : "gelap");
}

function gambar(hpp, namaBarang, baris, sumber, berkas, bukanPenjualan) {
  // --- ringkasan
  var eksposur = eksposurKotor(baris.map(function (b) { return b.selisihTotal; }));
  var bersih = baris.reduce(function (t, b) { return t + b.selisihTotal; }, 0);
  var aman = anggaranAman(KONFIG.anggaranKampanye, eksposur);
  var stAnggaran = statusAnggaran(KONFIG.anggaranKampanye, eksposur);

  var kritis = baris.filter(function (b) { return b.tingkat === "KRITIS"; }).length;
  var hampir = baris.filter(function (b) { return b.status === "HAMPIR_HABIS"; }).length;
  var habis = baris.filter(function (b) { return b.status === "HABIS"; }).length;
  var dibawah = baris.filter(function (b) { return b.selisihTotal > 0; }).length;

  document.getElementById("angka").innerHTML = [
    ['SKU bermasalah', String(kritis + hampir + habis), kritis + " kritis · " + (hampir + habis) + " masalah stok"],
    ['Di bawah HPP', String(dibawah), "dari " + baris.length + " baris SKU"],
    ['Total kerugian', rupiahRingkas(eksposur), "kerugian saja, laba tidak mengurangi"],
    ['Sisa anggaran', rupiahRingkas(aman), angkaID(aman / KONFIG.anggaranKampanye * 100, 1) + "% · " + stAnggaran]
  ].map(function (r) {
    return '<div><dt>' + r[0] + '</dt><dd class="' + (r[0] === 'Sisa anggaran' ? LABEL_ANGGARAN[stAnggaran] : (r[0] === 'Total kerugian' || r[0] === 'Di bawah HPP' ? 'merah' : '')) +
      '">' + r[1] + '</dd><dd class="senyap" style="font-weight:400;font-size:11.5px;margin-top:2px">' + r[2] + '</dd></div>';
  }).join("");

  // --- sumber data
  var pesan = [];
  berkas.forEach(function (b) {
    pesan.push(b.nama + " → " + (b.marketplace || "?") +
      (b.ok ? " (" + angkaID(b.baris) + " baris terbaca)" : " — gagal: " + b.pesan));
  });
  if (bukanPenjualan.length) {
    pesan.push(bukanPenjualan.length + " SKU tidak ada di tabel HPP, diabaikan: " +
      bukanPenjualan.slice(0, 3).join(", "));
  }
  var teksSumber = pesan.join(" · ");
  document.getElementById("ringkasSumber").textContent =
    sumber + (teksSumber ? " · " + teksSumber : "");

  // --- saran alokasi
  var saran = saranAlokasi(baris);
  var elAlokasi = document.getElementById("alokasi");
  if (!saran.length) {
    elAlokasi.innerHTML = '<div class="kosong">Tidak ada marketplace yang perlu dipindahkan stoknya.<br>' +
      '<span class="senyap">Data pada contoh ini bergerak sangat lambat, sehingga hampir semua SKU masih punya cadangan panjang.</span></div>';
  } else {
    elAlokasi.innerHTML = '<table><thead><tr>' +
      '<th>Produk</th><th>Pindahkan</th><th>Alasan</th></tr></thead><tbody>' +
      saran.map(function (s) {
        var aksi = s.terhalang
          ? tagMarket(s.ke) + ' <span class="senyap">butuh stok</span> ' + tag("tidak ada pemasok", "kuning")
          : tag(angkaID(s.unit) + " unit", "gelap") + " " + tagMarket(s.dari) +
            ' <span class="senyap">→</span> ' + tagMarket(s.ke);
        return "<tr><td><span class='nama'>" + s.nama + "</span><span class='kode'>" + s.sku + "</span></td>" +
          "<td>" + aksi + "</td><td class='senyap'>" + s.alasan + "</td></tr>";
      }).join("") + "</tbody></table>";
  }

  // --- daftar tindakan
  var peringkatStok = { HABIS: 3, HAMPIR_HABIS: 2, AMAN: 1, TIDAK_TERJUAL: 0 };
  var peringkatTingkat = { KRITIS: 3, BERISIKO: 2, PANTAU: 1, PROFIT: 0 };
  var bertindak = baris.filter(function (b) {
    return b.status === "HABIS" || b.status === "HAMPIR_HABIS" ||
           b.tingkat === "KRITIS" || b.tingkat === "BERISIKO" || b.tingkat === "PANTAU";
  }).sort(function (a, b) {
    return (peringkatTingkat[b.tingkat] * 2 + peringkatStok[b.status]) -
           (peringkatTingkat[a.tingkat] * 2 + peringkatStok[a.status]);
  });

  document.getElementById("daftarSumber").textContent =
    bertindak.length + " baris perlu tindakan, diurutkan dari risiko terbesar.";

  var elDaftar = document.getElementById("daftar");
  if (!bertindak.length) {
    elDaftar.innerHTML = '<div class="kosong">Tidak ada SKU yang perlu tindakan.</div>';
    return;
  }

  elDaftar.innerHTML = "<table><thead><tr>" +
    "<th>Produk</th><th>Marketplace</th><th>Stok</th><th>Margin</th>" +
    "<th class='num'>Tayang</th><th class='num'>Terjual 7h</th><th class='num'>Cadangan</th>" +
    "<th class='num'>Rugi/unit</th><th class='num'>Total rugi</th><th class='num'>Harga saran</th>" +
    "</tr></thead><tbody>" +
    bertindak.map(function (b) {
      var st = LABEL_STOK[b.status], mg = LABEL_TINGKAT[b.tingkat];
      var naik = b.selisihUnit > 0 && b.hargaUnit > 0
        ? angkaID((b.hargaSaran / b.hargaUnit - 1) * 100, 0) + "% lebih tinggi" : "";
      return "<tr>" +
        "<td><span class='nama'>" + b.nama + "</span><span class='kode'>" + b.sku + "</span></td>" +
        "<td>" + tagMarket(b.market) + "</td>" +
        "<td>" + tag(st[0], st[1]) + "</td>" +
        "<td>" + tag(mg[0], mg[1]) + "</td>" +
        "<td class='num'>" + angkaID(b.dialokasikan) + "</td>" +
        "<td class='num'>" + (b.terjual7 > 0 ? angkaID(b.terjual7) : "—") + "</td>" +
        "<td class='num'>" + fmtHari(b.sisaHari) + "</td>" +
        "<td class='num " + (b.selisihUnit > 0 ? "merah" : "") + "'>" +
          (b.selisihUnit > 0 ? rupiah(b.selisihUnit) : "—") + "</td>" +
        "<td class='num " + (b.selisihTotal > 0 ? "merah" : "") + "'>" +
          (b.selisihTotal > 0 ? rupiah(b.selisihTotal) : "—") + "</td>" +
        "<td class='num'>" + (b.selisihUnit > 0 && b.hargaSaran > 0
          ? rupiah(b.hargaSaran) + "<span class='kode'>" + naik + "</span>" : "—") + "</td>" +
        "</tr>";
    }).join("") + "</tbody></table>";
}

/* ============================================================================
   Alur unggah
   ============================================================================ */
var DATA_CONTOH = JSON.parse(document.getElementById("data-contoh").textContent);
var TABEL_HPP = JSON.parse(document.getElementById("tabel-hpp").textContent);
// Nama barang tersedia untuk seluruh katalog, jadi SKU yang baru diunggah tetap
// punya nama yang bisa dibaca, bukan hanya kodenya.
var NAMA_BARANG = DATA_CONTOH.nama || {};
DATA_CONTOH.baris.forEach(function (b) { NAMA_BARANG[b.s] = b.n; });

// Tanggal dasar = tanggal data contoh, agar jendela 7 hari berarti sama
// baik untuk contoh maupun file yang diunggah.
var BATAS_DASAR = new Date(DATA_CONTOH.perTanggal + "T23:59:59+07:00");

/** Ubah data contoh menjadi baris siap tampil — tanpa pembacaan CSV. */
// Data contoh berasal dari analysis.json yang memakai label Inggris; label di
// halaman ini memakai istilah Indonesia.
var STATUS_ID = {
  OUT_OF_STOCK: "HABIS",
  AT_RISK: "HAMPIR_HABIS",
  HEALTHY: "AMAN",
  DORMANT: "TIDAK_TERJUAL"
};
var TINGKAT_ID = {
  CRITICAL: "KRITIS",
  AT_RISK: "BERISIKO",
  WATCH: "PANTAU",
  OK: "PROFIT"
};

function barisContoh() {
  return DATA_CONTOH.baris.map(function (b) {
    return {
      sku: b.s, nama: b.n, market: b.c, dialokasikan: b.a,
      terjual7: b.u7, terjual30: b.u7, terjualPeriode: b.u7,
      hpp: b.k, hargaUnit: b.p, diterima: b.r,
      laju: b.cd === null || b.a === 0 ? 0 : b.a / (b.cd * 24),
      jam: b.cd === null ? null : b.cd * 24,
      sisaHari: b.cd,
      status: STATUS_ID[b.st] || b.st,
      selisihUnit: b.lu, selisihTotal: b.lt,
      tingkat: TINGKAT_ID[b.sev] || b.sev,
      hargaSaran: b.tp
    };
  });
}

function tampilkanContoh() {
  document.getElementById("status").innerHTML =
    "Belum ada file. Menampilkan <b>contoh data</b> dari hasil generate — " +
    angkaID(DATA_CONTOH.baris.length) + " baris.";
  document.getElementById("reset").style.display = "none";
  gambar(TABEL_HPP, NAMA_BARANG, barisContoh(), "Contoh data", [], []);
  document.getElementById("hasil").classList.remove("sembunyi");
}

function bacaBerkas(file) {
  return new Promise(function (selesai) {
    var r = new FileReader();
    r.onload = function () {
      var teks = String(r.result);
      var barisMentah = bacaCSV(teks);
      var kepala = barisMentah.length ? Object.keys(barisMentah[0]) : [];
      var jenisEkspor = kenaliEkspor(kepala);
      var market = jenisEkspor.marketplace;

      if (!market) {
        return selesai({ nama: file.name, terbaca: false, pesan: "kolom tidak dikenali" });
      }

      var isInventori = jenisEkspor.jenis === "inventori";

      var baris = barisMentah.map(function (r) {
        if (isInventori) {
          // Shopee memakai "Parent SKU" + "Stock"/"Reserved Stock";
          // TikTok memakai "Seller SKU" + "Available Inventory".
          var sku = r["Parent SKU"] || r["Seller SKU"] || "";
          var tersedia = r["Available Inventory"] !== undefined
            ? parseInt(r["Available Inventory"], 10) || 0
            : (parseInt(r["Stock"], 10) || 0) - (parseInt(r["Reserved Stock"], 10) || 0);
          return { jenis: "inventori", sellerSku: sku, tersedia: tersedia };
        }

        var sku2 = r["SKU Reference No."] || r["Seller SKU"] || "";
        var unit = parseInt(r["Quantity"], 10) || 0;
        var kembali = parseInt(r["Returned Quantity"], 10) || 0;
        var harga, nilaiPerUnit;

        if (market === "Shopee") {
          // Deal Price = harga setelah diskon penjual, belum diskon platform.
          harga = parseInt(r["Deal Price"], 10) || 0;
          var diskonPlatform = parseInt(r["Shopee Discount"], 10) || 0;
          nilaiPerUnit = harga - (unit ? diskonPlatform / unit : 0);
        } else {
          harga = parseInt(r["Sku Unit Original Price"], 10) || 0;
          var dp = parseInt(r["Sku Platform Discount"], 10) || 0;
          var ds = parseInt(r["Sku Seller Discount"], 10) || 0;
          nilaiPerUnit = harga - (unit ? (dp + ds) / unit : 0);
        }

        return {
          jenis: "penjualan", sellerSku: sku2, status: r["Order Status"] || "",
          unit: Math.max(0, unit - kembali), harga: harga, nilaiPerUnit: nilaiPerUnit,
          waktu: ambilTanggal(r["Create Time"] || r["Created Time"] || "")
        };
      });

      selesai({ nama: file.name, marketplace: market, terbaca: true, baris: baris });
    };
    r.onerror = function () {
      selesai({ nama: file.name, terbaca: false, pesan: "gagal membaca file" });
    };
    r.readAsText(file, "utf-8");
  });
}

function proses(files) {
  if (!files || !files.length) return;
  var daftar = Array.prototype.slice.call(files);

  Promise.all(daftar.map(bacaBerkas)).then(function (hasil) {
    var rangkuman = rangkumEkspor(hasil, TABEL_HPP);
    var baris = hitungBaris(rangkuman, TABEL_HPP, NAMA_BARANG);

    if (!baris.length) {
      document.getElementById("status").innerHTML =
        "<b>Tidak ada baris yang bisa dianalisis.</b> Pastikan file adalah ekspor pesanan " +
        "atau inventori dari Shopee / TikTok Shop. " +
        hasil.filter(function (b) { return !b.terbaca; })
             .map(function (b) { return b.nama + ": " + b.pesan; }).join(" · ");
      document.getElementById("hasil").classList.add("sembunyi");
      return;
    }

    var gagal = hasil.filter(function (b) { return !b.terbaca; });
    document.getElementById("status").innerHTML =
      angkaID(daftar.length - gagal.length) + " dari " + angkaID(daftar.length) +
      " file terbaca → <b>" + angkaID(baris.length) + " baris SKU</b> dianalisis." +
      (gagal.length ? " <span class='merah'>Gagal: " +
        gagal.map(function (b) { return b.nama + " (" + b.pesan + ")"; }).join(", ") + "</span>" : "");
    document.getElementById("reset").style.display = "inline-block";

    gambar(TABEL_HPP, NAMA_BARANG, baris, "Hasil unggahan", rangkuman.berkas,
           Object.keys(rangkuman.bukanPenjualan));
    document.getElementById("hasil").classList.remove("sembunyi");
  });
}

/* ------------------------------------------------------------------ pengikatan */
var drop = document.getElementById("drop");
var input = document.getElementById("file");

drop.addEventListener("click", function () { input.click(); });
drop.addEventListener("keydown", function (e) {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
});
input.addEventListener("change", function () { proses(input.files); input.value = ""; });

["dragenter", "dragover"].forEach(function (n) {
  drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.add("aktif"); });
});
["dragleave", "drop"].forEach(function (n) {
  drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.remove("aktif"); });
});
drop.addEventListener("drop", function (e) {
  if (e.dataTransfer && e.dataTransfer.files) proses(e.dataTransfer.files);
});

document.getElementById("reset").addEventListener("click", function () {
  tampilkanContoh();
  document.getElementById("status").innerHTML =
    "Kembali ke <b>contoh data</b>. Silakan unggah file untuk menggantinya.";
});

// Tampilkan contoh data sejak awal, supaya halaman tidak kosong saat dibuka.
tampilkanContoh();
</script>