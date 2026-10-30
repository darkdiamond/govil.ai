// Maps CKAN `license_title` values seen on data.gov.il to canonical URLs.
// Keys are matched exact-first, then trimmed + lowercased. Unknown values
// still emit a valid Schema.org CreativeWork from buildLicenseLd (name only),
// which clears Google's "Invalid object type for license" warning even when
// we don't recognise the string.

export interface LicenseLd {
  "@type": "CreativeWork";
  name: string;
  url?: string;
}

const LICENSE_URLS: Record<string, string> = {
  "אחר (פתוח)": "https://data.gov.il/about/terms",
  "other (open)": "https://data.gov.il/about/terms",
  "creative commons attribution":
    "https://creativecommons.org/licenses/by/4.0/",
  "creative commons attribution-sharealike":
    "https://creativecommons.org/licenses/by-sa/4.0/",
  ייחוס: "https://creativecommons.org/licenses/by/4.0/",
  "ייחוס-שיתוף זהה": "https://creativecommons.org/licenses/by-sa/4.0/",
  "נחלת הכלל": "https://creativecommons.org/publicdomain/zero/1.0/",
  "cc-by": "https://creativecommons.org/licenses/by/4.0/",
  "cc-by-sa": "https://creativecommons.org/licenses/by-sa/4.0/",
  "cc-zero": "https://creativecommons.org/publicdomain/zero/1.0/",
};

const DEFAULT_LICENSE: LicenseLd = {
  "@type": "CreativeWork",
  name: "תנאי שימוש — data.gov.il",
  url: "https://data.gov.il/about/terms",
};

// `termsUrl`: a non-CKAN source's own terms page (SourceInfo.terms_url),
// used when the license name isn't one we know.
export function buildLicenseLd(
  raw?: string | null,
  termsUrl?: string
): LicenseLd {
  const name = (raw ?? "").trim();
  if (!name) {
    return termsUrl
      ? { "@type": "CreativeWork", name: "תנאי שימוש", url: termsUrl }
      : DEFAULT_LICENSE;
  }
  const key = name.toLowerCase();
  const url = LICENSE_URLS[name] ?? LICENSE_URLS[key] ?? termsUrl;
  return url
    ? { "@type": "CreativeWork", name, url }
    : { "@type": "CreativeWork", name };
}
