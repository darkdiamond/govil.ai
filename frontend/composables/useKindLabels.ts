import type { DatasetKind } from "~/types/manifest";

// Hebrew labels + blurbs for the 5 dataset_kind values. Kept in one place so
// pages/kinds/[kind].vue and pages/kinds/index.vue stay in sync.

export interface KindInfo {
  label: string;
  blurb: string;
  icon: string; // path under /public/icons/
}

export const KIND_INFO: Record<DatasetKind, KindInfo> = {
  map: {
    label: "גיאוגרפי",
    blurb: "מפות ונקודות ציון",
    icon: "/icons/map-pin.svg",
  },
  timeseries: {
    label: "סדרת זמן",
    blurb: "מדידות לאורך זמן",
    icon: "/icons/database.svg",
  },
  registry: {
    label: "רשימת ישויות",
    blurb: "רשימות וכתובות",
    icon: "/icons/list.svg",
  },
  rankings: {
    label: "דירוגים",
    blurb: "דירוגים ומדדים",
    icon: "/icons/circle-check.svg",
  },
  misc: { label: "אחר", blurb: "מאגרים נוספים", icon: "/icons/info.svg" },
};

export const KIND_ORDER: DatasetKind[] = [
  "map",
  "timeseries",
  "registry",
  "rankings",
  "misc",
];

export function useKindLabels() {
  return { KIND_INFO, KIND_ORDER };
}
