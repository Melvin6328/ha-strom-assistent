# Strom-Assistent (Home Assistant Custom Integration)

Drei Funktionen rund um den Stromzähler (z. B. Shelly Pro 3EM), alles per UI konfigurierbar:

- **A Tarif & Kosten** – Preise mit Gültig-ab-Datum (historisch korrekt), optional dynamischer Preis;
  Sensoren für Kosten heute/Monat/Jahr, Einspeiseerlös, Netto-Kosten, Hochrechnung, aktueller Preis.
- **B Lastprofil & Anomalie** – Baseline je Wochentag/Stunde (Median/MAD), Grundlast, Abweichung in %,
  Binary Sensor „Anomalie“ + Event `strom_assistent_anomalie`; optional Geräteerkennung
  (Event `strom_assistent_geraet_erkannt`).
- **C Statistik-Lücken** – Dienste `strom_assistent.luecke_pruefen` und `strom_assistent.luecke_reparieren`
  plus Repair-Issue bei erkannter Lücke.

Fehlt eine Quelle oder ist sie `unavailable`/`unknown`, werden die Sensoren `unavailable` (nie 0) und ein
Repair-Issue wird angelegt.

## Installation

1. Ordner `custom_components/strom_assistent` nach `/config/custom_components/` kopieren
   (oder per HACS als benutzerdefiniertes privates Repository).
2. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Strom-Assistent*.
   Quellen: Bezugs-/Einspeise-Energiezähler und Leistung. Optional die Helfer, die auf Lücken
   geprüft werden sollen (Bezug-/Einspeise-Energie, Bezug-/Einspeise-Leistung).
4. *Konfigurieren* (Optionen): Tarif hinzufügen, optional Preis-Entität, Anomalie-Schwellen, Geräteerkennung.

Hinweis: Sensorwerte entstehen aus den Langzeitstatistiken (stündlich). Ohne mindestens einen Tarif
bleiben die Kostensensoren `unavailable`.

## Statistik-Lücke reparieren (Erstfall 2026-11-09 20:43 → 2026-11-10 ~09:55)

Immer zuerst Vorschau (`dry_run` ist Standard `true`, es wird nichts geschrieben):

```yaml
action: strom_assistent.luecke_reparieren
data:
  entity_id: sensor.mein_verbrauch_energie
  richtung: bezug
  start: "2026-11-09 20:00:00"
  ende: "2026-11-10 10:00:00"
  dry_run: true
response_variable: vorschau
```

Für die Einspeisung: `entity_id: sensor.mein_einspeisung_energie`, `richtung: einspeisung`.
Die Antwort enthält Lücken, fehlende kWh und die neuen `sum`-Werte. Passt alles, `dry_run: false` setzen.

Wie repariert wird (Energie): Lückenstunden bekommen das Delta des echten Zählers
(deine konfigurierte Bezugs- bzw. Einspeise-Energie); alle **späteren** Stundenzeilen werden um die
nachgetragene Energie verschoben, damit Differenzen im Energy-Dashboard stimmen (`state` bleibt unverändert).
Plausibilitätsprüfung: Stundendelta 0…30 kWh, Summe ≤ `max_kwh` (Standard 100). Es werden nur Stunden
verändert, in denen das Ziel < 50 % des Referenzzählers erreicht hat. Jede Reparatur wird als Warnung im Log
dokumentiert. Leistungs-Statistiken (Mittel/Min/Max) werden aus der Referenzleistung abgeleitet
(Näherung: Bezug = max(P,0), Einspeisung = max(−P,0)).

Vorher ein Backup anlegen – Statistik-Importe lassen sich nicht automatisch zurückrollen.

## Beispiel-Automation: Anomalie-Benachrichtigung

```yaml
alias: Strom-Anomalie melden
triggers:
  - trigger: event
    event_type: strom_assistent_anomalie
actions:
  - action: notify.notify
    data:
      title: Stromverbrauch auffällig
      message: >-
        Gründe: {{ trigger.event.data.gruende | join(', ') }},
        Abweichung: {{ trigger.event.data.abweichung_prozent }} %,
        Grundlast: {{ trigger.event.data.grundlast_w }} W
```

Geräteerkennung: Event `strom_assistent_geraet_erkannt` mit `delta_w`, `richtung` (`an`/`aus`),
`leistung_vorher_w`, `leistung_nachher_w`, `zeitpunkt`.

## Energy-Dashboard

`Aktueller Preis` (EUR/kWh) und `Aktuelle Einspeisevergütung` können dort als „Entität mit aktuellem Preis“
gewählt werden. Kostensensoren haben `device_class: monetary`, Währung `EUR`.

## Entwicklung

```
pip install -r requirements_test.txt
ruff check . && pytest
```

Reine Logik liegt in `custom_components/strom_assistent/logic/` (ohne HA-Abhängigkeit).
