"""The desktop-duplication capture, with bettercam stood in for: the meter must ask it for BGRA.

Asked for BGR, bettercam converts each frame with OpenCV, which the packaged meter does not ship
(it went with the boss-title reader in 0.3.0): the capture would fail on its first frame. The
meter drops the alpha channel itself.
"""

import sys
import types
import unittest
from unittest import mock

import numpy as np

from wwmeter import capture


class _Camera:
    width, height = 2560, 1440

    def __init__(self, frame):
        self.frame = frame

    def grab(self, region):
        x0, y0, x1, y1 = region
        return self.frame[y0:y1, x0:x1]

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
            mock.patch.dict(sys.modules, {"bettercam": fake}),
            mock.patch.object(capture.win32api, "MonitorFromWindow", return_value=1),
            mock.patch.object(capture.win32api, "GetMonitorInfo", return_value={"Monitor": (0, 0, 2560, 1440)}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_asks_for_bgra_so_bettercam_never_needs_opencv(self):
        backend = capture._DuplicationBackend()
        backend.grab(123, (0, 0, 2560, 1440))
        self.assertEqual(self.created[0]["output_color"], "BGRA")

    def test_frames_come_out_bgr_and_contiguous(self):
        backend = capture._DuplicationBackend()
        frame = backend.grab(123, (100, 50, 900, 450))
        self.assertEqual(frame.shape, (400, 800, 3))
        self.assertTrue(frame.flags["C_CONTIGUOUS"])
        np.testing.assert_array_equal(frame, self.bgra[50:450, 100:900, :3])
        self.assertFalse(np.shares_memory(frame, self.bgra))  # a copy, not the camera's buffer


if __name__ == "__main__":
    unittest.main()
