"""News: data-driven articles (layer 6), run by its own job (`run.py`).

The deterministic half finds what moved in the data: `series` pulls time
series out of recipe page models (persisted by the builder under
models/<id>/ in the staging bucket), `signals` scores what is new and
unusual in them, `links` adds the cross-dataset context, `demand` weighs by
search interest (GSC). `run --signals-only` prints the ranked list and calls
no model. The model half (`editor`, `writer`, `gates`) turns the picked
signals into articles; `publish_news` writes them out for the site.
"""
