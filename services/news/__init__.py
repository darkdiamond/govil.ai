"""News: data-driven articles (layer 6, planned).

This package is the deterministic half — find what moved in the data:
`series` pulls time series out of recipe page models (persisted by the
builder under models/<id>/ in the staging bucket), `signals` scores what is
new and unusual in them, `links` adds the cross-dataset context, `demand`
weighs by search interest (GSC). `run --signals-only` prints the ranked list.
No LLM here; the writer (a separate job) consumes these signals.
"""
