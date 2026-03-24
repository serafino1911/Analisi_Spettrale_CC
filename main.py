import sys

from PyQt5.QtWidgets import QApplication

from sourcecode.gui_app import SpectraMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = SpectraMainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
