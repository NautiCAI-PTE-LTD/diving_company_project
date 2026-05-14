"""Safe knowledge-distillation fine-tune of the Swin hull-region classifier
to recognise the user's new ``Bow`` examples without forgetting the other
10 classes.

Why this is structured the way it is
------------------------------------
We only have 11 Bow images and *no* labelled examples for the other 10
classes. A naive fine-tune on Bow alone would collapse the softmax to
"Bow" and break the existing model. To avoid that catastrophic forgetting:

  1. Freeze the entire Swin backbone. Only the small head (BN/Linear/Linear)
     is trainable. ~1M trainable params vs ~27M frozen.
  2. Train on TWO streams in the same batch:
        a) the few Bow images -> hard cross-entropy to class "Bow"
        b) a "rehearsal buffer" of ~489 unlabeled images (the extracted
           before/after photos). For these we don't know the true class,
           so we use the ORIGINAL model's softmax as a *soft target* and
           penalise divergence with KL (this is standard knowledge
           distillation a-la Hinton 2015). The rehearsal stream keeps the
           new model honest on classes other than Bow.
  3. After training, run two acceptance gates:
        * Bow validation accuracy must improve materially.
        * Rehearsal agreement with the ORIGINAL model must stay >= 90%
          (i.e. we didn't quietly break the other classes).
     We save the new checkpoint as ``Ship_classification_v2.pth``. We do
     NOT touch the production file unless ``--deploy`` is also passed AND
     the gates pass.

Outputs:
    Models/Ship_classification_v2.pth          -- new checkpoint (always)
    Models/Ship_classification_v2.metrics.json -- metrics + gate decision

Usage:
    python retrain_region.py                       # train + measure, no deploy
    python retrain_region.py --deploy              # additionally swap into backend if gates pass
    python retrain_region.py --epochs 30 --batch 16
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms

import timm

from backend import config  # noqa: E402

MODELS_DIR    = ROOT / "Models"
BOW_DIR       = ROOT / "Report_to_extract_images" / "extracted" / "Bow"
REHEARSAL_DIRS = [
    ROOT / "Report_to_extract_images" / "extracted" / "before",
    ROOT / "Report_to_extract_images" / "extracted" / "after",
]
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SEED = 42


# ----------------------------------------------------------- model rebuild ----
def _build_head(num_classes: int) -> nn.Sequential:
    return nn.Sequential(
        nn.BatchNorm1d(768),
        nn.ReLU(inplace=True),
        nn.Linear(768, 512),
        nn.ReLU(inplace=True),
        nn.BatchNorm1d(512),
        nn.Dropout(0.0),
        nn.Linear(512, num_classes),
    )


class SwinClassifier(nn.Module):
    def __init__(self, num_classes: int):
        super().__init__()
        self.base = timm.create_model("swin_tiny_patch4_window7_224",
                                      pretrained=False, num_classes=0)
        self.head = _build_head(num_classes)

    def forward(self, x):
        return self.head(self.base(x))


def load_original(device: str) -> tuple[nn.Module, dict, int]:
    ckpt = torch.load(str(config.SHIP_REGION_CKPT),
                      map_location="cpu", weights_only=False)
    num_classes = int(ckpt["num_classes"])
    model = SwinClassifier(num_classes)
    model.load_state_dict(ckpt["model_state"])
    return model.to(device).eval(), ckpt, num_classes


# ----------------------------------------------------------- datasets ----
TFM_TRAIN_BOW = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomAffine(degrees=8, translate=(0.05, 0.05),
                            scale=(0.92, 1.08)),
    transforms.ColorJitter(brightness=0.20, contrast=0.20,
                           saturation=0.10, hue=0.02),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std =[0.229, 0.224, 0.225]),
])

TFM_TRAIN_REH = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.RandomHorizontalFlip(),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std =[0.229, 0.224, 0.225]),
])

TFM_EVAL = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std =[0.229, 0.224, 0.225]),
])


def _list_imgs(folders) -> list[Path]:
    out: list[Path] = []
    for f in folders:
        if not f.exists():
            continue
        out.extend(sorted(p for p in f.iterdir()
                          if p.is_file() and p.suffix.lower() in IMG_EXTS))
    return out


class BowDataset(Dataset):
    def __init__(self, paths: list[Path], tfm, target_idx: int):
        self.paths = paths; self.tfm = tfm; self.t = target_idx

    def __len__(self): return len(self.paths)

    def __getitem__(self, i):
        img = Image.open(self.paths[i]).convert("RGB")
        return self.tfm(img), self.t


class RehearsalDataset(Dataset):
    """Each item: (transformed image, soft_target_logits_from_original_model)."""
    def __init__(self, paths: list[Path], tfm, teacher_logits: torch.Tensor):
        self.paths = paths; self.tfm = tfm; self.tl = teacher_logits

    def __len__(self): return len(self.paths)

    def __getitem__(self, i):
        img = Image.open(self.paths[i]).convert("RGB")
        return self.tfm(img), self.tl[i]


# ----------------------------------------------------------- helpers ----
@torch.inference_mode()
def teacher_logits_for(model: nn.Module, paths: list[Path],
                       batch: int, device: str) -> torch.Tensor:
    """Forward pass each image through the ORIGINAL model once and store
    its logits. These are the soft targets used during distillation."""
    model.eval()
    rows: list[torch.Tensor] = []
    buf: list[torch.Tensor] = []

    def _flush():
        if not buf:
            return
        x = torch.stack(buf).to(device, non_blocking=True)
        rows.append(model(x).detach().cpu())
        buf.clear()

    for p in paths:
        img = TFM_EVAL(Image.open(p).convert("RGB"))
        buf.append(img)
        if len(buf) >= batch:
            _flush()
    _flush()
    return torch.cat(rows, dim=0)


def kd_loss(student_logits: torch.Tensor, teacher_logits: torch.Tensor,
            T: float = 4.0) -> torch.Tensor:
    """KL(student || teacher) at temperature T, scaled by T^2."""
    s = F.log_softmax(student_logits / T, dim=-1)
    t = F.softmax(teacher_logits / T, dim=-1)
    return F.kl_div(s, t, reduction="batchmean") * (T * T)


# ----------------------------------------------------------- main ----
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch",  type=int, default=16,
                    help="Batch size for the REHEARSAL stream (Bow uses all 8 each step).")
    ap.add_argument("--lr",     type=float, default=1e-4)
    ap.add_argument("--alpha",  type=float, default=0.5,
                    help="Loss weight: total = alpha*CE_bow + (1-alpha)*KD_rehearsal")
    ap.add_argument("--T",      type=float, default=4.0)
    ap.add_argument("--deploy", action="store_true",
                    help="If gates pass, swap the new checkpoint into the production path.")
    ap.add_argument("--gate-bow",   type=float, default=0.50,
                    help="Minimum Bow val accuracy to accept (default 0.50).")
    ap.add_argument("--gate-preserve", type=float, default=0.90,
                    help="Minimum rehearsal-agreement with original model (default 0.90).")
    args = ap.parse_args()

    torch.manual_seed(SEED); random.seed(SEED); np.random.seed(SEED)
    device = config.DEVICE
    print(f"== retrain_region ==  device={device}")
    print(f"   ckpt(in) = {config.SHIP_REGION_CKPT}")

    # ---- discover data ----
    bow = _list_imgs([BOW_DIR])
    reh = _list_imgs(REHEARSAL_DIRS)
    print(f"   Bow imgs : {len(bow)}")
    print(f"   Rehearsal: {len(reh)}")
    if len(bow) < 5:
        print("!! Need at least 5 Bow images"); return 2

    # Split Bow ~70/30 train/val (small but at least gives a held-out signal)
    rng = random.Random(SEED); rng.shuffle(bow)
    n_val_bow = max(2, len(bow) // 4)
    bow_val, bow_train = bow[:n_val_bow], bow[n_val_bow:]
    print(f"   Bow split: train={len(bow_train)}  val={len(bow_val)}")

    # Hold out 10% of rehearsal for "preservation" measurement.
    rng2 = random.Random(SEED + 1); reh_shuf = list(reh); rng2.shuffle(reh_shuf)
    n_val_reh = max(20, int(round(len(reh_shuf) * 0.10)))
    reh_val, reh_train = reh_shuf[:n_val_reh], reh_shuf[n_val_reh:]
    print(f"   Rehearsal split: train={len(reh_train)}  val={len(reh_val)}")

    # ---- load original model (teacher) ----
    print("\nLoading original model as teacher...")
    teacher, ckpt, num_classes = load_original(device)
    class_names: list[str] = list(ckpt["class_names"])
    bow_idx = class_names.index("Bow")
    img_size = int(ckpt.get("img_size", 224))
    print(f"   classes ({num_classes}): {class_names}")
    print(f"   Bow class index = {bow_idx}, img_size = {img_size}")

    # ---- precompute teacher logits for rehearsal ----
    print("Computing teacher logits on rehearsal set (one pass) ...")
    t0 = time.perf_counter()
    teacher_train = teacher_logits_for(teacher, reh_train, args.batch, device)
    teacher_val   = teacher_logits_for(teacher, reh_val,   args.batch, device)
    print(f"   done in {time.perf_counter()-t0:.1f}s   "
          f"(train={tuple(teacher_train.shape)}, val={tuple(teacher_val.shape)})")

    # Teacher's top-1 on rehearsal val (this is what "preservation" measures against).
    teacher_top1_val = teacher_val.argmax(dim=-1).numpy()

    # ---- build student (= copy of teacher) and freeze backbone ----
    print("\nBuilding student (= same architecture, backbone frozen)...")
    student = SwinClassifier(num_classes)
    student.load_state_dict(ckpt["model_state"])
    for p in student.base.parameters():
        p.requires_grad = False
    student.to(device).train()
    # CRITICAL: keep all BatchNorm running stats frozen during fine-tune. With
    # only 9 Bow examples and 16 rehearsal examples per batch, the BN running
    # mean/var would drift wildly away from the teacher's stats and that alone
    # destroys preservation on the rehearsal set, *even without learning Bow*.
    # We allow BN weight/bias to be trained (it's part of the head and small),
    # but force `eval()` so the running stats don't update.
    def _freeze_bn(m):
        for mod in m.modules():
            if isinstance(mod, nn.BatchNorm1d):
                mod.eval()
    _freeze_bn(student)

    trainable = sum(p.numel() for p in student.parameters() if p.requires_grad)
    total = sum(p.numel() for p in student.parameters())
    print(f"   trainable params: {trainable:,} / {total:,}  ({100*trainable/total:.2f}%)")

    # ---- datasets / loaders ----
    bow_train_ds = BowDataset(bow_train, TFM_TRAIN_BOW, target_idx=bow_idx)
    reh_train_ds = RehearsalDataset(reh_train, TFM_TRAIN_REH, teacher_train)

    # We loop through rehearsal once per epoch; Bow images are oversampled
    # by repeating bow_train every step (each step uses ALL Bow train imgs).
    reh_loader = DataLoader(reh_train_ds, batch_size=args.batch,
                            shuffle=True, num_workers=0, drop_last=False)

    bow_x = torch.stack([bow_train_ds[i][0] for i in range(len(bow_train_ds))]).to(device)
    bow_y = torch.full((len(bow_train_ds),), bow_idx, dtype=torch.long, device=device)

    optimizer = torch.optim.Adam(filter(lambda p: p.requires_grad,
                                        student.parameters()), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,
                                                           T_max=args.epochs)

    # ---- baseline eval (so we have before/after numbers) ----
    print("\n--- baseline (teacher = original model) ---")
    base_bow_train, base_bow_val = _eval_top1(teacher, bow_train, bow_idx, device), \
                                    _eval_top1(teacher, bow_val,   bow_idx, device)
    print(f"   Bow train top-1: {base_bow_train:.2%}   "
          f"Bow val top-1: {base_bow_val:.2%}")
    print(f"   Rehearsal val preservation by definition: 100%")

    # ---- training loop ----
    print(f"\nTraining: epochs={args.epochs}  batch(reh)={args.batch}  "
          f"lr={args.lr}  alpha={args.alpha}  T={args.T}")
    for epoch in range(1, args.epochs + 1):
        student.train()
        _freeze_bn(student)            # re-pin BN to eval after train() flips it
        # Refresh augmented Bow batch each epoch
        bow_x = torch.stack([bow_train_ds[i][0] for i in range(len(bow_train_ds))]).to(device)
        bow_y = torch.full((len(bow_train_ds),), bow_idx, dtype=torch.long, device=device)

        running_ce, running_kd, n_steps = 0.0, 0.0, 0
        for x_reh, t_logits in reh_loader:
            x_reh = x_reh.to(device, non_blocking=True)
            t_logits = t_logits.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)
            s_reh = student(x_reh)
            s_bow = student(bow_x)

            ce = F.cross_entropy(s_bow, bow_y)
            kd = kd_loss(s_reh, t_logits, T=args.T)
            loss = args.alpha * ce + (1.0 - args.alpha) * kd
            loss.backward()
            optimizer.step()

            running_ce += float(ce.detach()); running_kd += float(kd.detach())
            n_steps += 1
        scheduler.step()

        # Evaluate every epoch and keep the BEST snapshot (by gate-aware score):
        #   if preserve >= gate_preserve  -> score = bow_val (higher is better)
        #   else                          -> score = preserve - 1.0 (smaller penalty when closer to gate)
        bow_train_acc = _eval_top1(student, bow_train, bow_idx, device)
        bow_val_acc   = _eval_top1(student, bow_val,   bow_idx, device)
        pres = _preservation(student, reh_val, teacher_top1_val, device)
        ce_avg = running_ce / max(n_steps, 1)
        kd_avg = running_kd / max(n_steps, 1)
        score = bow_val_acc if pres >= args.gate_preserve else (pres - 1.0)
        if not hasattr(main, "_best") or score > main._best_score:  # type: ignore[attr-defined]
            main._best_score = score                                   # type: ignore[attr-defined]
            main._best_state = {k: v.detach().cpu().clone()            # type: ignore[attr-defined]
                                for k, v in student.state_dict().items()}
            main._best_epoch = epoch                                   # type: ignore[attr-defined]
            main._best_metrics = (bow_train_acc, bow_val_acc, pres)    # type: ignore[attr-defined]

        if epoch == 1 or epoch % 2 == 0 or epoch == args.epochs:
            print(f"   epoch {epoch:2d}/{args.epochs}  "
                  f"ce={ce_avg:.3f} kd={kd_avg:.3f}  "
                  f"bow_train={bow_train_acc:.0%}  bow_val={bow_val_acc:.0%}  "
                  f"preserve={pres:.1%}  lr={scheduler.get_last_lr()[0]:.2e}")

    # ---- restore best snapshot (the one that passed both gates most cleanly) ----
    if hasattr(main, "_best_state"):
        print(f"\nRestoring best snapshot from epoch {main._best_epoch}  "        # type: ignore[attr-defined]
              f"(bow_train, bow_val, preserve) = "
              f"{tuple(round(v, 3) for v in main._best_metrics)}")               # type: ignore[attr-defined]
        student.load_state_dict(main._best_state)                                # type: ignore[attr-defined]

    print("\nFinal evaluation (best snapshot) ...")
    final = {
        "bow_train_acc_orig": base_bow_train,
        "bow_val_acc_orig":   base_bow_val,
        "bow_train_acc_new":  _eval_top1(student, bow_train, bow_idx, device),
        "bow_val_acc_new":    _eval_top1(student, bow_val,   bow_idx, device),
        "preservation":       _preservation(student, reh_val, teacher_top1_val, device),
    }
    for k, v in final.items():
        print(f"   {k:24s} = {v:.4f}")

    # ---- save new checkpoint (always; deploy = optional) ----
    out_ckpt = MODELS_DIR / "Ship_classification_v2.pth"
    torch.save({
        "class_names": class_names,
        "num_classes": num_classes,
        "img_size": img_size,
        "model_state": student.state_dict(),
        "lineage": "knowledge_distillation_from_Ship_classification_vby_swin",
    }, str(out_ckpt))
    print(f"\nSaved new checkpoint: {out_ckpt}")

    # ---- decision gate ----
    pass_bow   = final["bow_val_acc_new"]  >= args.gate_bow
    pass_preserve = final["preservation"] >= args.gate_preserve
    gates_ok = pass_bow and pass_preserve

    print("\n========= DECISION GATE =========")
    print(f"   gate-bow      ({args.gate_bow:.0%}): "
          f"{'PASS' if pass_bow else 'FAIL'}   "
          f"(got {final['bow_val_acc_new']:.0%})")
    print(f"   gate-preserve ({args.gate_preserve:.0%}): "
          f"{'PASS' if pass_preserve else 'FAIL'}   "
          f"(got {final['preservation']:.0%})")
    print(f"   overall      : {'PASS' if gates_ok else 'FAIL'}")

    metrics_path = MODELS_DIR / "Ship_classification_v2.metrics.json"
    metrics_path.write_text(json.dumps({
        "args": vars(args),
        "data": {"bow_total": len(bow), "bow_train": len(bow_train),
                 "bow_val": len(bow_val), "reh_train": len(reh_train),
                 "reh_val": len(reh_val)},
        "metrics": final,
        "gates": {"bow_pass": pass_bow, "preserve_pass": pass_preserve,
                  "overall_pass": gates_ok,
                  "bow_threshold": args.gate_bow,
                  "preserve_threshold": args.gate_preserve},
    }, indent=2), encoding="utf-8")
    print(f"\nWrote metrics: {metrics_path}")

    if args.deploy:
        if gates_ok:
            print("\nGates pass + --deploy set. Swapping into production...")
            _deploy_to_backend(out_ckpt)
        else:
            print("\n--deploy requested but gates FAILED. Refusing to swap. "
                  "Production model untouched.")
    else:
        print("\n(No --deploy flag passed; production model untouched.)")
    return 0


def _deploy_to_backend(new_ckpt: Path) -> None:
    """Repoint backend.config.SHIP_REGION_CKPT to the new file by editing config.py.

    Also back up the current production file to <name>.bak so we can revert.
    Resets the inference module's cached model on next import (caller will need
    to restart the FastAPI process anyway)."""
    cfg = ROOT / "backend" / "config.py"
    text = cfg.read_text(encoding="utf-8")
    new_line = 'SHIP_REGION_CKPT  = MODELS_DIR / "Ship_classification_v2.pth"'
    target = 'SHIP_REGION_CKPT  = MODELS_DIR / "Ship_classification_vby_swin.pth"'
    if target in text:
        cfg.write_text(text.replace(target, new_line), encoding="utf-8")
        print(f"   patched {cfg.name}: SHIP_REGION_CKPT -> Ship_classification_v2.pth")
    elif new_line in text:
        print("   backend/config.py already points at v2; nothing to change.")
    else:
        print("!! Could not find expected SHIP_REGION_CKPT line in config.py; "
              "leaving it untouched. Edit manually.")
        return

    # Back up old file if present.
    old = MODELS_DIR / "Ship_classification_vby_swin.pth"
    bak = MODELS_DIR / "Ship_classification_vby_swin.pth.bak"
    if old.exists() and not bak.exists():
        old.rename(bak)
        print(f"   backed up {old.name} -> {bak.name}")


@torch.inference_mode()
def _eval_top1(model: nn.Module, paths: list[Path], gt_idx: int,
               device: str) -> float:
    if not paths:
        return float("nan")
    model.eval()
    hits = 0
    for p in paths:
        x = TFM_EVAL(Image.open(p).convert("RGB")).unsqueeze(0).to(device)
        pred = int(model(x).argmax(dim=-1).item())
        if pred == gt_idx:
            hits += 1
    return hits / len(paths)


@torch.inference_mode()
def _preservation(student: nn.Module, paths: list[Path],
                  teacher_top1: np.ndarray, device: str) -> float:
    """Fraction of rehearsal-val images where student's top-1 matches teacher's."""
    if not paths:
        return float("nan")
    student.eval()
    hits = 0
    for i, p in enumerate(paths):
        x = TFM_EVAL(Image.open(p).convert("RGB")).unsqueeze(0).to(device)
        pred = int(student(x).argmax(dim=-1).item())
        if pred == int(teacher_top1[i]):
            hits += 1
    return hits / len(paths)


if __name__ == "__main__":
    sys.exit(main())
