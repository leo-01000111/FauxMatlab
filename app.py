"""
Run Evans from a checkout, without installing it:

    python app.py            open the window
    python app.py --check    run the headless self-test and exit
    python app.py --version  print the version and exit

The program itself is :mod:`evans.app`; an installed copy runs it as the
``evans`` command. This file only puts ``src/`` on the path first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from evans.app import main

if __name__ == "__main__":
    main()
