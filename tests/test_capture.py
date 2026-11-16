"""The desktop-duplication capture, with bettercam stood in for: it must never need OpenCV.

Asked for BGR, bettercam converts each frame with OpenCV, which the packaged meter does not ship
(it went with the boss-title reader in 0.3.0), so the capture would fail on its first frame.
Asked for BGRA, it returns a view of a GPU surface it has already unmapped. The meter replaces
bettercam's converter with its own, which copies the frame while it is still mapped.
"""

import sys
import types
import unittest
from unittest import mock

import numpy as np

from wwmeter import capture


class _Processor:
    """bettercam 1.0.0's NumpyProcessor, as far as the meter relies on it."""

    def process_cvtcolor(self, image):
        import cv2  # what the real one does; the meter must have replaced this

        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)


class _Camera:
    width, height = 2560, 1440

    def __init__(self, screen):
        self.screen = screen  # the "mapped surface"
        self._processor = types.SimpleNamespace(backend=_Processor())
        self.mapped = False

    def grab(self, region):
        x0, y0, x1, y1 = region
        self.mapped = True
        image = self._processor.backend.process_cvtcolor(self.screen[y0:y1])[:, x0:x1]
        self.mapped = False
        return image

    def release(self):
        pass


class DuplicationTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.bgra = rng.integers(0, 256, (1440, 2560, 4), dtype=np.uint8)
        self.created = []
        output = types.SimpleNamespace(hmonitor=1)
        fake = types.ModuleType("bettercam")
        setattr(fake, "__factory", types.SimpleNamespace(outputs=[[output]]))

        def create(**kwargs):
            self.created.append(kwargs)
            return _Camera(self.bgra)

        fake.create = create
        patches = [
            mock.patch.dict(sys.modules, {"bettercam": fake, "cv2": None}),  # no OpenCV at all
            mock.patch.object(capture.win32api, "MonitorFromWindow", return_value=1),
            mock.patch.object(capture.win32api, "GetMonitorInfo", return_value={"Monitor": (0, 0, 2560, 1440)}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_frames_come_out_bgr_without_opencv(self):
        backend = capture._DuplicationBackend()
        frame = backend.grab(123, (100, 50, 900, 450))
        self.assertEqual(self.created[0]["output_color"], "BGR")
        self.assertEqual(frame.shape, (400, 800, 3))
        np.testing.assert_array_equal(frame, self.bgra[50:450, 100:900, :3])

    def test_the_frame_is_a_copy_not_the_cameras_surface(self):
        frame = capture._DuplicationBackend().grab(123, (0, 0, 2560, 1440))
        self.assertFalse(np.shares_memory(frame, self.bgra))
        before = frame.copy()
        self.bgra[:] = 0  # the surface is reused for the next frame
        np.testing.assert_array_equal(frame, before)

    def test_a_bettercam_without_the_converter_is_refused(self):
        with self.assertRaises(RuntimeError):
            capture._convert_without_opencv(types.SimpleNamespace(_processor=types.SimpleNamespace(backend=object())))


if __name__ == "__main__":
    unittest.main()
