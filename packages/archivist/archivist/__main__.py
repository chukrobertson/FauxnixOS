from __future__ import annotations

import sys

from archivist.db import init_db
from archivist.file_manager.daemon import ArchivistDaemon


def main():
    init_db()

    daemon = ArchivistDaemon()
    daemon.start()

    try:
        from archivist.file_manager.gui import ArchivistWindow
        from PyQt6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        window = ArchivistWindow()
        window.show()
        app.exec()
    except ImportError:
        print("PyQt6 not installed. Running headless daemon only.")
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    finally:
        daemon.stop()


if __name__ == "__main__":
    main()
