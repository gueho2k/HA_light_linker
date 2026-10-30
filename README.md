# Light Linker

Verknüpft Taster und Schalter mit Lampen, Steckdosen und Garagentoren, dazu Bewegungs- und Präsenzmelder – ohne Automationen oder Node-RED-Flows. Version 0.5.5.

## Neu in 0.5.5

- **Alle Aktionen in jeder Belegung:** Das Belegungsfenster zeigt immer alle Aktionen, gegliedert in „Licht & Steckdose“, „Tor & Rollladen“ und „Sonstiges“ – unabhängig von Vorlage und Ziel. Ein Torschalter (Relais) lässt sich so auch frei mit „Tor / Rollladen“ (Impuls) belegen.
- Tore und Rollläden (cover) sind in jeder Vorlage als Ziel wählbar. „Umschalten“, „Einschalten“ und „Ausschalten“ bewegen sie (umschalten / öffnen / schließen), ohne Wiederholung.
- Hinweis, wenn „Öffnen/Schließen/Stopp“ an ein Ziel ohne Tor-Rückmeldung geht.

## Neu in 0.5.4

- **Mehrfach-Taster: Vorlage für eine Taste.** Beim Einrichten fragt Light Linker „Für welche Taste?“ (vorgewählt: die erste freie Taste, oder „alle Tasten“). So schaltet Taste 1 Tor 1 und Taste 2 Tor 2.
- **Belegung „alle Tasten“ einzeln ändern:** Der Stift in einer Zeile mit „gilt für alle Tasten“ ändert jetzt nur diese Taste; die anderen bleiben, wie sie sind. „Nichts“ hält eine einzelne Taste frei. Wird die Belegung für alle Tasten nirgends mehr gebraucht, steht sie unter „Weitere Belegungen“ mit dem Hinweis, dass sie entfernt werden kann.
- Beim Drücken eines echten Tasters leuchtet nur noch dessen Taste im großen Bild auf – nicht mehr gleichnamige Tasten anderer Taster in der Liste.

## Neu in 0.5.3

- **Moes/Tuya-Szenentaster mit allen Tasten:** Zigbee2MQTT nennt sie „Scene remote with 2/3 keys“ (ZT-B-EU1…4). Sie werden jetzt erkannt und mit allen Tasten gezeichnet, auch bevor jede Taste einmal gedrückt wurde.
- Unbekannte Taster, deren Modellname die Tastenzahl nennt („3 keys“, „2-gang“, „3-fach“), zeigen ebenfalls gleich alle Tasten.
- Neue Gerätedatei Aqara H1 Wippe doppelt (WXKG15LM) mit links, rechts, beide und Dreifachklick.

## Neu in 0.5.2

- **Räume & Geräte zeigt alle Lampen**, auch solche ohne Taster („noch kein Taster“, gestrichelt), nach Raum sortiert – z. B. SONOFF ZBMINI (01MINIZB), die ZHA als Licht anlegt. Ein Klick öffnet die Lampe, dort lässt sich direkt ein Taster zuweisen.
- Die Zielsuche findet Geräte auch über Hersteller und Modell („zbmini“, „sonoff“, „01MINIZB“).

## Neu in 0.5.1

- **Lichtgruppe nachträglich anlegen:** Taster, die schon genau diese Geräte geschaltet haben, schalten danach automatisch die Gruppe. Hieß die Verknüpfung nur nach den Lampen („Sofa1, Sofa3“), bekommt sie den Gruppennamen.
- **Lichtgruppe allein als Ziel** – beim Einrichten und im Belegungsfenster.
- **Taster umbenennen** (✎ neben dem Namen): ein lesbarer Name nur in Light Linker. Der Gerätename bleibt darunter sichtbar und in der Suche auffindbar.
- **„+ Taster einrichten“** öffnet direkt ein Einrichtungsfenster wie beim Bewegungsmelder: Taste drücken oder suchen, dann Ziel und Vorlage. Taster, deren Drücken nur „gedrückt“ meldet (z. B. press/press_release), werden jetzt beim ersten Druck erkannt.
- Belegungen für „alle Tasten“ stehen jetzt in den Zeilen jeder Taste („gilt für alle Tasten“) statt unter „Weitere Belegungen“; die Zählung „x von y belegt“ stimmt.
- Fernbedienungen ohne Gerätedatei mit an/aus und Dimmen werden als Wippe I/O gezeichnet.
- Startseite mit Knöpfen zum Loslegen und kurzer Erklärung der drei Reiter.
- Fehlerbehebungen: Seite blieb nach „Einrichten“ auf dem alten Stand; Light Linkers eigene Schalter „aktiv“ tauchten als Ziel auf; „gleicher Raum“ bei Geräten ohne Raum; Darstellung auf schmalen Bildschirmen (Tablet hochkant, Split-Screen) und lange Entitäts-IDs auf dem Handy.

