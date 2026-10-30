import type { DatasetKind, SlimEntry } from "~/types/manifest";

export interface InsightSlide {
  id: string;
  title: string;
  organization: string | null;
  dataset_kind: DatasetKind;
  kind_label_he: string;
  stat: { value: string; unit: string } | null;
  primary_tag: string | null;
  is_fresh: boolean;
  href: string;
}

const KIND_LABEL_HE: Record<DatasetKind, string> = {
  map: "מפה",
  timeseries: "סדרת זמן",
  registry: "מאגר",
  rankings: "דירוג",
  misc: "מאגר",
};

const KIND_UNIT_HE: Record<Exclude<DatasetKind, "misc">, string> = {
  map: "מקומות על המפה",
  timeseries: "נקודות נתונים",
  registry: "רשומות",
  rankings: "בדירוג",
};

const KIND_MIN_COUNT: Record<Exclude<DatasetKind, "misc">, number> = {
  map: 50,
  timeseries: 100,
  registry: 100,
  rankings: 10,
};

const FRESH_WINDOW_MS = 7 * 86_400_000;

function buildStat(e: SlimEntry): { value: string; unit: string } | null {
  const k = e.dataset_kind;
  if (!k || k === "misc") return null;
  const count = e.record_count;
  if (count == null) return null;
  return { value: count.toLocaleString("he-IL"), unit: KIND_UNIT_HE[k] };
}

function buildPrimaryTag(e: SlimEntry): string | null {
  // Canonical tags are already cleaned (no ministry names, most important first).
  return e.tags?.[0] ?? null;
}

function buildIsFresh(iso?: string | null): boolean {
  if (!iso) return false;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return false;
  return Date.now() - t < FRESH_WINDOW_MS;
}

export function buildInsightPool(entries: SlimEntry[]): InsightSlide[] {
  const pool: InsightSlide[] = [];
  for (const e of entries) {
    if (!e.summary_he || !e.dataset_kind || e.dataset_kind === "misc") continue;
    const k = e.dataset_kind;
    const count = e.record_count;
    const hasSpatial = !!e.spatial_coverage?.trim();

    const meetsCount = count != null && count >= KIND_MIN_COUNT[k];
    const meetsSpatial = k === "map" && hasSpatial;
    if (!meetsCount && !meetsSpatial) continue;

    pool.push({
      id: e.id,
      title: e.title,
      organization: e.organization ?? null,
      dataset_kind: k,
      kind_label_he: KIND_LABEL_HE[k],
      stat: buildStat(e),
      primary_tag: buildPrimaryTag(e),
      is_fresh: buildIsFresh(e.metadata_modified),
      href: `/datasets/${encodeURI(e.page_slug || e.id)}/`,
    });
  }
  return pool;
}

export function sampleInsights(
  pool: InsightSlide[],
  n: number
): InsightSlide[] {
  if (pool.length <= n) return [...pool];
  const arr = [...pool];
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr.slice(0, n);
}

export function chunkBy<T>(arr: T[], size: number): T[][] {
  if (size <= 0) return [arr];
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}
