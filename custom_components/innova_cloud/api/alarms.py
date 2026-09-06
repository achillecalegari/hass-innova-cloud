"""Alarm bit descriptions per product family, as shipped in the official app (AlarmDescriptions.strings).

Families: two_point_zero (Innova 2.0 air conditioners), waterloop, fancoil (AirLeaf & co.), m7 (thermostat),
idrowall_12v / idrowall_gree, diva_xli, yardy. Bit N set in the alarm bitmask means alarm N.
"""

from __future__ import annotations

ALARM_DESCRIPTIONS: dict[str, dict[int, dict[str, str]]] = {
    "diva_xli": {
        0: {"en": "T1 alarm fault", "it": "Allarme T1 fault"},
        1: {"en": "T2 alarm fault", "it": "Allarme T2 fault"},
        2: {"en": "T3 alarm fault", "it": "Allarme T3 fault"},
        3: {"en": "Condensate level alarm", "it": "Allarme livello condensa"},
    },
    "fancoil": {
        0: {"en": "Communication error (display E8)", "it": "Errore di comunicazione (display E8)"},
        1: {"en": "Room air probe failure (display E1)", "it": "Guasto sonda aria ambiente (display E1)"},
        2: {"en": "Cold-water probe T3/H4 failure (display E5)", "it": "Guasto sonda acqua fredda T3/H4 (display E5)"},
        3: {"en": "Water not suitable for the current season (display E6)", "it": "Acqua non idonea alla stagione corrente (display E6)"},
        4: {"en": "Hot-water probe T2/H2 failure (display E3)", "it": "Guasto sonda acqua calda T2/H2 (display E3)"},
        6: {"en": "Resistance overtemperature alarm (display E4)", "it": "Allarme sovratemperatura resistenza (display E4)"},
        7: {"en": "Fan motor fault (display E2)", "it": "Guasto motore ventilatore (display E2)"},
        8: {"en": "Grille input active (display Gr)", "it": "Ingresso griglia attivo (display Gr)"},
        9: {"en": "Water temperature not suitable on T2/H2 (display h2o)", "it": "Temperatura acqua non idonea su T2/H2 (display h2o)"},
        10: {"en": "Filter maintenance required (display CL)", "it": "Manutenzione filtro richiesta (display CL)"},
    },
    "idrowall_12v": {
        10: {"en": "Fan motor fault (display E8)", "it": "Motore ventilatore guasto (display E8)"},
        12: {"en": "Heat exchanger overtemperature (display E4, limit 78 C)", "it": "Sovratemperatura sullo scambiatore di calore (display E4, limite 78 C)"},
        13: {"en": "Water probe fault (display E3)", "it": "Sonda acqua guasta (display E3)"},
        14: {"en": "Air probe fault (display E2)", "it": "Sonda aria guasta (display E2)"},
        15: {"en": "Room temperature limit exceeded (display E5, limit 60 C)", "it": "Superato limite massimo temperatura ambiente (display E5, limite 60 C)"},
    },
    "idrowall_gree": {
        0: {"en": "Wired remote display temperature probe fault", "it": "Guasto sonda temperatura display remoto cablato"},
        1: {"en": "Coil 1 temperature probe fault", "it": "Guasto sonda temperatura batteria 1"},
        2: {"en": "Fan fault", "it": "Guasto ventilatore"},
        3: {"en": "Coil 2 temperature probe fault", "it": "Guasto sonda temperatura batteria 2"},
    },
    "m7": {
        0: {"en": "Communication error (display E8)", "it": "Errore di comunicazione (display E8)"},
        1: {"en": "Room air probe failure (display E1)", "it": "Guasto sonda aria ambiente (display E1)"},
        2: {"en": "Cold-water probe T3/H4 failure (display E5)", "it": "Guasto sonda acqua fredda T3/H4 (display E5)"},
        3: {"en": "Water not suitable for the current season (display E6)", "it": "Acqua non idonea alla stagione corrente (display E6)"},
        4: {"en": "Hot-water probe T2/H2 failure (display E3)", "it": "Guasto sonda acqua calda T2/H2 (display E3)"},
        6: {"en": "Resistance overtemperature alarm (display E4)", "it": "Allarme sovratemperatura resistenza (display E4)"},
        7: {"en": "Fan motor fault (display E2)", "it": "Guasto motore ventilatore (display E2)"},
        8: {"en": "Grille input active (display Gr)", "it": "Ingresso griglia attivo (display Gr)"},
        9: {"en": "Water temperature not suitable on T2/H2 (display h2o)", "it": "Temperatura acqua non idonea su T2/H2 (display h2o)"},
        10: {"en": "Filter maintenance required (display CL)", "it": "Manutenzione filtro richiesta (display CL)"},
    },
    "two_point_zero": {
        0: {"en": "Room probe failure (display E1)", "it": "Guasto sonda ambiente (display E1)"},
        1: {"en": "Air exchanger probe failure (display E2)", "it": "Guasto sonda scambiatore aria (display E2)"},
        2: {"en": "Outdoor air probe failure (display E3)", "it": "Guasto sonda aria esterna (display E3)"},
        3: {"en": "Outdoor exchanger probe failure (display E4)", "it": "Guasto sonda scambiatore esterno (display E4)"},
        4: {"en": "Indoor fan fault (display E5)", "it": "Guasto ventilatore interno (display E5)"},
        5: {"en": "Outdoor fan fault (display E6)", "it": "Guasto ventilatore esterno (display E6)"},
        6: {"en": "Inverter driver communication fault (display E7)", "it": "Guasto comunicazione driver inverter (display E7)"},
        7: {"en": "Discharge temperature probe failure (display E8)", "it": "Guasto sonda temperatura di scarico (display E8)"},
        8: {"en": "Remote function error (display F1)", "it": "Errore funzione remota (display F1)"},
        9: {"en": "Condensate water alarm (display F2)", "it": "Allarme acqua condensa (display F2)"},
        10: {"en": "Presence contact open (display F3)", "it": "Contatto presenza aperto (display F3)"},
        11: {"en": "Inverter fault (display F4)", "it": "Guasto inverter (display F4)"},
        15: {"en": "Low refrigerant or 4-way valve fault (display F8)", "it": "Basso refrigerante o guasto valvola a 4 vie (display F8)"},
        16: {"en": "Compressor mismatch error (display E10)", "it": "Errore incompatibilita compressore (display E10)"},
        18: {"en": "Heating resistance probe error (display E12)", "it": "Guasto sonda resistenza di riscaldamento (display E12)"},
        23: {"en": "ERV communication error", "it": "Errore di comunicazione con ERV"},
    },
    "waterloop": {
        0: {"en": "Room probe failure (display E1)", "it": "Guasto sonda ambiente (display E1)"},
        1: {"en": "Air exchanger probe failure (display E2)", "it": "Guasto sonda scambiatore aria (display E2)"},
        2: {"en": "Water outlet probe failure (display E3)", "it": "Guasto sonda acqua uscita (display E3)"},
        3: {"en": "Water exchanger probe failure (display E4)", "it": "Guasto sonda scambiatore acqua (display E4)"},
        4: {"en": "Indoor fan fault (display E5)", "it": "Guasto ventilatore interno (display E5)"},
        5: {"en": "Water inlet probe failure (display E6)", "it": "Guasto sonda acqua ingresso (display E6)"},
        6: {"en": "Inverter driver communication fault (display E7)", "it": "Guasto comunicazione driver inverter (display E7)"},
        7: {"en": "Discharge temperature probe failure (display E8)", "it": "Guasto sonda temperatura di scarico (display E8)"},
        8: {"en": "Remote function error (display F1)", "it": "Errore funzione remota (display F1)"},
        10: {"en": "Presence contact open (display F3)", "it": "Contatto presenza aperto (display F3)"},
        11: {"en": "Inverter fault (display F4)", "it": "Guasto inverter (display F4)"},
        13: {"en": "No water outlet flow detected (display F6)", "it": "Nessun flusso acqua in uscita rilevato (display F6)"},
        15: {"en": "Low refrigerant or 4-way valve fault (display F8)", "it": "Basso refrigerante o guasto valvola a 4 vie (display F8)"},
        16: {"en": "Compressor mismatch error (display E10)", "it": "Errore incompatibilita compressore (display E10)"},
        17: {"en": "Vortex failure (display E11)", "it": "Guasto vortex (display E11)"},
    },
    "yardy": {
        0: {"en": "Water probe error", "it": "Errore sonda acqua"},
        1: {"en": "Control board air probe error", "it": "Errore sonda aria su scheda di controllo"},
        2: {"en": "External alarm (display E06)", "it": "Allarme esterno (display E06)"},
        8: {"en": "Remote off active", "it": "Remote off attivo"},
    },
}

# Node kind -> alarm family. Waterloop units report as "ac" too; their bit layout is nearly identical.
KIND_TO_FAMILY = {"ac": "two_point_zero", "fancoil": "fancoil", "thermostat": "m7"}


def describe_alarms(kind: str, bitmask: int | None, lang: str = "en") -> list[str]:
    """Human readable list of the alarms set in ``bitmask`` for a node kind."""
    if not bitmask:
        return []
    table = ALARM_DESCRIPTIONS.get(KIND_TO_FAMILY.get(kind, ""), {})
    out: list[str] = []
    for bit in range(64):
        if bitmask & (1 << bit):
            entry = table.get(bit)
            out.append(entry.get(lang, entry["en"]) if entry else f"Alarm {bit}")
    return out
