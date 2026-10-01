"""Master product catalogue - the single source of truth for both marketplaces.

The catalogue is defined as plain tuples so it is easy to read and extend.
`build_products()` turns that into `Product` objects carrying deterministic,
marketplace-specific identifiers and prices.

Nothing here is random at import time; the caller passes in a seeded RNG so
that repeat runs produce identical identifiers.
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass, astuple
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# --------------------------------------------------------------------------- #
# Brand pools (fictional - deliberately avoids real trademarks)
# --------------------------------------------------------------------------- #
BRANDS_BY_CATEGORY: Dict[str, Tuple[str, ...]] = {
    "Minuman": ("Tirta Segar", "Sari Bumi", "Kelinci Putih"),
    "Makanan Instan": ("Prima Rasa", "Bintang Pagi", "Nusantara"),
    "Snack": ("Aroma Jaya", "Cahaya", "Prima Rasa"),
    "Bumbu & Rempah": ("Matahari", "Nusantara", "Aroma Jaya"),
    "Perawatan Tubuh": ("Cahaya", "Segar Alami", "Kelinci Putih"),
    "Perawatan Rumah": ("Segar Alami", "Cahaya", "Tirta Segar"),
    "Kopi & Teh": ("Bintang Pagi", "Matahari", "Aroma Jaya"),
}

# --------------------------------------------------------------------------- #
# The catalogue
# (name, category, variant, uom, base_price, popularity, weight_gr,
#  shelf_life_days, perishable)
# popularity is a 1-10 weight used when sampling order lines; staples score high.
# --------------------------------------------------------------------------- #
CATALOGUE: Tuple[Tuple, ...] = (
    # ---- Minuman (10) -----------------------------------------------------
    ("Air Mineral 600 ml", "Minuman", "600 ml", "pcs", 4_000, 10, 620, 365, False),
    ("Air Mineral 1500 ml", "Minuman", "1500 ml", "pcs", 6_500, 9, 1_550, 365, False),
    ("Teh Kotak Original 300 ml", "Minuman", "Original", "pcs", 5_500, 8, 330, 240, False),
    ("Jus Jeruk 1 L", "Minuman", "1 L", "pcs", 22_000, 5, 1_100, 180, False),
    ("Susu UHT Cokelat 1 L", "Minuman", "Cokelat", "pcs", 19_000, 8, 1_050, 270, False),
    ("Susu UHT Plain 1 L", "Minuman", "Plain", "pcs", 18_500, 7, 1_050, 270, False),
    ("Susu Kental Manis 370 gr", "Minuman", "370 gr", "pcs", 11_500, 7, 410, 365, False),
    ("Minuman Isotonik 500 ml", "Minuman", "500 ml", "pcs", 7_500, 5, 550, 240, False),
    ("Susu Kedelai 250 ml", "Minuman", "250 ml", "pcs", 6_000, 4, 280, 120, False),
    ("Susu Fermentasi 200 ml", "Minuman", "200 ml", "pcs", 8_500, 3, 230, 30, True),

    # ---- Makanan Instan (8) ----------------------------------------------
    ("Mie Instan Goreng 85 gr", "Makanan Instan", "Goreng", "pcs", 3_500, 10, 90, 300, False),
    ("Mie Instan Kuah Ayam 75 gr", "Makanan Instan", "Kuah Ayam", "pcs", 3_300, 9, 80, 300, False),
    ("Mie Instan Kuah Sapi 75 gr", "Makanan Instan", "Kuah Sapi", "pcs", 3_400, 8, 80, 300, False),
    ("Bubur Instan Ayam 40 gr", "Makanan Instan", "Ayam", "pcs", 4_500, 4, 50, 300, False),
    ("Sarden Kaleng 155 gr", "Makanan Instan", "155 gr", "pcs", 12_500, 7, 200, 730, False),
    ("Kornet Sapi Kaleng 198 gr", "Makanan Instan", "198 gr", "pcs", 21_000, 5, 250, 730, False),
    ("Nugget Ayam 500 gr", "Makanan Instan", "500 gr", "pack", 32_000, 6, 530, 180, True),
    ("Sosis Ayam 500 gr", "Makanan Instan", "500 gr", "pack", 28_000, 5, 510, 150, True),

    # ---- Snack (8) --------------------------------------------------------
    ("Keripik Kentang Original 68 gr", "Snack", "Original", "pcs", 11_000, 7, 80, 200, False),
    ("Biskuit Cokelat 300 gr", "Snack", "300 gr", "pcs", 15_000, 6, 320, 270, False),
    ("Wafer Cokelat 145 gr", "Snack", "145 gr", "pcs", 9_500, 6, 160, 270, False),
    ("Cokelat Batang 65 gr", "Snack", "65 gr", "pcs", 12_000, 5, 75, 300, False),
    ("Permen Mint 125 gr", "Snack", "125 gr", "pcs", 8_000, 4, 140, 365, False),
    ("Kacang Atom 200 gr", "Snack", "200 gr", "pcs", 13_000, 4, 210, 180, False),
    ("Kerupuk Udang 200 gr", "Snack", "200 gr", "pcs", 9_000, 5, 200, 180, False),
    ("Biskuit Marie 250 gr", "Snack", "250 gr", "pcs", 10_500, 5, 270, 270, False),

    # ---- Bumbu & Rempah (8) ----------------------------------------------
    ("Kecap Manis 520 ml", "Bumbu & Rempah", "520 ml", "pcs", 17_500, 9, 640, 540, False),
    ("Saus Sambal 335 ml", "Bumbu & Rempah", "335 ml", "pcs", 14_000, 8, 400, 540, False),
    ("Saus Tomat 335 ml", "Bumbu & Rempah", "335 ml", "pcs", 13_500, 7, 400, 540, False),
    ("Garam Beryodium 250 gr", "Bumbu & Rempah", "250 gr", "pcs", 3_500, 8, 260, 730, False),
    ("Gula Pasir 1 kg", "Bumbu & Rempah", "1 kg", "pack", 16_000, 9, 1_010, 730, False),
    ("Kaldu Ayam Blok 100 gr", "Bumbu & Rempah", "Ayam", "pcs", 7_500, 6, 120, 540, False),
    ("Merica Bubuk 30 gr", "Bumbu & Rempah", "30 gr", "pcs", 9_000, 3, 45, 540, False),
    ("Bawang Goreng 100 gr", "Bumbu & Rempah", "100 gr", "pcs", 15_000, 4, 115, 120, False),

    # ---- Perawatan Tubuh (6) ---------------------------------------------
    ("Sabun Cair 450 ml", "Perawatan Tubuh", "450 ml", "pcs", 28_000, 6, 490, 730, False),
    ("Shampoo Anti Ketombe 340 ml", "Perawatan Tubuh", "Anti Ketombe", "pcs", 42_000, 6, 400, 730, False),
    ("Pasta Gigi 190 gr", "Perawatan Tubuh", "190 gr", "pcs", 18_000, 7, 215, 730, False),
    ("Deodoran Roll On 50 ml", "Perawatan Tubuh", "50 ml", "pcs", 21_000, 4, 65, 730, False),
    ("Sabun Batang 85 gr", "Perawatan Tubuh", "85 gr", "pcs", 4_500, 7, 90, 730, False),
    ("Hand Sanitizer 100 ml", "Perawatan Tubuh", "100 ml", "pcs", 12_000, 4, 125, 730, False),

    # ---- Perawatan Rumah (6) ---------------------------------------------
    ("Deterjen Bubuk 800 gr", "Perawatan Rumah", "800 gr", "pack", 24_000, 8, 860, 730, False),
    ("Deterjen Cair 1 L", "Perawatan Rumah", "1 L", "pcs", 32_000, 7, 1_120, 730, False),
    ("Pembersih Lantai 800 ml", "Perawatan Rumah", "800 ml", "pcs", 18_500, 7, 910, 730, False),
    ("Sabun Cuci Piring 750 ml", "Perawatan Rumah", "750 ml", "pcs", 16_500, 8, 860, 730, False),
    ("Pemutih Pakaian 1 L", "Perawatan Rumah", "1 L", "pcs", 14_000, 5, 1_120, 365, False),
    ("Pelembut Pakaian 1 L", "Perawatan Rumah", "1 L", "pcs", 20_000, 6, 1_060, 730, False),

    # ---- Kopi & Teh (4) ---------------------------------------------------
    ("Kopi Bubuk 250 gr", "Kopi & Teh", "250 gr", "pack", 35_000, 6, 265, 365, False),
    ("Kopi Instan Sachet (10x)", "Kopi & Teh", "10 sachet", "pack", 18_000, 7, 140, 540, False),
    ("Teh Celup 25 Bags", "Kopi & Teh", "25 bags", "pack", 12_500, 6, 95, 540, False),
    ("Kopi Susu Sachet (10x)", "Kopi & Teh", "10 sachet", "pack", 22_000, 7, 210, 365, False),
)

assert len(CATALOGUE) == 50, f"expected 50 SKUs, found {len(CATALOGUE)}"


# --------------------------------------------------------------------------- #
# Product model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Product:
    sku_id: str
    seller_sku: str
    name: str
    brand: str
    category: str
    variant: str
    uom: str
    cost_price: int
    base_price: int
    weight_gr: int
    shelf_life_days: int
    perishable: bool
    popularity: int
    shopee_item_id: int
    shopee_model_id: int
    shopee_price: int
    tiktok_product_id: int
    tiktok_sku_id: int
    tiktok_price: int
    launch_date: str

    @property
    def display_name(self) -> str:
        """Product name as marketplaces render it: 'Name - Variant'."""
        return f"{self.name} - {self.variant}"


MASTER_COLUMNS = [
    "SKU ID",
    "Seller SKU",
    "Product Name",
    "Brand",
    "Category",
    "Variant",
    "UOM",
    "Cost Price",
    "Base Price",
    "Weight (gr)",
    "Shelf Life (days)",
    "Perishable",
    "Popularity Weight",
    "Shopee Item ID",
    "Shopee Model ID",
    "Shopee Price",
    "TikTok Product ID",
    "TikTok SKU ID",
    "TikTok Price",
    "Launch Date",
]


def _round_to(value: float, step: int) -> int:
    return int(round(value / step)) * step


def build_products(rng: random.Random) -> List[Product]:
    """Expand `CATALOGUE` into fully-identified `Product` records.

    All identifiers and prices are derived from `rng`, so a fixed seed always
    yields the same catalogue.
    """
    products: List[Product] = []

    for index, row in enumerate(CATALOGUE, start=1):
        (name, category, variant, uom, base_price,
         popularity, weight_gr, shelf_life_days, perishable) = row

        sku_id = f"SRC-{index:04d}"
        seller_sku = f"SS-{sku_id}"

        brands = BRANDS_BY_CATEGORY[category]
        brand = brands[(index - 1) % len(brands)]

        cost_price = _round_to(base_price * rng.uniform(0.62, 0.80), 50)
        shopee_price = _round_to(base_price * rng.uniform(0.95, 1.02), 100)
        tiktok_price = _round_to(base_price * rng.uniform(0.97, 1.05), 100)

        # Launch dates spread across the 18 months before the window.
        launch = date(2025, 1, 1) - timedelta(days=rng.randint(0, 540))

        products.append(
            Product(
                sku_id=sku_id,
                seller_sku=seller_sku,
                name=name,
                brand=brand,
                category=category,
                variant=variant,
                uom=uom,
                cost_price=cost_price,
                base_price=base_price,
                weight_gr=weight_gr,
                shelf_life_days=shelf_life_days,
                perishable=perishable,
                popularity=popularity,
                shopee_item_id=rng.randint(1_000_000_000, 9_999_999_999),
                shopee_model_id=rng.randint(1_000_000_000_000, 9_999_999_999_999),
                shopee_price=shopee_price,
                tiktok_product_id=rng.randint(1_000_000_000_000_000_000, 9_999_999_999_999_999_999),
                tiktok_sku_id=rng.randint(1_000_000_000_000_000_000, 9_999_999_999_999_999_999),
                tiktok_price=tiktok_price,
                launch_date=launch.isoformat(),
            )
        )

    return products


def write_master_csv(products: List[Product], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(MASTER_COLUMNS)
        for product in products:
            writer.writerow([
                product.sku_id,
                product.seller_sku,
                product.name,
                product.brand,
                product.category,
                product.variant,
                product.uom,
                product.cost_price,
                product.base_price,
                product.weight_gr,
                product.shelf_life_days,
                "TRUE" if product.perishable else "FALSE",
                product.popularity,
                product.shopee_item_id,
                product.shopee_model_id,
                product.shopee_price,
                product.tiktok_product_id,
                product.tiktok_sku_id,
                product.tiktok_price,
                product.launch_date,
            ])


def channel_price(product: Product, channel: str) -> int:
    """List price for a product on a given channel."""
    from config import SHOPEE
    return product.shopee_price if channel == SHOPEE else product.tiktok_price