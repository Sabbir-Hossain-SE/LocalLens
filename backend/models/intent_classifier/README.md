# Intent Classifier (DistilBERT)

Fine-tuned single-task DistilBERT that predicts the **category** of a user's
search query (one of ~10 OSM-compatible tags). Inference is ~50–100 ms on
CPU vs. ~1–13 s for an LLM round-trip — when confidence ≥ 0.7 we use this
instead of calling the LLM (see [`intent_parser.py`](../../app/modules/intent_parser.py)).

Location-type and filter detection are handled by lightweight regex/keyword
rules in the same module, not by this model — a multi-head BERT for what is
fundamentally string-matching would be overkill at this dataset size.

## Build & train

```bash
# 1. Generate the labeled dataset (~500 queries via template augmentation)
python -m backend.scripts.build_intent_dataset

# 2. Fine-tune DistilBERT (CPU ~5 min on 500 examples)
python -m backend.scripts.train_intent_classifier
```

The training script writes `model.safetensors`, `tokenizer.json`,
`config.json`, and `label_map.json` into this directory. Once those files
exist, `IntentParser` will pick the classifier up on next startup.

## Dataset format

`dataset.jsonl` — one JSON object per line:

```json
{"query": "best 3 ramen near me", "category": "restaurant", "location_type": "near_me", "filters": []}
{"query": "highly rated dentist in 94110", "category": "dentist", "location_type": "zip", "filters": ["highly_rated"]}
```

## Skip / disable

The classifier is **optional**. If `model.safetensors` is absent the
parser logs `intent_classifier_unavailable` once at startup and falls back
to the LLM. To force LLM-only, delete this directory.
