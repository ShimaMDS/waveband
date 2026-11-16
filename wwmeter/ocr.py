"""Read one line of text (the boss's name and level above its bar) with a small neural network.

This is the text recognizer from PaddleOCR's PP-OCRv3 (Chinese and Latin script), as packaged by
RapidOCR, run here directly on ONNX Runtime. RapidOCR also brings a text detector, an angle
classifier, OpenCV, Shapely and pyclipper; reading a line whose place is already known needs none
of them, and leaving them out takes about 60 MB off the download. What is done to the picture
and to the network's output is RapidOCR's ``TextRecognizer`` with ``use_det=False,
use_cls=False``, the way the meter called it before.

The model file is ``data/ocr/ch_PP-OCRv3_rec_infer.onnx`` (Apache-2.0, see the NOTICE beside it);
its list of characters is stored inside it.
"""

from __future__ import annotations

import math
import os

import numpy as np

from .config import ROOT

MODEL = os.path.join(ROOT, "data", "ocr", "ch_PP-OCRv3_rec_infer.onnx")
_HEIGHT = 48  # the network's input height
_MIN_SCORE = 0.5  # RapidOCR's text_score: a reading below this counts as nothing read


def _resize_bilinear(img: np.ndarray, width: int, height: int) -> np.ndarray:
    """Bilinear resize with pixel centres aligned (as OpenCV's INTER_LINEAR), in float32."""
    src_h, src_w = img.shape[:2]
    if (src_w, src_h) == (width, height):
        return img.astype(np.float32)

    def axis(dst: int, src: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        pos = (np.arange(dst, dtype=np.float64) + 0.5) * (src / dst) - 0.5
        pos = np.clip(pos, 0, src - 1)
        low = np.floor(pos).astype(np.int64)
        high = np.minimum(low + 1, src - 1)
        return low, high, (pos - low).astype(np.float32)

    y0, y1, fy = axis(height, src_h)
    x0, x1, fx = axis(width, src_w)
    img = img.astype(np.float32)
    rows = img[y0] * (1 - fy)[:, None, None] + img[y1] * fy[:, None, None]
    return rows[:, x0] * (1 - fx)[None, :, None] + rows[:, x1] * fx[None, :, None]


class TextReader:
    """``reader(bgr) -> (text, score)``, or ``("", 0.0)`` when nothing is read with confidence."""

    def __init__(self, model: str = MODEL) -> None:
        import onnxruntime as ort

        if not os.path.exists(model):
            raise FileNotFoundError(f"the text reader's model is missing: {model}")
        options = ort.SessionOptions()
        options.log_severity_level = 4
        options.enable_cpu_mem_arena = False
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            model, sess_options=options,
            providers=[("CPUExecutionProvider", {"arena_extend_strategy": "kSameAsRequested"})],
        )
        self._input = self._session.get_inputs()[0].name
        characters = self._session.get_modelmeta().custom_metadata_map["character"].splitlines()
        # index 0 is CTC's blank; a space is added at the end, as PaddleOCR does
        self._characters = ["", *characters, " "]

    def _prepare(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        ratio = w / float(h)
        width = int(_HEIGHT * ratio)
        resized_w = min(width, int(math.ceil(_HEIGHT * ratio)))
        image = _resize_bilinear(bgr, resized_w, _HEIGHT)
        image = (image.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
        batch = np.zeros((1, 3, _HEIGHT, width), dtype=np.float32)
        batch[0, :, :, :resized_w] = image
        return batch

    def __call__(self, bgr: np.ndarray) -> tuple[str, float]:
        if bgr.ndim != 3 or bgr.shape[2] != 3 or min(bgr.shape[:2]) == 0:
            return "", 0.0
        preds = self._session.run(None, {self._input: self._prepare(bgr)})[0][0]
        best, prob = preds.argmax(axis=1), preds.max(axis=1)
        keep = best != 0
        keep[1:] &= best[1:] != best[:-1]  # CTC: a repeat without a blank between is one character
        text = "".join(self._characters[i] for i in best[keep])
        score = float(np.mean(np.append(prob[keep], 1e-50))) if keep.any() else 1e-50
        if score < _MIN_SCORE:
            return "", 0.0
        return text, score
