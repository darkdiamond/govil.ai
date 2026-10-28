# Evaluating candidate models

Before changing the production model (`OPENROUTER_MODEL`), run the
candidate through the local harness against a few representative
datasets and compare its output side-by-side with the current model
and the live site. This documents that workflow.

Comparison snapshots live in `services/page_builder/harness-comparison/`,
which is **local-only and gitignored** — agent output embeds raw dataset
content (including personal contact details from registry datasets), so
snapshots must never be committed. What's versioned is this method, not
the artifacts.

## Picking datasets

Choose 3–5 datasets that stress different page shapes:

- a mid-sized **timeseries** (body density + chart quality),
- a large **map** dataset (GovMap/Leaflet + categorical charts),
- a thin **registry** (restraint test — a good model does _not_ pad),
- a wide dataset with many plausible charts (depth + prioritization).

Include at least one dataset the production model already published so
you can diff against a known-good page.

## Running a candidate

```sh
source .venv/bin/activate
export OPENROUTER_API_KEY=...

# 1. run the model through production's session path, inside the production
#    image under Podman (any OpenRouter <vendor>/<model> id)
infra/benchmark.sh --source <dataset_id> --model <model>

# 2. render the offline preview
python -m services.page_builder.cli.preview render <dataset_id>

# 3. archive the artifacts into a local, model-specific snapshot dir
mkdir -p services/page_builder/harness-comparison/<dataset_id>/<model>/
cp tmp/model_test/<dataset_id>/{content.html,agent_data.json,cost.json,transcript.json,preview.html} \
   services/page_builder/harness-comparison/<dataset_id>/<model>/

# 4. snapshot the live page for the same dataset, for a prod baseline
mkdir -p services/page_builder/harness-comparison/<dataset_id>/prod/
for f in content.html agent_data.json data.json; do
  curl -fsSL https://govil.ai/datasets/<dataset_id>/$f \
       -o services/page_builder/harness-comparison/<dataset_id>/prod/$f
done
```

Keep a small `README.md` table inside each dataset's snapshot folder
(model, date, cost, attempt count, notable failures) — future you will
be comparing these months later.

## What to check

- **Numeric provenance** — validate every chart's numbers against the
  CKAN datastore. Models have fabricated plausible-looking chart data;
  the system prompt's CHART-DATA PROVENANCE rule exists because of it.
- **Self-check** — `agent/skills/check.py` must exit 0 on the output.
- **Cost + reliability** — `cost.json` per page, and how many
  `SESSION_ATTEMPTS` retries the run needed (API flake rate matters as
  much as output quality for a daily unattended batch).
- **Restraint on thin datasets** — padding a 9-row registry with filler
  charts is a failure mode, not thoroughness.

## Tool-surface caveat

The harness tool surface (bash + code_execution + web_fetch +
web_search) is **narrower** than platforms with first-class file tools
(`read`, `write`, `edit`, `glob`, `grep`). For "model A vs model B" on
the same harness that's fine; when comparing against output produced on
a different platform, also run the current model through this harness
so the platform delta is isolated from the model delta.