## Neu in 0.5.0

- **Lichtgruppen in Light Linker:** Unter „Räume & Geräte“ → „+ Lichtgruppe anlegen“ fasst du Lampen, Steckdosen oder andere Gruppen zusammen, z. B. „Kellerlicht 1“ (002, 003, 004), „Kellerlicht 2“ (006, 007, 008) und „Kellerlicht gesamt“ (= Kellerlicht 1 + 2). Gruppen dürfen ineinander stecken; Zirkel verhindert Light Linker.
- Gruppen sind überall als Ziel wählbar (Belegung, Einrichten, Bewegungsmelder). Änderst du die Mitglieder einer Gruppe, gilt das sofort für alle Taster und Melder, die sie schalten.
- Gruppenseite: Mitglieder hinzufügen und entfernen, umbenennen, löschen, „Wird bedient von“ (auch über übergeordnete Gruppen), „+ Taster zuweisen“, Automatik.
- Automatisch zusammengefasste Geräte lassen sich mit „Als Lichtgruppe speichern“ zu einer festen Gruppe machen. In der Übersicht erscheinen Gruppen als eigene Zeile.
- Die Gruppen leben nur in Light Linker (keine zusätzlichen Entitäten). Eine Licht-Entität je Gruppe und das Anlegen als Zigbee2MQTT-Gruppe sind für später vorgesehen.

## Neu in 0.4.5

- Der Name der Verknüpfung erscheint auch bei einzelnen Geräten (z. B. „Sofalicht“ für Sofa2), wenn die Verknüpfung genau diese Geräte schaltet – in „Räume & Geräte“ und in der Übersicht.
- Umbenennen (✎) direkt dort, wo der Name steht: Kopf der Geräteseite, Zeile in der Übersicht, Melder-Karte, Verknüpfungen eines Tasters.

## Neu in 0.4.4

- Zusammengefasste Geräte tragen den Namen ihrer Verknüpfung (z. B. „Fensterecke“ statt „Sofa1, Sofa3“) – in „Räume & Geräte“ und in der Übersicht, sofern alle Belegungen aus einer Verknüpfung kommen.
- „+ Taster zuweisen“ hat ein Suchfeld: Taster suchen, dann Taste und Ereignis wählen.
- Gruppen auflösen: Jedes Gerät einer Gruppe lässt sich einzeln öffnen. Dort kann es eigene Taster bekommen oder mit × aus einer gemeinsamen Belegung gelöst werden; die anderen Geräte bleiben belegt.

## Neu in 0.4.3

- **Bereinigen:** Doppelt angelegte Belegungen werden erkannt (Hinweis oben in der Taster-Liste und beim Taster). „Bereinigen“ behält jede Belegung einmal – in der ältesten Verknüpfung – und löscht Verknüpfungen, die dadurch leer werden.
- **Taster entfernen:** Auf der Seite eines Tasters nimmt „Taster entfernen“ ihn aus allen Verknüpfungen. Verknüpfungen ohne weitere Taster werden gelöscht; die Abfrage zeigt vorher, welche.
- **Umbenennen:** Bei „Verknüpfungen dieses Tasters“ hat jede Verknüpfung ✎ zum Umbenennen und ⚙ für die Einstellungen. Der Schalter `switch.light_linker_…` behält seine Entitäts-ID, Automationen bleiben also gültig.
- **Zusammenfassen:** Gleiche Belegungen erscheinen in der Taster-Ansicht nur einmal. In der Übersicht werden Geräte mit gleicher Belegung zu einer Zeile („Sofa1, Sofa3“), unter „Räume & Geräte“ zu einem Eintrag mit Anzahl.

## Neu in 0.4.2

- Behoben: Anlegen und Ändern von Verknüpfungen schlug mit „unknown error“ fehl (falscher Aufruf der neuen Geräte-Suche von Home Assistant aus 0.4.1). Eine fehlschlagende Zustandsprüfung bricht das Speichern jetzt grundsätzlich nicht mehr ab.

## Neu in 0.4.1

