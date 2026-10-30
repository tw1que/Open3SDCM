# DCM → STL — lokale webinterface

Pak op Windows de ZIP uit en dubbelklik op `start.bat`. Dit installeert zo nodig `open3sdcm==1.1.4` en opent http://127.0.0.1:8765.

Handmatig starten:

```powershell
python -m pip install --only-binary=:all: open3sdcm==1.1.4
python web/app.py
```

Sleep een of meerdere DCM-bestanden naar het venster. Een enkel DCM-bestand levert direct een STL op. Bij 2–20 DCM-bestanden krijg je een ZIP met STL-bestanden die hun originele naam behouden. Als een bestand niet geconverteerd kan worden, gaat de batch door en komt `conversie-fouten.txt` met de mislukte namen in de ZIP. Als geen bestand slaagt, toont de browser een foutmelding. Dubbele bestandsnamen krijgen een uniek achtervoegsel.

Maximaal 100 MB per bestand en 500 MB totaal per batch (20 bestanden). De conversies worden na elkaar uitgevoerd, om het geheugenverbruik te beperken. Alleen lokaal bereikbaar via `127.0.0.1`, zonder cloud, met automatische verwijdering van tijdelijke data. STL bevat geen kleuren of texturen. Sommige versleutelde DCM-scans blijven niet ondersteund.

Tests: `python -m unittest discover -s web -p 'test_*.py' -v`.
