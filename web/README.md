# DCM → STL (lokaal)

Minimalistische webinterface voor de bestaande **Open3SDCMCLI**. Geen cloud, externe webserver of Python-pakketten nodig: de Python standaardbibliotheek verzorgt de webinterface.

1. Bouw de Open3SDCMCLI volgens de instructies in de hoofd-README (of gebruik een bestaande build).
2. Start vanuit de root van de repository:

   ```bash
   python web/app.py
   ```

3. Open **http://127.0.0.1:8765** en sleep een `.dcm`-bestand in het venster. Een geldige `.stl` downloadt automatisch.

De webinterface vindt `Open3SDCMCLI` in `builds/*/bin/` of via `PATH`. Staat de CLI elders, zet dan `OPEN3SDCM_CLI` naar het volledige pad van de executable:

```powershell
$env:OPEN3SDCM_CLI = "C:\pad\naar\Open3SDCMCLI.exe"
python web/app.py
```

Een andere poort kiezen: `python web/app.py --port 8766`.

## Grenzen

- Eén DCM-bestand per keer; maximaal 100 MB; conversietime-out van 3 minuten.
- Alleen toegankelijk via `127.0.0.1` (dezelfde computer). Geen cloud-upload of permanente opslag; tijdelijke invoer/uitvoer wordt verwijderd na afloop van het verzoek.
- De bestaande CLI bepaalt welke DCM-schema's ondersteund worden. Niet-ondersteunde of versleutelde bestanden kunnen falen.
- Het systeem controleert dat de CLI daadwerkelijk een niet-lege, correct gestructureerde binaire STL heeft aangemaakt, omdat de CLI bij sommige fouten toch exitcode 0 teruggeeft.