- Behoben: Nach einem Update meldete eine noch offene Home-Assistant-Seite (z. B. über Nabu Casa oder in der App) „Unable to load custom panel“, weil dort noch die alte Panel-Version geladen war. Das Panel lädt die Seite jetzt in diesem Fall einmal selbst neu.
- Geräte werden über die neue Geräte-Suche von Home Assistant gefunden (Warnung „async_get_device is deprecated“ entfällt).

## Neu in 0.4.0

- **Jede Taste, jedes Ereignis einzeln belegbar.** Ein Taster ist jetzt ein Bild mit seinen Tasten; darunter steht jede Belegung: kurz, doppelt, dreifach, halten – jeweils mit eigener Aktion und eigenem Ziel. Ein RODRET kann z. B. mit „I“ das Kellerlicht umschalten, mit „O“ die Stehlampe, und gehalten dimmen.
- **Drei Ansichten:** *Taster* (Gerätebild, alle Plätze, freie gestrichelt), *Räume & Geräte* (wer bedient diese Lampe? „+ Taster zuweisen“ zeigt freie Tasten oder lernt per Tastendruck), *Übersicht* (Tabelle pro Raum: Geräte × Taster).
- **Rampe zum Dimmen**, pro Belegung einstellbar: *Zigbee direkt* (ein Befehl über Zigbee2MQTT oder ZHA, beim Loslassen Stopp – am flüssigsten), *Übergang* oder *Schritte*; Dauer, Unter-/Obergrenze, Verhalten bei ausgeschaltetem Licht. „Automatisch“ nimmt Zigbee direkt, wo die Lampe es kann.
- **Ende der Rampe je Taster:** Stopp-Ereignis (RODRET), Loslassen (Hue, Aqara), Wächter für Taster, die „halten“ wiederholen, oder ein Schritt bei Tastern ganz ohne Loslassen (Moes/Tuya).
- **Doppel- und Dreifachklick auch für Taster, die ihn nicht melden** (z. B. Hue-Wandschaltermodul): Light Linker zählt die Drücke selbst. Ein einzelner Klick wartet dann 0,4 s, ob ein zweiter folgt – aber nur an Tasten, auf denen ein Doppelklick belegt ist.
- **Gerätebibliothek** mit Bildern und Eigenheiten von IKEA RODRET, STYRBAR, SOMRIG, TRADFRI, Philips Hue Dimmschalter und Wandschaltermodul, Aqara 1-/2-fach und Mini, Tuya/Moes 1–4-fach. Andere Taster bekommen ein einfaches Bild aus ihren Ereignissen. Die Bibliothek liegt als JSON-Dateien in `devices/` und lässt sich erweitern.
- **Live-Markierung:** Drückst du den echten Taster, leuchtet seine Zeile im Panel kurz auf.
- **Umstellung:** Bestehende Verknüpfungen werden beim ersten Start in Belegungen übersetzt und verhalten sich wie bisher (Namen, Schalter `switch.light_linker_*` und Dashboard-Tasten bleiben). Der alte Speicherstand liegt als `.storage/light_linker.links.backup_0_3` daneben; wer zurück auf 0.3 will, benennt ihn zurück.
- Vorlagen (Taster, Wippe, Schalter, Tor) belegen einen neuen Taster mit einem Klick; danach ist jede Zeile einzeln änderbar.

## Neu in 0.3.1

- **Feineinstellungen bleiben offen**, wenn man darin etwas umstellt (z. B. Doppelklick auf „Farbe durchschalten“).
- **Farben und Farbtemperaturen grafisch wählen:** Farbfelder mit Farbwähler, Farbtemperatur als Regler mit Farbverlauf (begrenzt auf das, was die gewählten Lampen können), Vorschläge per Klick hinzufügen, Reihenfolge per Ziehen oder ‹ ›.

## Neu in 0.3.0

