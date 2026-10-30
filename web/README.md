# Webinterface

The web application uses the published Python package `open3sdcm==1.1.4` for DCM decoding and NumPy to stream a standard binary STL in batches. No C++ CLI build or Docker is required. Install the Python package with `pip` or launch via `start.bat` from the ZIP root.

Run `python web/app.py`, then open http://127.0.0.1:8765. The browser opens automatically unless `--no-browser` is passed. Use `--port 8766` to change the port.

Privacy: binds to loopback only; one DCM <=100 MB per request; uploads temporarily kept on disk and removed once the request completes. No telemetry. Only geometry exports to STL, not texture or colour. Unsupported and encrypted DCM files can still fail.

Tests: `python -m unittest discover -s web -p 'test_*.py' -v`.
