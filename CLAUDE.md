# Light Linker – Hinweise für die Weiterentwicklung

Home-Assistant-Custom-Integration (Domain `light_linker`), Oberfläche auf Deutsch.

- Code: `custom_components/light_linker/` (Backend Python, Panel `frontend/light-linker-panel.js` als einzelne Web-Component ohne Build-Schritt).
- Gerätebilder: `custom_components/light_linker/devices/*.json` (`match` auf Modell / model_id, `buttons` mit Slots `taste:ereignis`).
- Tests: `pip install -r requirements_test.txt`, dann `pytest -q`.
- Version immer an drei Stellen gleich setzen: `manifest.json`, `const.py` (`VERSION`), `light-linker-panel.js` (`LL_VERSION`), dazu Abschnitt „Neu in x.y.z“ in `README.md`.
- Der Nutzer installiert manuell (ZIP mit `custom_components/`, `README.md`, `hacs.json`) oder über HACS als benutzerdefiniertes Repository.