- **Bewegungsmelder und Präsenzmelder** (Verhalten „Bewegung“): Melder schalten ein, wenn es dunkler als die Schwelle ist (Standard 36 lx), und nach dem Nachlauf (Standard 30 s) wieder aus. Mehrere Melder pro Raum sind möglich; das Licht geht erst aus, wenn alle frei melden.
- **Von Hand hat Vorrang:** Wer das Licht am Wandschalter, im Dashboard oder per Sprache einschaltet, bekommt einen längeren Nachlauf (Standard 10 min ohne Bewegung, leer = bleibt an). Wer es von Hand ausschaltet, pausiert die Automatik, bis der Raum leer war (oder für eine feste Zeit).
- **Pausieren** über eine beliebige Entität, z. B. `input_boolean.film`, und Option „nur ausschalten“.
- **Status-Sensor** pro Bewegungs-Verknüpfung (`sensor.light_linker_<name>_status`: aus, automatisch an, Nachlauf, von Hand an, von Hand aus, inaktiv) mit Restzeit; das Panel zählt live herunter.
- **Zigbee2MQTT-Gruppen:** Sind alle Ziele einer Verknüpfung genau die Mitglieder einer Z2M-Gruppe, schaltet Light Linker die Gruppe – ein Funkbefehl, alle Lampen gleichzeitig.
- **Umzugshilfe ZHA → Zigbee2MQTT:** Ist ein Taster oder eine Lampe neu in Z2M gekoppelt, zeigt das Panel (und die Reparaturen-Seite) den Tausch; „Umstellen“ übernimmt ihn.
- **„Wird auch anderswo genutzt“:** Taster, die zusätzlich in Node-RED oder Automationen stecken, lassen sich mit einer Notiz markieren. Die Suche zeigt die Notiz und fragt vor dem Verknüpfen nach.

## Neu in 0.2.2

- Suchfelder ohne Suchbegriff zeigen wieder alles nach Raum gruppiert wie in 0.1: der Raum des Tasters zuerst, „Ohne Raum“ zuletzt, im Raum zuerst „Ganzer Bereich“, dann alphabetisch.
- Behoben: Beim Wechsel vom Quellen- ins Zielfeld blieb die erste Liste offen.

## Neu in 0.2.1

- Behoben: Das Panel meldete „Unknown error“, wenn im Gerätespeicher ein Gerät mit dreiteiliger Kennung steht. Die ZHA-Suche betrachtet jetzt nur noch ZHA-Geräte.
- Fällt eine Auswahlliste aus, zeigt das Panel trotzdem die Verknüpfungen und einen Hinweis.

## Neu in 0.2.0

- **Schnelles Drücken:** Light Linker merkt sich 3 s lang den zuletzt geschalteten Zustand. Ein zweiter Klick, bevor die Lampe ihren neuen Zustand gemeldet hat, schaltet zurück statt den ersten Befehl zu wiederholen.
- **Fehlergrund sichtbar:** Antwortet ein Gerät nicht, nennt die Benachrichtigung den Grund (z. B. „device did not respond“), das Panel zeigt ihn an der Verknüpfung.
- **Sparsamer:** Light Linker folgt nur noch den Tastern, die in Verknüpfungen stehen; die Zustandsprüfung wartet auf Ereignisse statt alle 250 ms nachzusehen.
- **Suchfelder** für Ziele und Quellen: tippen filtert nach Name, Entitäts-ID und Raum, Pfeiltasten und Enter wählen aus.
- **„Reagiert auf“:** pro Verknüpfung Klick, Doppelklick, Dreifachklick und Halten an- oder abwählen; das Panel warnt, wenn zwei Verknüpfungen dasselbe Ereignis derselben Taste belegen.
- **Dashboard-Taste:** optional pro Verknüpfung `button.light_linker_<name>_taste`, wirkt wie ein kurzer Klick.
- **ZHA-Taster** (z. B. TS0043) als Quelle, erkannt über die IEEE-Adresse.
- **Reparaturhinweise**, wenn eine Quelle oder ein Ziel gelöscht wurde; **Diagnosedaten** zum Herunterladen.

## Was Light Linker kann

- Quellen: Event-Entitäten (Zigbee2MQTT, Homematic IP, Matter, Hue …), ZHA-Taster, Eingänge (`binary_sensor`, `input_boolean`, `switch`) und Melder (`binary_sensor` der Klassen motion, occupancy, presence)
- Belegungen je Taste und Ereignis: umschalten, ein, aus, Helligkeit, Rampe hoch/runter/wechselnd, Farbtemperatur oder Farbe durchschalten, Szene, Tor/Rollladen (Impuls, auf, zu, stopp)
- Vorlagen: **Taster** (Klick schaltet um, Halten dimmt), **Wippe** (oben an, unten aus), **Schalter** (Wechselschaltung), **Tor** (nur Einzelklick, `cover.toggle`); dazu **Bewegung** (Melder mit Helligkeitsschwelle und Nachlauf)
- Zustandsprüfung mit Wiederholung und Benachrichtigung (bei Toren nie Wiederholung)
- Panel in der Seitenleiste (nur Admins) mit Anlernmodus und Testknopf
- Pro Verknüpfung ein Schalter `switch.light_linker_<name>` als Fallback-Schalter für alte Automationen
- Logbuch-Einträge, Aktion `light_linker.trigger`

