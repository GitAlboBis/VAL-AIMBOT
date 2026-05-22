"""Download and export the Valorant head-detection YOLO11 model.

Downloads ``jparedesDS/valorant-yolo11m`` from Hugging Face, exports the
``.pt`` weights to ONNX at the project's expected shape (416x416, FP16
NCHW for QNN HTP), drops the file in ``models/``, and prints the
``config.yaml`` + ``engines/ai_engine.py::CLASS_NAMES`` deltas the user
should apply.

The Hub repo is two-class (``Body``, ``Head``) so a head-only aimbot
sets ``target_classes: [1]``. The export is FP16 because that is what
the QNN provider's HTP backend natively consumes (see
``engines/qnn_provider.py::QNNProvider.load`` step 8b).

Run with::

    python tools\\download_valorant_model.py
    python tools\\download_valorant_model.py --imgsz 640        # higher resolution
    python tools\\download_valorant_model.py --repo jparedesDS/valorant-yolov10b
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"
DEFAULT_REPO = "jparedesDS/valorant-yolo11m"
DEFAULT_FILE = "yolo11m_vlr.pt"  # the .pt artifact in the HF repo
DEFAULT_IMGSZ = 416


# --------------------------------------------------------------------- #
# Dependency bootstrap (huggingface_hub + ultralytics)
# --------------------------------------------------------------------- #
def _pip_install(packages: List[str]) -> None:
    """Install ``packages`` via ``pip`` in the current interpreter."""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", *packages]
    print(f"  + {' '.join(cmd)}")
    subprocess.check_call(cmd)


def _ensure_dep(module: str, pip_name: Optional[str] = None) -> None:
    try:
        importlib.import_module(module)
        return
    except ImportError:
        pass
    print(f"[deps] {module} not found; installing...")
    _pip_install([pip_name or module])
    importlib.invalidate_caches()
    importlib.import_module(module)


def _ensure_deps() -> None:
    """Install ``huggingface_hub`` + ``ultralytics`` if missing.

    ``ultralytics`` pulls in ``torch`` etc. on first install — sizable
    download but a one-shot cost. The script runs offline thereafter.
    """
    print("[deps] checking dependencies...")
    _ensure_dep("huggingface_hub")
    _ensure_dep("ultralytics")
    _ensure_dep("onnx")


# --------------------------------------------------------------------- #
# Repo discovery + download
# --------------------------------------------------------------------- #
def _list_pt_files(repo_id: str) -> List[str]:
    """Return the names of all ``*.pt`` files in ``repo_id`` on the Hub."""
    from huggingface_hub import HfApi

    api = HfApi()
    files = api.list_repo_files(repo_id)
    return [f for f in files if f.endswith(".pt")]


def _download_pt(repo_id: str, filename: Optional[str] = None) -> Path:
    """Download a ``.pt`` weight file from ``repo_id`` and return its path.

    When ``filename`` is ``None``, picks the first ``.pt`` returned by
    the Hub. Cached under ``~/.cache/huggingface/`` so re-runs are
    instantaneous.
    """
    from huggingface_hub import hf_hub_download

    if filename is None:
        candidates = _list_pt_files(repo_id)
        if not candidates:
            raise RuntimeError(
                f"no '*.pt' files found in repo {repo_id!r}; "
                f"check the repo URL or pick another model"
            )
        # Prefer canonical names like "yolo11m_vlr.pt" / "best.pt".
        for preferred in ("yolo11m_vlr.pt", "yolo11s_vlr.pt", "yolo11n_vlr.pt",
                          "yolov10b_vlr.pt", "yolov10s_vlr.pt", "yolov10n_vlr.pt",
                          "best.pt"):
            if preferred in candidates:
                filename = preferred
                break
        else:
            filename = candidates[0]

    print(f"[hub] downloading {repo_id}/{filename} ...")
    local_path = hf_hub_download(repo_id=repo_id, filename=filename)
    return Path(local_path)


# --------------------------------------------------------------------- #
# ONNX export via ultralytics
# --------------------------------------------------------------------- #
def _export_to_onnx(
    pt_path: Path,
    imgsz: int = DEFAULT_IMGSZ,
    half: bool = True,
) -> Path:
    """Export ``pt_path`` to ONNX at ``imgsz x imgsz`` and return the .onnx path.

    The export uses opset 12 (matches ORT/QNN compatibility) and FP16
    when ``half=True`` (QNN HTP's native dtype). The exported file
    lives next to ``pt_path``; we then move/copy it into ``models/``.
    """
    from ultralytics import YOLO

    print(f"[export] loading {pt_path.name} ...")
    model = YOLO(str(pt_path))

    print(f"[export] exporting → ONNX (imgsz={imgsz}, half={half}) ...")
    onnx_path = model.export(
        format="onnx",
        imgsz=imgsz,
        half=half,
        opset=12,
        simplify=True,
        dynamic=False,
    )
    return Path(onnx_path)


def _print_config_diff(
    onnx_dest: Path,
    class_names: dict,
    target_classes: List[int],
    imgsz: int,
    confidence: float = 0.40,
) -> None:
    """Print the config.yaml + CLASS_NAMES patch the user has to apply."""
    rel_path = onnx_dest.relative_to(REPO_ROOT).as_posix()
    print()
    print("=" * 70)
    print("Done. Apply these edits to use the new model:")
    print("=" * 70)
    print()
    print("[1] config.yaml — under 'ai_engine:'")
    print(f"  model_path: ./{rel_path}")
    print(f"  capture_size: {imgsz}")
    print(f"  target_classes: {target_classes}")
    print(f"  confidence: {confidence}")
    print()
    print("[2] engines/ai_engine.py — replace the CLASS_NAMES dict:")
    print(f"  CLASS_NAMES = {class_names!r}")
    print()
    print("[3] Run:")
    print("  python main_simple.py --debug-frame --debug-classes")
    print()


# --------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------- #
def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download + export a Valorant YOLO model to ONNX for QNN HTP."
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=(
            "Hugging Face repo id (default: %(default)s). "
            "Pre-tested options: jparedesDS/valorant-yolo11m (Body+Head, "
            "recommended), jparedesDS/valorant-yolov10b (alt arch), "
            "keremberke/yolov8m-valorant-detection (4 classes "
            "incl. enemy/teammate)."
        ),
    )
    parser.add_argument(
        "--filename",
        default=None,
        help="Specific .pt file inside the repo. Auto-picks if omitted.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=DEFAULT_IMGSZ,
        help="ONNX input resolution (default: %(default)s). 416 is the "
             "current pipeline default; 640 is more accurate but ~2x slower.",
    )
    parser.add_argument(
        "--no-half",
        action="store_true",
        help="Disable FP16 export (use FP32). QNN HTP runs FP16 natively; "
             "FP32 falls back to a slower path. Off by default — keep FP16.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Override output filename (default: derived from --repo, e.g. "
             "valorant-yolo11m.onnx).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    _ensure_deps()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Download
    pt_path = _download_pt(args.repo, args.filename)
    print(f"[hub] cached: {pt_path}")

    # 2. Export to ONNX (will land next to pt_path inside the HF cache dir)
    onnx_src = _export_to_onnx(
        pt_path, imgsz=args.imgsz, half=not args.no_half
    )

    # 3. Move into models/ with a stable name
    if args.out:
        dest_name = args.out
    else:
        # Derive from repo name: "jparedesDS/valorant-yolo11m" → "valorant-yolo11m.onnx"
        repo_tail = args.repo.split("/")[-1]
        dest_name = f"{repo_tail}.onnx"
    onnx_dest = MODELS_DIR / dest_name
    if onnx_dest.exists():
        backup = onnx_dest.with_suffix(".onnx.bak")
        print(f"[export] backing up existing {onnx_dest.name} → {backup.name}")
        shutil.move(str(onnx_dest), str(backup))
    shutil.copy2(str(onnx_src), str(onnx_dest))
    print(f"[export] saved: {onnx_dest}")

    # 4. Print the config diff. Class names depend on the chosen repo.
    repo_lower = args.repo.lower()
    if "valorant-yolo11" in repo_lower or "valorant-yolov10" in repo_lower:
        # jparedesDS family — 2 classes Body/Head
        class_names = {0: "body", 1: "head"}
        target_classes = [1]  # head-only for headshot aimbot
        confidence = 0.40
    elif "valorant-detection" in repo_lower:
        # keremberke family — 4 classes
        class_names = {
            0: "dropped_spike",
            1: "enemy",
            2: "planted_spike",
            3: "teammate",
        }
        target_classes = [1]  # enemies only
        confidence = 0.40
    else:
        # Unknown repo — leave the existing names in place
        class_names = {0: "enemy", 1: "ally"}
        target_classes = [0]
        confidence = 0.40
        print()
        print(
            "[warn] unknown repo — class_names guessed; verify against the "
            "repo's README and update CLASS_NAMES manually."
        )

    _print_config_diff(
        onnx_dest=onnx_dest,
        class_names=class_names,
        target_classes=target_classes,
        imgsz=args.imgsz,
        confidence=confidence,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
