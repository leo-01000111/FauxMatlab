# PyInstaller spec — a one-folder build.
#
# One folder rather than one file. A one-file build unpacks the whole Qt
# runtime to a temporary directory on every launch, which for PySide6 plus
# scipy plus sympy is a few seconds of disk churn before the window appears.
# The folder starts immediately and is what you want for something people
# open several times a day.
#
#   pyinstaller --clean --noconfirm packaging/fauxmatlab.spec
#
# Then check the result actually works:
#
#   dist/FauxMatlab/FauxMatlab-check.exe --check

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent

# Our own modules are imported lazily at the bottom of functions all over the
# codebase — the console's `sim`, the tuner's `tuning`, the lessons' probes.
#
# `control` is deliberately *not* collected wholesale. `collect_submodules`
# walks every submodule, which reaches `control.tests.*`; those import pytest,
# pytest drags in its plugin ecosystem, and that reaches whatever else is
# installed. On a development machine with torch, jax, OpenCV and transformers
# present, that turned a 1.5 GB folder out of a 400 MB application. The static
# scan already follows the parts of `control` this code actually imports.
HIDDEN = (
    collect_submodules("fakematlab")
    + ["scipy.special._cdflib", "scipy._lib.messagestream"]
)

# Qt modules this app never touches. Dropping them takes a large bite out of
# the build without changing what runs: the whole WebEngine stack alone is
# bigger than everything else put together.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.QtQuick3D", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSerialPort",
    "PySide6.QtDesigner", "PySide6.QtHelp",
    # Not QtTest: pyqtgraph imports it for its input-simulation helpers, so
    # excluding it breaks the frozen build where the source tree works.
    # The other Qt bindings. All three are installed in the dev environment
    # and PyInstaller will happily bundle every one of them; two of the three
    # would then fight the first over the Qt DLLs at run time, which is the
    # same conflict `app.py` pins the binding to avoid.
    "PyQt5", "PyQt6", "tkinter",

    # Test suites. `control.tests` is the one that matters: it imports pytest
    # at module level, and pytest's plugin discovery is what opens the door to
    # everything below.
    "pytest", "_pytest", "control.tests", "scipy.tests", "numpy.tests",
    "sympy.testing",

    # NOT excluded, though it is tempting: matplotlib, and python-control's
    # plotting modules. This application draws with pyqtgraph and never calls
    # them — but `control/__init__.py` imports `ctrlplot`, `freqplot`,
    # `timeplot`, `nichols`, `pzmap`, `rlocus`, `sisotool` and `phaseplot`
    # unconditionally, and those import matplotlib at module level. Excluding
    # any of them turns `import control` into ModuleNotFoundError, which is
    # what the frozen build's own self-test reported when this was tried.
    # matplotlib is a hard runtime dependency of python-control 0.10.

    # Present in the development environment, used by none of this. Named
    # explicitly rather than trusted to the import scan, because a fat
    # site-packages is the normal case on a machine that does other work.
    "torch", "torchvision", "jax", "jaxlib", "transformers", "tokenizers",
    "cv2", "sklearn", "skimage", "pandas", "pyarrow", "llvmlite", "numba",
    "plotly", "pygame", "grpc", "nltk", "wandb", "IPython", "notebook",
    "jupyter", "jupyter_client", "jupyter_core", "zmq", "tornado",
]

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    # Runs before any package is imported. A windowed build has no standard
    # streams, and several scientific packages capture `sys.stderr.write` at
    # import time — see the hook for the numpy chain that crashed the launch.
    runtime_hooks=[str(SPEC_DIR / "rthook_stdio.py")],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

def _exe(name: str, console: bool):
    return EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


# Two entry points over one bundle — the second costs a few hundred kilobytes,
# not a second copy of Qt.
#
# A windowed executable on Windows has no stdout at all, so `--check` from
# `FauxMatlab.exe` would set an exit code and print nothing, which is useless
# to anybody diagnosing an installation by hand. `FauxMatlab-check.exe` is the
# same program built as a console application, so its report is readable.
gui = _exe("FauxMatlab", console=False)
check = _exe("FauxMatlab-check", console=True)

coll = COLLECT(
    gui,
    check,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FauxMatlab",
)
