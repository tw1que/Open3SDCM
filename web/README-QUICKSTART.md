# DCM → STL — Windows

1. Pak de ZIP uit.
2. Dubbelklik `start.bat` (de eerste keer is internet nodig om het Python-pakket te installeren).
3. De browser opent op http://127.0.0.1:8765.
4. Sleep een of meerdere DCM-bestanden erin, of klik op **Bestanden kiezen**.

Eén DCM wordt een STL-download. Meerdere DCM's (maximaal 20) worden één ZIP met de geslaagde STL's. Fouten staan in `conversie-fouten.txt` in dezelfde ZIP.

Maximaal 100 MB per bestand en 500 MB totaal. Conversies lopen na elkaar. Alles blijft lokaal op de computer. Versleutelde of niet-ondersteunde DCM's kunnen falen.

Handmatig:

```cmd
python -m pip install --only-binary=:all: open3sdcm==1.1.4
python web/app.py
```
