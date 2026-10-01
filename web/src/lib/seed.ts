import seedJson from "../../public/seed.json";
import type { Seed } from "./upload";

/**
 * The bundled "current data" seed, emitted by `python src/build_analysis.py`.
 *
 * It carries only the catalogue cost/name, the per-channel allocation and the
 * tunables — enough for the Upload page to price and rank a freshly uploaded file
 * without shipping the full `analysis.json` (~165 KB) to the client.
 */
export const seed = seedJson as unknown as Seed;