Noch nicht enthalten (siehe Spezifikation): Export als Automation, direkte Zigbee-Bindungen.

## Installation

### Variante A: von Hand kopieren

1. Den Ordner `custom_components/light_linker` aus dem ZIP nach `/config/custom_components/light_linker` kopieren, z. B. mit der App „Samba share“, „File editor“ oder „Studio Code Server“. Danach liegt dort u. a. `/config/custom_components/light_linker/manifest.json`.
2. Home Assistant neu starten: **Einstellungen → System → Neu starten**.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → „Light Linker“** wählen und bestätigen.
4. In der Seitenleiste erscheint **Light Linker**. Falls nicht: Seite mit Strg+F5 neu laden.

### Variante B: über HACS (eigenes GitHub-Repository)

1. Den Inhalt des ZIP als Repository auf GitHub hochladen (Wurzel mit `hacs.json`, `README.md` und `custom_components/`). In `manifest.json` `OWNER` durch den eigenen GitHub-Namen ersetzen.
2. **HACS → ⋮ → Benutzerdefinierte Repositories**, URL eintragen, Typ **Integration**.
3. „Light Linker“ in HACS herunterladen, Home Assistant neu starten, dann weiter wie oben ab Schritt 3.

Updates: den Ordner `light_linker` komplett ersetzen bzw. in HACS aktualisieren, neu starten, im Browser einmal Strg+F5. Bestehende Verknüpfungen bleiben erhalten.

## Ersten Taster einrichten

1. Panel öffnen, Ansicht **Taster**, **+ Taster anlernen** und eine Taste drücken – oder oben nach dem Taster suchen.
2. Für einen neuen Taster erscheint „Was soll dieser Taster schalten?“: Ziel wählen, Vorlage wählen, **Einrichten**.
3. Jede Zeile unter dem Bild lässt sich jetzt einzeln ändern (✎), testen (▶) oder neu belegen („frei – belegen“).
4. Vom Licht aus geht es auch: **Räume & Geräte** → Lampe wählen → **+ Taster zuweisen** → „Per Tastendruck wählen“ und die gewünschte Taste drücken (kurz, doppelt oder halten).

## Bewegungslicht einrichten

1. **Taster** → **+ Bewegungsmelder verknüpfen** (oder in **Räume & Geräte** bei der Lampe), im Quellenfeld „Bewegung“ tippen und den Melder wählen (oder anlernen: vor dem Melder bewegen). Das Verhalten springt auf **Bewegung**, der Helligkeitssensor desselben Geräts wird übernommen.
2. Ziele wählen, unter **Automatik** Schwelle und Nachlauf prüfen, **Anlegen**.
3. Wichtig bei Hue-Meldern (SML001/SML003): In Z2M die Einstellung „occupancy timeout“ bzw. in ZHA „Verzögerung belegt → frei“ nicht auf 0 lassen. Light Linker rechnet seinen Nachlauf ab „frei“; ein Melder-Timeout von 0 s meldet schon nach Sekunden „frei“, auch wenn noch jemand im Raum ist.
4. Wandtaster im selben Raum können zusätzlich als Quelle in derselben Verknüpfung stehen; sie zählen als „von Hand“.

## Fallback auf bestehende Automationen

Alte Automationen bleiben bestehen und bekommen diese Bedingung. Sie laufen dann nur, wenn die Verknüpfung abgeschaltet ist oder Light Linker nicht läuft (Schalter `unavailable`):

```yaml
conditions:
  - condition: not
    conditions:
      - condition: state
        entity_id: switch.light_linker_fensterecke
        state: "on"
```

Im Node-RED-Flow leistet ein „current state“-Knoten auf denselben Schalter dasselbe.

## Fehlersuche

- **Einstellungen → Geräte & Dienste → Light Linker → Debug-Logging aktivieren**, Taster drücken, Logging wieder deaktivieren: Das Protokoll wird heruntergeladen.
- Jede ausgelöste Verknüpfung steht im **Logbuch**.
- Reagiert ein Zigbee2MQTT-Taster nicht, prüfen, ob in Zigbee2MQTT „experimental event entities“ aktiv sind (bei dir schon der Fall).

## Entwicklung

```bash
pip install pytest-homeassistant-custom-component
pytest
```
