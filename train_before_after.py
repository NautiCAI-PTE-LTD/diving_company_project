"""Train a new (better) Before / After classifier on the labelled folders.

Why this exists
---------------
The shipped ``Models/Before_and_after.h5`` (MobileNetV2 + light head) is
~50% accurate on the PDF-extracted images (see ``evaluate_before_after.py``).
This script builds a stronger classifier from the same data:

  * Backbone : **EfficientNetV2-B0** (Keras Applications)
  * Head     : GAP -> Dropout -> Dense(128, swish) -> Dropout -> Dense(1, sigmoid)
  * Two-stage : (1) frozen backbone, train head; (2) unfreeze top of backbone, fine-tune
  * Heavy augmentation, class weights, stratified 70/15/15 split
  * Dedup across the four candidate folders by SHA-1

Inputs (auto-discovered, missing folders are skipped):
  Report_to_extract_images/extracted/before
  Report_to_extract_images/extracted/after
  Rerun model/Before
  Rerun model/After

Outputs (under project root):
  Models/Before_and_after_v2.keras      -- best model (full architecture+weights)
  Models/Before_and_after_v2.metrics.json
  Models/Before_and_after_v2.history.csv
  eval_v2_predictions.csv               -- test-set predictions
  eval_v2_mismatches.csv                -- test-set mistakes only

Run:
    python train_before_after.py
    python train_before_after.py --epochs1 5 --epochs2 10        # quick run
    python train_before_after.py --img-size 240 --batch 16
    python train_before_after.py --no-finetune                   # stage 1 only

The new model is *self-contained* (architecture + weights stored together in
the ``.keras`` file). To use it from Python you just do:
    model = tf.keras.models.load_model("Models/Before_and_after_v2.keras")
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

# Quiet TF and force CPU-friendly defaults BEFORE importing tensorflow.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import numpy as np
from PIL import Image, UnidentifiedImageError
import tensorflow as tf
from tensorflow.keras import layers, Model, callbacks
from tensorflow.keras.applications import EfficientNetV2B0
# NOTE: in current Keras, efficientnet_v2.preprocess_input is a no-op
# placeholder. We let the model do its own [-1, 1] normalization via
# `include_preprocessing=True` and feed it raw [0, 255] images.

ROOT = Path(__file__).resolve().parent
MODELS_DIR = ROOT / "Models"
MODELS_DIR.mkdir(exist_ok=True)

CANDIDATE_DIRS = {
    "before": [
        ROOT / "Report_to_extract_images" / "extracted" / "before",
        ROOT / "Rerun model" / "Before",
    ],
    "after":  [
        ROOT / "Report_to_extract_images" / "extracted" / "after",
        ROOT / "Rerun model" / "After",
    ],
}
DEFAULT_OVERWATER_DIR = Path(r"F:\ship_image")
LABEL_NAMES = {0: "before", 1: "after", 2: "not_hull"}
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SEED = 42


# ----------------------------------------------------------- data discovery ----
def discover_images(
    *,
    overwater_dir: Path | None = None,
    three_class: bool = False,
) -> list[tuple[Path, int]]:
    """Return list of (path, label): 0=before, 1=after, 2=not_hull (overwater)."""
    label_to_id = {"before": 0, "after": 1, "not_hull": 2}
    by_sha: dict[str, tuple[Path, str]] = {}
    conflicts: set[str] = set()

    for label, dirs in CANDIDATE_DIRS.items():
        for d in dirs:
            if not d.exists():
                print(f"  (skip missing) {d}")
                continue
            for p in sorted(d.iterdir()):
                if not p.is_file() or p.suffix.lower() not in IMG_EXTS:
                    continue
                try:
                    sha = hashlib.sha1(p.read_bytes()).hexdigest()
                except OSError:
                    continue
                if sha in by_sha:
                    if by_sha[sha][1] != label:
                        conflicts.add(sha)
                    continue
                by_sha[sha] = (p, label)

    items = [(path, label_to_id[lab]) for sha, (path, lab) in by_sha.items()
             if sha not in conflicts]
    if conflicts:
        print(f"  dropped {len(conflicts)} images that appeared in BOTH before/after")

    if three_class and overwater_dir and overwater_dir.is_dir():
        hull_shas = set(by_sha.keys())
        added = 0
        for p in sorted(overwater_dir.iterdir()):
            if not p.is_file() or p.suffix.lower() not in IMG_EXTS:
                continue
            try:
                sha = hashlib.sha1(p.read_bytes()).hexdigest()
            except OSError:
                continue
            if sha in hull_shas or sha in conflicts:
                continue
            items.append((p, 2))
            added += 1
        print(f"  added {added} not_hull images from {overwater_dir}")
    return items


def stratified_split(items: list[tuple[Path, int]],
                     val_frac=0.15, test_frac=0.15, seed=SEED):
    rng = random.Random(seed)
    labels = sorted({y for _, y in items})
    by_label: dict[int, list[tuple[Path, int]]] = {y: [] for y in labels}
    for p, y in items:
        by_label[y].append((p, y))
    train, val, test = [], [], []
    for y, lst in by_label.items():
        rng.shuffle(lst)
        n = len(lst)
        n_test = int(round(n * test_frac))
        n_val  = int(round(n * val_frac))
        test  += lst[:n_test]
        val   += lst[n_test:n_test+n_val]
        train += lst[n_test+n_val:]
    rng.shuffle(train); rng.shuffle(val); rng.shuffle(test)
    return train, val, test


# ----------------------------------------------------------- tf.data pipeline ----
def _decode_image(path: tf.Tensor, label: tf.Tensor, img_size: int):
    raw = tf.io.read_file(path)
    img = tf.io.decode_image(raw, channels=3, expand_animations=False)
    img.set_shape([None, None, 3])
    img = tf.image.resize(img, [img_size, img_size], method="bilinear")
    img = tf.cast(img, tf.float32)            # raw [0, 255]; model does its own norm
    return img, label


def _augment(img: tf.Tensor, label: tf.Tensor):
    img = tf.image.random_flip_left_right(img)
    img = tf.image.random_brightness(img, max_delta=0.10 * 255.0)
    img = tf.image.random_contrast(img, 0.85, 1.15)
    img = tf.clip_by_value(img, 0.0, 255.0)
    return img, label


def make_dataset(items, img_size: int, batch: int,
                 shuffle: bool, augment: bool) -> tf.data.Dataset:
    paths  = [str(p) for p, _ in items]
    labels = [int(y) for _, y in items]
    ds = tf.data.Dataset.from_tensor_slices((paths, labels))
    if shuffle:
        ds = ds.shuffle(len(paths), seed=SEED, reshuffle_each_iteration=True)
    ds = ds.map(lambda p, y: _decode_image(p, y, img_size),
                num_parallel_calls=tf.data.AUTOTUNE)
    if augment:
        ds = ds.map(_augment, num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.batch(batch).prefetch(tf.data.AUTOTUNE)
    return ds


# ----------------------------------------------------------- model ----
def build_model(img_size: int, dropout=0.30, *, num_classes: int = 2) -> Model:
    backbone = EfficientNetV2B0(include_top=False, include_preprocessing=True,
                                weights="imagenet", pooling=None,
                                input_shape=(img_size, img_size, 3))
    backbone.trainable = False
    inputs = tf.keras.Input(shape=(img_size, img_size, 3), name="input_image")
    x = backbone(inputs, training=False)
    x = layers.GlobalAveragePooling2D(name="gap")(x)
    x = layers.Dropout(dropout, name="dropout_1")(x)
    x = layers.Dense(128, activation="swish",
                     kernel_regularizer=tf.keras.regularizers.l2(1e-4),
                     name="head_dense")(x)
    x = layers.Dropout(dropout, name="dropout_2")(x)
    if num_classes <= 2:
        outputs = layers.Dense(1, activation="sigmoid", name="head_out")(x)
        name = "before_after_v2"
    else:
        outputs = layers.Dense(num_classes, activation="softmax", name="head_out")(x)
        name = "before_after_v3"
    return Model(inputs, outputs, name=name)


def unfreeze_top(model: Model, fraction: float = 0.30) -> int:
    """Unfreeze the top fraction of layers in the backbone (closest to the head)."""
    # The backbone is the only nested Model in our architecture; find it by
    # type rather than by name so we don't depend on Keras's auto name.
    backbone: Model | None = None
    for layer in model.layers:
        if isinstance(layer, Model):
            backbone = layer
            break
    if backbone is None:
        raise RuntimeError("Could not locate backbone sub-model in the network")
    backbone.trainable = True
    layers_ = backbone.layers
    cutoff = int(len(layers_) * (1.0 - fraction))
    n_unfrozen = 0
    for i, layer in enumerate(layers_):
        # BN layers are kept frozen (training=False) for stability
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False
            continue
        layer.trainable = i >= cutoff
        if layer.trainable:
            n_unfrozen += 1
    return n_unfrozen


# ----------------------------------------------------------- helpers ----
def class_weights_for(items) -> dict[int, float]:
    counts = Counter(y for _, y in items)
    total = sum(counts.values())
    n_cls = max(len(counts), 1)
    return {y: total / (n_cls * counts[y]) for y in counts}


def confusion_matrix(y_true, y_pred):
    cm = {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 0}
    for t, p in zip(y_true, y_pred):
        cm[(int(t), int(p))] += 1
    return cm


def fmt_pct(num, den): return f"{(100.0*num/den):5.1f}%" if den else "  n/a"


def evaluate_split_multiclass(model: Model, items, img_size: int, batch: int,
                              name="test") -> dict:
    ds_eval = make_dataset(items, img_size, batch, shuffle=False, augment=False)
    probs = model.predict(ds_eval, verbose=0)
    if probs.ndim == 1:
        probs = probs.reshape(-1, 1)
    preds = np.argmax(probs, axis=1).astype("int32")
    truth = np.array([y for _, y in items], dtype="int32")
    acc = float((preds == truth).mean()) if len(items) else 0.0
    labels = sorted(set(truth.tolist()) | set(preds.tolist()))

    print(f"\n  ===== {name.upper()} SET (n={len(items)}) — 3-class =====")
    hdr = "gt\\pred   " + "".join(f"{LABEL_NAMES.get(i, i):>10}" for i in labels)
    print(hdr)
    cm: dict[tuple[int, int], int] = {}
    for t, p in zip(truth, preds):
        cm[(int(t), int(p))] = cm.get((int(t), int(p)), 0) + 1
    for t in labels:
        row = f"  {LABEL_NAMES.get(t, t):>9}"
        for p in labels:
            row += f"{cm.get((t, p), 0):10d}"
        print(row)
    print(f"     accuracy        : {acc*100:5.1f}%")
    per_class = {}
    for c in labels:
        mask = truth == c
        if mask.any():
            per_class[LABEL_NAMES.get(c, str(c))] = float((preds[mask] == c).mean())
    print(f"     per-class recall  : {per_class}")
    return {
        "n": len(items), "accuracy": acc, "per_class_recall": per_class,
        "confusion": {f"{LABEL_NAMES.get(t, t)}->{LABEL_NAMES.get(p, p)}": v
                      for (t, p), v in cm.items()},
        "predictions": list(zip(
            [str(p) for p, _ in items], truth.tolist(), preds.tolist(),
            [probs[i].astype(float).tolist() for i in range(len(items))],
        )),
    }


def evaluate_split(model: Model, items, img_size: int, batch: int,
                   threshold=0.5, name="test") -> dict:
    ds_eval = make_dataset(items, img_size, batch, shuffle=False, augment=False)
    probs = model.predict(ds_eval, verbose=0).reshape(-1)
    preds = (probs >= threshold).astype("int32")
    truth = np.array([y for _, y in items], dtype="int32")
    cm = confusion_matrix(truth, preds)
    tp_b, fp_b = cm[(0, 0)], cm[(1, 0)]
    fn_b = cm[(0, 1)]
    tp_a, fp_a = cm[(1, 1)], cm[(0, 1)]
    fn_a = cm[(1, 0)]
    prec_b = tp_b / max(tp_b + fp_b, 1)
    rec_b  = tp_b / max(tp_b + fn_b, 1)
    prec_a = tp_a / max(tp_a + fp_a, 1)
    rec_a  = tp_a / max(tp_a + fn_a, 1)
    acc    = (cm[(0, 0)] + cm[(1, 1)]) / max(len(items), 1)

    print(f"\n  ===== {name.upper()} SET (n={len(items)}) =====")
    print(f"                      pred=before   pred=after")
    print(f"     gt=before   {cm[(0,0)]:8d}    {cm[(0,1)]:8d}")
    print(f"     gt=after    {cm[(1,0)]:8d}    {cm[(1,1)]:8d}")
    print(f"     accuracy        : {fmt_pct(cm[(0,0)]+cm[(1,1)], len(items))}")
    print(f"     precision before={prec_b*100:5.1f}%  recall before={rec_b*100:5.1f}%")
    print(f"     precision after ={prec_a*100:5.1f}%  recall after ={rec_a*100:5.1f}%")
    return {
        "n": len(items), "accuracy": acc,
        "precision_before": prec_b, "recall_before": rec_b,
        "precision_after": prec_a,  "recall_after": rec_a,
        "confusion": {f"{t}->{p}": v for (t, p), v in cm.items()},
        "predictions": list(zip([str(p) for p, _ in items],
                                truth.tolist(),
                                preds.tolist(),
                                probs.astype(float).tolist())),
    }


# ----------------------------------------------------------- main ----
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--img-size", type=int, default=224)
    ap.add_argument("--batch",    type=int, default=16)
    ap.add_argument("--epochs1",  type=int, default=10,
                    help="Stage 1 epochs (frozen backbone)")
    ap.add_argument("--epochs2",  type=int, default=20,
                    help="Stage 2 epochs (fine-tune)")
    ap.add_argument("--lr1",      type=float, default=1e-3)
    ap.add_argument("--lr2",      type=float, default=1e-5)
    ap.add_argument("--no-finetune", action="store_true",
                    help="Skip stage 2, save only the head-trained model")
    ap.add_argument("--unfreeze-frac", type=float, default=0.30)
    ap.add_argument("--three-class", action="store_true",
                    help="Add not_hull class from overwater ship photos")
    ap.add_argument("--overwater-dir", type=Path, default=DEFAULT_OVERWATER_DIR,
                    help="Whole-ship / overwater negatives (label not_hull)")
    args = ap.parse_args()

    tf.keras.utils.set_random_seed(SEED)

    print("== train_before_after ==")
    print(f"   tf={tf.__version__}   img_size={args.img_size}   batch={args.batch}")
    gpus = tf.config.list_physical_devices("GPU")
    print(f"   GPUs visible to TF: {[g.name for g in gpus] or 'none (CPU)'}")

    three_class = args.three_class
    print("\nDiscovering images...")
    items = discover_images(overwater_dir=args.overwater_dir, three_class=three_class)
    counts = Counter(y for _, y in items)
    count_str = "   ".join(f"{LABEL_NAMES.get(k, k)}={counts[k]}" for k in sorted(counts))
    print(f"   total kept: {len(items)}   {count_str}")
    if min(counts.values()) < 20:
        print("WARNING: very few images per class — accuracy will be unstable.")

    train, val, test = stratified_split(items)
    print(f"   split: train={len(train)}  val={len(val)}  test={len(test)}")

    cw = class_weights_for(train)
    print(f"   class weights (train): {cw}")

    train_ds = make_dataset(train, args.img_size, args.batch, shuffle=True,  augment=True)
    val_ds   = make_dataset(val,   args.img_size, args.batch, shuffle=False, augment=False)

    num_classes = 3 if three_class else 2
    print(f"\nBuilding model (EfficientNetV2-B0, {num_classes} classes, backbone frozen)...")
    model = build_model(args.img_size, num_classes=num_classes)
    n_total = sum(int(np.prod(w.shape)) for w in model.weights)
    n_train = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
    print(f"   params: total={n_total:,}   trainable={n_train:,}")

    out_path = MODELS_DIR / ("Before_and_after_v3.keras" if three_class
                             else "Before_and_after_v2.keras")
    loss = "sparse_categorical_crossentropy" if three_class else "binary_crossentropy"
    metrics = ["accuracy"]
    if not three_class:
        metrics.extend([
            tf.keras.metrics.AUC(name="auc"),
            tf.keras.metrics.Precision(name="precision"),
            tf.keras.metrics.Recall(name="recall"),
        ])
    cb_list = [
        callbacks.ModelCheckpoint(str(out_path), monitor="val_loss",
                                  save_best_only=True, mode="min", verbose=0),
        callbacks.EarlyStopping(monitor="val_loss", patience=5,
                                restore_best_weights=True, mode="min", verbose=0),
        callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.3,
                                    patience=3, min_lr=1e-7, verbose=0),
    ]

    # ---- Stage 1: head only ----
    print(f"\nStage 1: train head only ({args.epochs1} epochs, lr={args.lr1})")
    model.compile(optimizer=tf.keras.optimizers.Adam(args.lr1), loss=loss, metrics=metrics)
    t0 = time.perf_counter()
    h1 = model.fit(train_ds, validation_data=val_ds,
                   epochs=args.epochs1, class_weight=cw,
                   callbacks=cb_list, verbose=2)
    t1 = time.perf_counter() - t0
    print(f"   stage 1 done in {t1/60:.1f} min")

    history = {k: list(map(float, v)) for k, v in h1.history.items()}

    # ---- Stage 2: fine-tune ----
    if not args.no_finetune and args.epochs2 > 0:
        n_unfrozen = unfreeze_top(model, args.unfreeze_frac)
        n_train2 = sum(int(np.prod(w.shape)) for w in model.trainable_weights)
        print(f"\nStage 2: fine-tune top {args.unfreeze_frac*100:.0f}% of backbone "
              f"({n_unfrozen} layers unfrozen, trainable params={n_train2:,})")
        model.compile(optimizer=tf.keras.optimizers.Adam(args.lr2), loss=loss, metrics=metrics)
        t0 = time.perf_counter()
        h2 = model.fit(train_ds, validation_data=val_ds,
                       epochs=args.epochs2, class_weight=cw,
                       callbacks=cb_list, verbose=2)
        t2 = time.perf_counter() - t0
        print(f"   stage 2 done in {t2/60:.1f} min")
        for k, v in h2.history.items():
            history.setdefault(k, []).extend(map(float, v))

    # Reload best (callbacks already restore_best_weights, but the .keras
    # file on disk corresponds to the best val_loss across both stages).
    print(f"\nReloading best snapshot from {out_path.name}")
    model = tf.keras.models.load_model(out_path)

    if three_class:
        val_metrics  = evaluate_split_multiclass(model, val,  args.img_size, args.batch, name="val")
        test_metrics = evaluate_split_multiclass(model, test, args.img_size, args.batch, name="test")
    else:
        val_metrics  = evaluate_split(model, val,  args.img_size, args.batch, name="val")
        test_metrics = evaluate_split(model, test, args.img_size, args.batch, name="test")

    tag = "v3" if three_class else "v2"
    metrics_path = MODELS_DIR / f"Before_and_after_{tag}.metrics.json"
    history_path = MODELS_DIR / f"Before_and_after_{tag}.history.csv"
    pred_path    = ROOT / f"eval_{tag}_predictions.csv"
    miss_path    = ROOT / f"eval_{tag}_mismatches.csv"

    data_summary = {"total": len(items), "train": len(train), "val": len(val), "test": len(test)}
    for k in sorted(counts):
        data_summary[LABEL_NAMES.get(k, str(k))] = counts[k]

    summary = {
        "num_classes": num_classes,
        "class_names": [LABEL_NAMES[i] for i in range(num_classes)],
        "data": data_summary,
        "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "val":  {k: v for k, v in val_metrics.items()  if k != "predictions"},
        "test": {k: v for k, v in test_metrics.items() if k != "predictions"},
        "model_path": str(out_path),
    }
    metrics_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if history:
        keys = list(history.keys())
        n_epochs = max(len(v) for v in history.values())
        with history_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["epoch"] + keys)
            for i in range(n_epochs):
                row = [i + 1] + [history[k][i] if i < len(history[k]) else ""
                                 for k in keys]
                w.writerow(row)

    label_name = LABEL_NAMES
    rows_all = []
    for row in test_metrics["predictions"]:
        p, t, pp, pr = row[0], row[1], row[2], row[3]
        entry = {"path": p, "gt": label_name[t], "pred": label_name[pp], "correct": int(t == pp)}
        if isinstance(pr, list):
            for i, prob in enumerate(pr):
                entry[f"prob_{label_name.get(i, i)}"] = round(float(prob), 4)
        else:
            entry["probability_after"] = round(float(pr), 4)
        rows_all.append(entry)
    with pred_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_all[0].keys()))
        w.writeheader(); w.writerows(rows_all)
    miss_rows = [r for r in rows_all if r["correct"] == 0]
    with miss_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_all[0].keys()))
        w.writeheader(); w.writerows(miss_rows)

    print("\nSaved:")
    print(f"   {out_path}        -- best model")
    print(f"   {metrics_path}    -- metrics summary")
    print(f"   {history_path}    -- training history")
    print(f"   {pred_path.name}  -- test-set predictions")
    print(f"   {miss_path.name}  -- test-set mistakes ({len(miss_rows)})")
    print(f"\nTEST ACCURACY = {test_metrics['accuracy']*100:.2f}%   "
          f"(n={test_metrics['n']})")

    if three_class and out_path.is_file():
        prod = MODELS_DIR / "Before_and_after_v2.keras"
        import shutil
        shutil.copy2(out_path, prod)
        summary["production_copy"] = str(prod)
        metrics_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"   Copied best model -> {prod} (production path)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
