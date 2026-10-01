"""Central configuration for the Shopee / TikTok Shop dummy-data generator.

Everything a reviewer might want to tweak lives here: the generation window,
volume, channel split, seasonality multipliers, status mixes, and the
reference lists (cities, couriers, payment methods, warehouses).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
MASTER_DIR = DATA_DIR / "master"
SHOPEE_DIR = DATA_DIR / "shopee"
TIKTOK_DIR = DATA_DIR / "tiktok"
INTERNAL_DIR = DATA_DIR / "internal"

# --------------------------------------------------------------------------- #
# Reproducibility
# --------------------------------------------------------------------------- #
RANDOM_SEED = 42

# --------------------------------------------------------------------------- #
# Generation window and volume
# --------------------------------------------------------------------------- #
START_DATE = date(2025, 7, 1)
END_DATE = date(2025, 9, 30)

NUM_ORDERS = 500
MAX_LINES_PER_ORDER = 3
LINE_COUNT_WEIGHTS = [0.62, 0.28, 0.10]  # probability of 1, 2, 3 line items

INVENTORY_LOOKBACK_DAYS = 30

CURRENCY = "IDR"
TIMEZONE_LABEL = "WIB (GMT+7)"

# --------------------------------------------------------------------------- #
# Channels
# --------------------------------------------------------------------------- #
SHOPEE = "Shopee"
TIKTOK = "TikTok Shop"

CHANNEL_SPLIT = {
    SHOPEE: 0.55,
    TIKTOK: 0.45,
}

# TikTok Shop is still growing, so its share ramps up over the window.
TIKTOK_GROWTH_RAMP = 0.35  # 0.0 = flat, 0.35 = ~35% relative uplift by the end

# --------------------------------------------------------------------------- #
# Seasonality
# --------------------------------------------------------------------------- #
WEEKEND_MULTIPLIER = {5: 1.25, 6: 1.15}  # Mon=0 ... Sat=5, Sun=6
PAYDAY_MULTIPLIER = 1.30                 # applies on day >= 25 or day <= 5
CAMPAIGN_DATES = {
    date(2025, 7, 7): 1.80,
    date(2025, 8, 8): 2.10,
    date(2025, 9, 9): 2.60,
}

# Relative likelihood of an order being placed in each hour (index 0 = 00:00).
HOUR_WEIGHTS = [
    1, 1, 1, 1, 1, 2, 3, 4, 5, 6, 6, 7,
    8, 7, 6, 6, 6, 7, 8, 10, 11, 10, 7, 4,
]

# --------------------------------------------------------------------------- #
# Internal COGS / costing policy
# --------------------------------------------------------------------------- #
# Stock kept on hand is proportional to what sells; lean SKUs hold less than a
# month of cover on purpose, so some months ship more than opening stock.
COSTING_METHOD = "Weighted Average"

# Fraction of SKUs whose unit cost changes during the window (supplier price
# movements). Enough to exercise a weighted-average roll, not enough to be noise.
COST_CHANGE_SHARE = 0.22
COST_CHANGE_RANGE = (0.92, 1.10)  # multiplier applied to the previous cost

# Lean SKUs carry low stock on purpose, so a month of shipped units can exceed
# opening stock. That forces backfill from the MID-MONTH cost roll instead of
# silently reporting a negative COGS.
LEAN_STOCK_SHARE = 0.15

# --------------------------------------------------------------------------- #
# Order status mixes (weights must sum to 1.0)
# --------------------------------------------------------------------------- #
SHOPEE_STATUS_MIX = {
    "Completed": 0.70,
    "Shipped": 0.10,
    "Ready to Ship": 0.08,
    "Cancelled": 0.08,
    "Returned/Refunded": 0.04,
}

TIKTOK_STATUS_MIX = {
    "Completed": 0.68,
    "In Transit": 0.11,
    "To Ship": 0.08,
    "Cancelled": 0.08,
    "Refund/Return": 0.05,
}

# Statuses that count as "sale realised" (used for Sales (30d)).
SOLD_STATUSES = {
    SHOPEE: {"Completed", "Shipped"},
    TIKTOK: {"Completed", "In Transit"},
}

# Statuses whose units are still sitting in the warehouse (used for Reserved).
RESERVED_STATUSES = {
    SHOPEE: {"Ready to Ship"},
    TIKTOK: {"To Ship"},
}

CANCELLED_STATUSES = {
    SHOPEE: {"Cancelled"},
    TIKTOK: {"Cancelled"},
}

RETURNED_STATUSES = {
    SHOPEE: {"Returned/Refunded"},
    TIKTOK: {"Refund/Return"},
}

# --------------------------------------------------------------------------- #
# Commercial parameters
# --------------------------------------------------------------------------- #
SELLER_DISCOUNT_RANGE = (0.00, 0.15)
PLATFORM_DISCOUNT_RANGE = (0.00, 0.20)
SHIPPING_FEE_RANGE = (0, 25_000)
FREE_SHIPPING_PROBABILITY = 0.40
QUANTITY_WEIGHTS = [0.52, 0.24, 0.13, 0.07, 0.04]  # qty 1..5

# --------------------------------------------------------------------------- #
# Reference lists
# --------------------------------------------------------------------------- #
SHOPEE_WAREHOUSES = [
    "Gudang Utama - Cikarang",
    "Gudang Surabaya",
]

TIKTOK_WAREHOUSES = [
    "Jabodetabek Warehouse",
    "Surabaya Warehouse",
    "Medan Warehouse",
]

SHOPEE_COURIERS = [
    "Shopee Xpress",
    "J&T Express",
    "SiCepat REG",
    "JNE Reguler",
    "AnterAja",
    "Ninja Xpress",
]

TIKTOK_COURIERS = [
    "TikTok Shop Logistics",
    "J&T Express",
    "SiCepat REG",
    "JNE Reguler",
    "Ninja Xpress",
    "AnterAja",
]

SHOPEE_PAYMENT_METHODS = [
    "ShopeePay",
    "SPayLater",
    "Transfer Bank (BCA)",
    "Transfer Bank (Mandiri)",
    "Transfer Bank (BRI)",
    "Kartu Kredit/Debit",
    "Indomaret",
    "Alfamart",
    "COD",
]

TIKTOK_PAYMENT_METHODS = [
    "TikTok Pay",
    "Transfer Bank (BCA)",
    "Transfer Bank (BNI)",
    "Kartu Kredit/Debit",
    "GoPay",
    "OVO",
    "DANA",
    "Alfamart",
    "COD",
]

# (city, province, postal-code prefix)
CITIES = [
    ("Jakarta Pusat", "DKI Jakarta", "10"),
    ("Jakarta Selatan", "DKI Jakarta", "12"),
    ("Jakarta Barat", "DKI Jakarta", "11"),
    ("Jakarta Timur", "DKI Jakarta", "13"),
    ("Bekasi", "Jawa Barat", "17"),
    ("Depok", "Jawa Barat", "16"),
    ("Tangerang", "Banten", "15"),
    ("Bogor", "Jawa Barat", "16"),
    ("Bandung", "Jawa Barat", "40"),
    ("Semarang", "Jawa Tengah", "50"),
    ("Yogyakarta", "DI Yogyakarta", "55"),
    ("Surabaya", "Jawa Timur", "60"),
    ("Malang", "Jawa Timur", "65"),
    ("Denpasar", "Bali", "80"),
    ("Medan", "Sumatera Utara", "20"),
    ("Palembang", "Sumatera Selatan", "30"),
    ("Pekanbaru", "Riau", "28"),
    ("Makassar", "Sulawesi Selatan", "90"),
    ("Balikpapan", "Kalimantan Timur", "76"),
    ("Pontianak", "Kalimantan Barat", "78"),
]

STREET_NAMES = [
    "Jl. Merdeka", "Jl. Sudirman", "Jl. Thamrin", "Jl. Gatot Subroto",
    "Jl. Ahmad Yani", "Jl. Diponegoro", "Jl. Cendrawasih", "Jl. Melati",
    "Jl. Kenanga", "Jl. Pahlawan", "Jl. Kartini", "Jl. Raya Bogor",
]

# Kelurahan / village names, used as the last part of a street address.
KELURAHAN_NAMES = [
    "Kel. Menteng", "Kel. Kebon Jeruk", "Kel. Cikini", "Kel. Sukamaju",
    "Kel. Tanah Abang", "Kel. Rawa Belong", "Kel. Jatiasih", "Kel. Cibubur",
    "Kel. Sukun", "Kel. Gubeng", "Kel. Wonokromo", "Kel. Kuta",
]

FIRST_NAMES = [
    "Andi", "Budi", "Citra", "Dewi", "Eko", "Fitri", "Gita", "Hendra",
    "Indah", "Joko", "Kartika", "Lestari", "Maya", "Nanda", "Oka", "Putri",
    "Rahmat", "Sari", "Tono", "Umi", "Vina", "Wahyu", "Yuni", "Zaki",
]

LAST_NAMES = [
    "Santoso", "Wijaya", "Pratama", "Hidayat", "Nugroho", "Setiawan",
    "Ramadhan", "Maulana", "Kusuma", "Halim", "Saputra", "Permata",
]

LAST_ORDER_NOTE_FRACTION = 0.18  # share of orders that carry a buyer note

BUYER_NOTES = [
    "Tolong dibungkus bubble wrap ya",
    "Kirim hari ini kalau bisa",
    "Titip di security",
    "Jangan pakai plastik, pakai kardus",
    "Sudah langganan, tolong bonus sachet",
    "Mohon dicek expired date-nya",
]

# Malformed-looking but plausible free text; useful for testing parsers.
CANCEL_REASONS = [
    "Pembeli mengajukan pembatalan",
    "Stok habis",
    "Alamat pengiriman tidak lengkap",
    "Pembeli tidak membayar dalam batas waktu",
    "Seller tidak dapat memenuhi pesanan",
]

RETURN_REASONS = [
    "Barang rusak saat diterima",
    "Barang tidak sesuai deskripsi",
    "Salah kirim varian",
    "Pembeli berubah pikiran",
    "Kemasan bocor",
]