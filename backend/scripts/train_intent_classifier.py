"""
Fine-tune DistilBERT for category classification (PDF §7.1).

Training is single-task: predicts one of the ~10 OSM category labels from a
free-text user query. Location-type and filter heads are handled by light
regex rules at inference time (see ``intent_parser._regex_fallback``) — a
multi-head DistilBERT for everything is overkill at this dataset size.

Run:
    python -m backend.scripts.build_intent_dataset      # build dataset.jsonl
    python -m backend.scripts.train_intent_classifier   # train & save model

Output:  backend/models/intent_classifier/{model.safetensors, label_map.json, ...}
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "models" / "intent_classifier" / "dataset.jsonl"
MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "intent_classifier"


def main() -> None:
    try:
        import torch  # noqa: F401
        from datasets import Dataset  # type: ignore
        from transformers import (  # type: ignore
            AutoTokenizer,
            AutoModelForSequenceClassification,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        print(f"Missing deps: {exc}")
        print("Install training extras: pip install datasets accelerate")
        return

    if not DATA_PATH.exists():
        print(f"Dataset not found at {DATA_PATH}. Run build_intent_dataset.py first.")
        return

    # Load
    rows = [json.loads(line) for line in DATA_PATH.read_text().splitlines() if line.strip()]
    labels = sorted({r["category"] for r in rows})
    label2id = {l: i for i, l in enumerate(labels)}
    id2label = {i: l for l, i in label2id.items()}

    ds = Dataset.from_list(
        [{"text": r["query"], "label": label2id[r["category"]]} for r in rows]
    )
    splits = ds.train_test_split(test_size=0.15, seed=42)

    model_name = "distilbert-base-uncased"
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    def tok(batch: dict) -> dict:
        return tokenizer(batch["text"], truncation=True, padding="max_length", max_length=64)

    tokenized = splits.map(tok, batched=True)

    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=len(labels),
        id2label=id2label,
        label2id=label2id,
    )

    args = TrainingArguments(
        output_dir=str(MODEL_DIR / "checkpoints"),
        num_train_epochs=4,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=32,
        evaluation_strategy="epoch",
        save_strategy="no",
        learning_rate=3e-5,
        weight_decay=0.01,
        logging_steps=50,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["test"],
        tokenizer=tokenizer,
    )
    trainer.train()
    metrics = trainer.evaluate()
    print(f"Eval loss: {metrics.get('eval_loss'):.4f}")

    # Save model + tokenizer
    model.save_pretrained(MODEL_DIR)
    tokenizer.save_pretrained(MODEL_DIR)
    (MODEL_DIR / "label_map.json").write_text(json.dumps({"id2label": id2label}, indent=2))
    print(f"Model saved → {MODEL_DIR}")


if __name__ == "__main__":
    main()
