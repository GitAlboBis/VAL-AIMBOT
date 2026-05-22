"""
Convert ONNX model from FP32 to FP16 in place.

Run with: ``python tools\\convert_model_fp16.py``

Input:  ./models/v11n-416-2.onnx     (FP32, ~10 MB)
Output: ./models/v11n-416-2-fp16.onnx (FP16, ~5 MB)

The FP16 variant cuts the QNN HTP DMA bandwidth in half and lets the input
buffer stay in QNN's native tensor format, which on Snapdragon X Elite
typically improves median inference latency by 30-50%. The FP32 model is
left untouched as a safety fallback.

Uses ``onnxconverter-common.float16.convert_float_to_float16`` which:

  * Promotes ops that don't have FP16 kernels back to FP32 around their
    boundaries via Cast nodes (``keep_io_types=False`` keeps inputs/outputs
    in FP16, so the QNN provider's pre-allocated FP16 buffer feeds the model
    directly without an extra cast).
  * Clamps weights that overflow FP16's [-65504, 65504] range to avoid
    Inf/NaN drift.
  * Skips initializers smaller than the size threshold (default keeps tiny
    constants in FP32 because the conversion overhead exceeds the savings).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "models" / "v11n-416-2.onnx"
DST = REPO_ROOT / "models" / "v11n-416-2-fp16.onnx"


def main() -> int:
    if not SRC.exists():
        print(f"[FAIL] Source model not found: {SRC}")
        return 1

    print(f"Loading: {SRC}")
    import onnx
    from onnxconverter_common import float16

    model = onnx.load(str(SRC))

    print("Converting to FP16 (keep_io_types=False, op_block_list=default)...")
    # ``keep_io_types=False`` makes the model accept FP16 inputs / outputs
    # directly so the QNN provider's pre-allocated FP16 NCHW buffer feeds the
    # graph without an extra Cast node — that's where most of the latency
    # savings come from. Some ops (NonMaxSuppression on older opsets, etc.)
    # are auto-blocked by the converter's default block list.
    #
    # ``op_block_list`` extends the default list. ``Resize`` has known
    # mixed-dtype handoff issues in onnxconverter-common's auto-cast pass on
    # YOLO-style upsample layers — leaving them in FP32 with Cast nodes on
    # both sides keeps the model loadable by ORT while still letting the
    # bulk of the convolution graph run in FP16.
    model_fp16 = float16.convert_float_to_float16(
        model,
        keep_io_types=False,
        disable_shape_infer=False,
        op_block_list=[
            "Resize",  # YOLO upsample handoff bug
        ],
    )

    # Post-conversion fix-up: ``onnxconverter-common`` sometimes leaves Cast
    # nodes whose declared output type doesn't match the actual produced
    # tensor type when an op is in the block list. Walk the graph and
    # synchronize Cast ``to`` attributes with their downstream consumers'
    # expected dtypes by inspecting each Cast and forcing its output value
    # info to match the ``to`` attribute. This is purely a metadata fix —
    # the runtime kernel already produces the correct dtype.
    from onnx import TensorProto, helper

    DTYPE_TO_TENSOR_TYPE = {
        TensorProto.FLOAT: 1,
        TensorProto.FLOAT16: 10,
    }
    DTYPE_NAMES = {1: "tensor(float)", 10: "tensor(float16)"}

    # Build a map from value-info name to the value_info proto so we can
    # fix declared types in place.
    value_info_by_name = {vi.name: vi for vi in model_fp16.graph.value_info}
    for vi in model_fp16.graph.output:
        value_info_by_name[vi.name] = vi
    for vi in model_fp16.graph.input:
        value_info_by_name[vi.name] = vi

    fixups = 0
    for node in model_fp16.graph.node:
        if node.op_type != "Cast":
            continue
        # Read the ``to`` attribute — that's the dtype the Cast emits.
        to_dtype = None
        for attr in node.attribute:
            if attr.name == "to":
                to_dtype = attr.i
                break
        if to_dtype is None:
            continue
        for out_name in node.output:
            vi = value_info_by_name.get(out_name)
            if vi is None:
                continue
            current = vi.type.tensor_type.elem_type
            if current != to_dtype:
                vi.type.tensor_type.elem_type = to_dtype
                fixups += 1
    if fixups > 0:
        print(f"[OK] Synchronized {fixups} Cast output value-info dtype(s)")

    print(f"Saving:  {DST}")
    onnx.save(model_fp16, str(DST))

    src_mb = SRC.stat().st_size / (1024 * 1024)
    dst_mb = DST.stat().st_size / (1024 * 1024)
    print()
    print(f"[OK] FP32 size: {src_mb:.2f} MB")
    print(f"[OK] FP16 size: {dst_mb:.2f} MB  ({dst_mb / src_mb * 100:.0f}% of FP32)")

    # Quick load sanity-check via ORT CPU EP — confirms the output graph is
    # actually a well-formed FP16 model that ORT can parse.
    print()
    print("Verifying FP16 model loads under CPUExecutionProvider...")
    import onnxruntime as ort

    sess = ort.InferenceSession(str(DST), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    out = sess.get_outputs()[0]
    print(f"[OK] Input:  {inp.name}  shape={inp.shape}  type={inp.type}")
    print(f"[OK] Output: {out.name}  shape={out.shape}  type={out.type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
