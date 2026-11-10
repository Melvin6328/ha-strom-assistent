"""Konstanten für Strom-Assistent."""

from __future__ import annotations

DOMAIN = "strom_assistent"

# Config (Quell- und Ziel-Entitäten)
CONF_BEZUG_ENERGIE = "bezug_energie"
CONF_EINSPEISE_ENERGIE = "einspeise_energie"
CONF_LEISTUNG = "leistung"
CONF_ZIEL_BEZUG_ENERGIE = "ziel_bezug_energie"
CONF_ZIEL_EINSPEISE_ENERGIE = "ziel_einspeise_energie"
CONF_ZIEL_BEZUG_LEISTUNG = "ziel_bezug_leistung"
CONF_ZIEL_EINSPEISE_LEISTUNG = "ziel_einspeise_leistung"

# Options
OPT_TARIFE = "tarife"
OPT_PREIS_ENTITAET = "preis_entitaet"
OPT_K = "empfindlichkeit"
OPT_STUNDEN = "anomalie_stunden"
OPT_MIN_ABWEICHUNG_W = "min_abweichung_w"
OPT_GERAETE_AKTIV = "geraete_aktiv"
OPT_GERAETE_SCHWELLE_W = "geraete_schwelle_w"
OPT_GERAETE_DAUER_S = "geraete_dauer_s"
OPT_LUECKE_TAGE = "luecke_tage"

DEFAULT_K = 3.0
DEFAULT_STUNDEN = 3
DEFAULT_MIN_ABWEICHUNG_W = 50.0
DEFAULT_GERAETE_SCHWELLE_W = 300.0
DEFAULT_GERAETE_DAUER_S = 60
DEFAULT_LUECKE_TAGE = 3

EVENT_ANOMALIE = "strom_assistent_anomalie"
EVENT_GERAET = "strom_assistent_geraet_erkannt"

SERVICE_LUECKE_PRUEFEN = "luecke_pruefen"
SERVICE_LUECKE_REPARIEREN = "luecke_reparieren"

RICHTUNG_BEZUG = "bezug"
RICHTUNG_EINSPEISUNG = "einspeisung"

ISSUE_QUELLE = "quelle_nicht_verfuegbar"
ISSUE_LUECKE = "statistik_luecke"
