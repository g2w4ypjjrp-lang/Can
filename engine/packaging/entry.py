"""PyInstaller giriş noktası: paketlenmiş ``ati-engine`` çalıştırılabilir dosyası."""

import multiprocessing
import sys

from ati_engine.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows'ta paketlenmiş süreçler için
    sys.exit(main())
