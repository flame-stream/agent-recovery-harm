# human labels

* `human_blind_labels.csv` — the author's blind labels (harmful action, residual violation, kind) of
  60 random episodes on which both LLM annotators agreed (seed 20261115).
* `human_verification.csv` — the author's review of the harmful continuations (`author_verdict`
  agree / unsure, `author_kind`). It records the labels as they were at the time of the review
  (52 continuations); slots 60 and 126 were resolved from database facts afterwards (126 became
  harmless), so its `final_*` columns can differ from `final_labels.csv` (they do for slot 126, and
  for slot 196, whose residual violation is now undecidable).
* The author's free-text columns (`basis` in the blind labels, `comment` in the review) are not
  published.
* The labelling page (`human_labeling.html`) quotes task data and is only in the bundle
  (`protected/labels/human/`). It is built by `scripts/labels/build_human_tool.py` from
  `scripts/labels/human_tool_template.html`.
