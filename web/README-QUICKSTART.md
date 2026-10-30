# DCM → STL — Windows

**One-time setup:** Extract the ZIP, then double-click **start.bat**.

The first launch installs the published `open3sdcm` Python converter (requires internet). Thereafter it works locally, without cloud uploads. The browser opens automatically at http://127.0.0.1:8765 . Drop one `.dcm` file and the converted `.stl` downloads automatically.

**Manual alternative:**

```cmd
python -m pip install --only-binary=:all: open3sdcm==1.1.4
python web/app.py
```

Requires **64-bit Python 3.9+** on Windows, installed with `pip` support.
Only one file at a time, max 100 MB. Some encrypted CE files cannot be read. STL is geometry-only.
