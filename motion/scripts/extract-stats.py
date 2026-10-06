"""Extract real figures from the LIVE site manifest -> motion/data/stats.json.
Default source is https://govil.ai/data/manifest.json (what visitors actually see);
pass --local to use frontend/public/data/manifest.json instead.
Re-run to refresh every video's numbers:  python3 motion/scripts/extract-stats.py"""
import json, collections, pathlib, sys, urllib.request
root = pathlib.Path(__file__).resolve().parents[2]
LIVE = "https://govil.ai/data/manifest.json"
if "--local" in sys.argv:
    source = "local"; m = json.load(open(root / "frontend/public/data/manifest.json"))
else:
    source = LIVE; m = json.load(urllib.request.urlopen(urllib.request.Request(LIVE, headers={"User-Agent": "govil-motion"}), timeout=60))
D = [d for d in m["datasets"] if d.get("source_status") != "unavailable"]
org = collections.Counter(d["organization"] for d in D)
kind = collections.Counter(d.get("dataset_kind") for d in D)
fmt = collections.Counter(f for d in D for f in (d.get("formats") or []))
tags = collections.Counter(t for d in D for t in (d.get("tags_he") or []))
def pick(orgname, n=8):
    xs = sorted([d for d in D if d["organization"] == orgname], key=lambda d: -(d.get("record_count") or 0))
    seen, out = set(), []
    for d in xs:  # dedupe near-identical series titles
        k = d["title"][:22]
        if k in seen: continue
        seen.add(k); out.append({"title": d["title"], "records": d.get("record_count") or 0, "kind": d.get("dataset_kind"), "slug": d.get("page_slug") or d.get("slug")})
    return out[:n]
def total(orgname): return sum(d.get("record_count") or 0 for d in D if d["organization"] == orgname)
def kinds(orgname): return dict(collections.Counter(d.get("dataset_kind") for d in D if d["organization"] == orgname))
orgs = ["משרד התחבורה והבטיחות בדרכים","משרד המשפטים","עיריית באר שבע","הרשות הממשלתית למים ולביוב","משרד הרווחה והביטחון החברתי","משרד הבריאות","המשרד להגנת הסביבה","משרד החקלאות וביטחון המזון"]
out = {
  "source": source, "generated_at": m["generated_at"], "datasets": len(D),
  "records": sum(d.get("record_count") or 0 for d in D),
  "organizations": len(org), "top_orgs": org.most_common(10),
  "kinds": dict(kind), "formats": fmt.most_common(6), "top_tags": tags.most_common(20),
  "related_links": sum(len(d.get("related_ids") or []) for d in D),
  "sector_top": {o: {"datasets": org[o], "records": total(o), "kinds": kinds(o), "top": pick(o)} for o in orgs},
}
out["summaries"] = [{"title": d["title"], "summary": d["summary_he"]} for d in sorted(D, key=lambda d: len(d.get("summary_he") or "")) if d.get("summary_he") and 80 < len(d["summary_he"]) < 200 and d.get("dataset_kind") == "timeseries"][:6]
(root / "motion/data/stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps({k: out[k] for k in ["datasets","records","organizations","kinds","formats","related_links"]}, ensure_ascii=False))
for o in orgs: print(o, org[o], [t["title"] for t in out["sector_top"][o]["top"][:3]])
