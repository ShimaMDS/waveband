"""Waveband, a passive damage meter for Wuthering Waves: reads the game's own log file and the
screen, and never touches the game process. ``wwmeter`` is its internal name."""

import os

# NumPy's maths library (OpenBLAS) sets aside a work buffer for each CPU thread when NumPy is
# imported: about 480 MB of the meter's 760 MB of committed memory on a 16-thread CPU, almost
# none of it ever used. The meter does no large matrix maths (the title reader runs on ONNX
# Runtime), so one thread does. Set here, before anything of the meter imports NumPy.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

# 0.2.0 is the first public release (on GitHub, as Waveband). Between releases this is the next
# version with .dev0 on the end.
__version__ = "0.3.1"
