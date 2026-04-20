# FHIR QuestionnaireResponse Workflow

**Version:** 1.0 · **Standard:** HL7 FHIR R4 · **Sprache:** Python 3.10+

> Prototypische Implementierung zur strukturierten Verarbeitung medizinischer Fragebogendaten im Kontext des elektronischen Eltern-Kind-Passes (e-EKP) der Oberösterreichischen Gesundheitsholding (OÖG).

---

## Inhaltsverzeichnis

1. [Hintergrund & Motivation](#1-hintergrund--motivation)
2. [Was dieses Projekt macht](#2-was-dieses-projekt-macht)
3. [Systemarchitektur](#3-systemarchitektur)
4. [Wichtige FHIR-Konzepte](#4-wichtige-fhir-konzepte)
5. [Datenmodell](#5-datenmodell)
6. [Modul 1 – MergeLogic](#6-modul-1--mergelogic)
7. [Modul 2 – StoreLogic](#7-modul-2--storelogic)
8. [Vergleich der beiden Module](#8-vergleich-der-beiden-module)
9. [Hilfsskripte](#9-hilfsskripte)
10. [Voraussetzungen & Installation](#10-voraussetzungen--installation)
11. [Ausführungsreihenfolge](#11-ausführungsreihenfolge)
12. [Ressourcen-ID-Strategie](#12-ressourcen-id-strategie)
13. [Zentrale Erkenntnisse](#13-zentrale-erkenntnisse)
14. [Hinweis zu Testdaten](#14-hinweis-zu-testdaten)

---

## 1. Hintergrund & Motivation

Der elektronische Eltern-Kind-Pass (e-EKP) ist ein digitales Vorsorgedokument, das medizinische Untersuchungen rund um Schwangerschaft und frühe Kindheit strukturiert erfasst. Die OÖG setzt dabei auf den internationalen Standard **HL7 FHIR R4**, um Daten interoperabel und maschinenlesbar zu speichern.

Eine besondere Herausforderung ist die **wiederholte Datenerfassung**: Schwangerschaftsdaten wie Gewicht oder Schwangerschaftswoche ändern sich laufend. Das System muss diese Änderungen effizient und nachvollziehbar verwalten, ohne dabei Datenverlust oder unkontrolliertes Datenwachstum zu verursachen.

Dieses Projekt untersucht und implementiert zwei verschiedene Strategien dafür.

---

## 2. Was dieses Projekt macht

Das System empfängt strukturierte Eingabedaten in folgender Form:

| Parameter | FHIR-Feld | Beispiel | Beschreibung |
|---|---|---|---|
| `svnr` | `identifier.value` | `1234567890` | Sozialversicherungsnummer des Patienten |
| `kapitel` | `questionnaire` | `schwangerschaft` | Kapitelname, z. B. für einen Fragebogen |
| `dek_field` | `item[].linkId` | `gewicht` | Name des Felds innerhalb des Fragebogens |
| `answer_dict` | `item[].answer[]` | `{"valueDecimal": 68.5}` | Typisierter FHIR-Antwortwert |

Aus diesen Parametern wird eine FHIR-`QuestionnaireResponse` erstellt oder aktualisiert und auf einem HAPI FHIR Server gespeichert.

---

## 3. Systemarchitektur

Das System nutzt zwei Server:

| Komponente | URL | Rolle |
|---|---|---|
| HAPI FHIR Server | `http://localhost:8080/fhir` | Speicherung aller FHIR-Ressourcen, Versionierung |
| forms-lab | `https://fhir.forms-lab.com` | Externer SDC-Server für `$populate` (Vorbefüllung) |

```
Eingabe (svnr, kapitel, feld, wert)
        │
        ▼
   ┌─────────────┐
   │  Python     │──── GET Patient ──────────────────► HAPI FHIR
   │  Anwendung  │──── GET/PUT QuestionnaireResponse ► HAPI FHIR
   │             │──── POST $populate ───────────────► forms-lab
   └─────────────┘
```

> **Warum zwei Server?**
> HAPI FHIR unterstützt den SDC-Standard (`$populate`) nicht vollständig. forms-lab übernimmt diese Rolle als externer SDC-Server. HAPI bleibt der primäre Datenspeicher.

---

## 4. Wichtige FHIR-Konzepte

### Questionnaire
Definiert die **Struktur** eines Fragebogens: Felder, Typen, Gruppen. Entspricht einem leeren Formular.

### QuestionnaireResponse
Speichert die **ausgefüllten Antworten** eines Patienten zu einem Questionnaire. Entspricht dem ausgefüllten Formular.

### $populate (SDC)
Eine FHIR-Operation, die eine neue, leere `QuestionnaireResponse` automatisch mit Werten aus einer vorherigen Response **vorbefüllt**. Dafür werden FHIRPath-Ausdrücke im Questionnaire hinterlegt.

### HAPI Versionierung
HAPI FHIR speichert bei jedem `PUT` auf dieselbe Ressourcen-ID automatisch eine neue technische Version. Die vollständige Historie ist abrufbar unter:
```
GET /QuestionnaireResponse/<id>/_history
```

---

## 5. Datenmodell

Alle `QuestionnaireResponse`-Ressourcen folgen einer einheitlichen Struktur mit einem `basic-group`-Container:

```json
{
  "resourceType": "QuestionnaireResponse",
  "id": "schwangerschaft-1234567890",
  "questionnaire": "http://localhost:8080/fhir/Questionnaire/schwangerschaft",
  "status": "completed",
  "subject": { "reference": "Patient/test-patient-1" },
  "identifier": { "system": "urn:oid:1.2.40.0.10.1.4.3.1", "value": "1234567890" },
  "authored": "2026-04-20T10:00:00+00:00",
  "item": [
    {
      "linkId": "basic-group",
      "item": [
        { "linkId": "ssw", "answer": [{ "valueInteger": 32 }] },
        { "linkId": "gewicht", "answer": [{ "valueDecimal": 68.5 }] }
      ]
    }
  ]
}
```

**Warum `basic-group`?**
- Einheitliche Struktur über alle Kapitel hinweg
- Ermöglicht stabiles Mergen einzelner Felder
- Kompatibel mit `$populate` (FHIRPath-Ausdrücke greifen auf diese Struktur zu)
- Voraussetzung für zuverlässige Weiterverarbeitung

---

## 6. Modul 1 – MergeLogic

**Datei:** `merge_logic.py`

### Konzept: Idempotentes Upsert

MergeLogic hält **genau eine `QuestionnaireResponse` pro Patient und Kapitel** mit einer festen, deterministischen ID. Neue Feldwerte werden direkt in die bestehende Ressource eingemergt.

### Feste ID
```
<kapitel>-<SVNR>
Beispiel: schwangerschaft-1234567890
```

### Workflow

```
1. Kapitel → Questionnaire-URL auflösen
2. Patient per SVNR auf HAPI suchen
3. Feste QR-ID generieren
4. Bestehende QR per ID laden (GET)
      │
      ├─ QR vorhanden → Felder zusammenführen (Merge)
      └─ Keine QR → Neue leere QR erstellen
      │
5. Normalisierung (Metadaten setzen, meta entfernen)
6. PUT auf feste ID → HAPI speichert neue Version
```

### Merge-Regeln

| Situation | Verhalten |
|---|---|
| `linkId` existiert bereits | Antwort wird **überschrieben** |
| `linkId` ist neu | Element wird **angehängt** |

### Versionierung

Da immer auf dieselbe ID geschrieben wird, legt HAPI automatisch Versionen an:

```
GET /QuestionnaireResponse/schwangerschaft-1234567890/_history
→ versionId 1 (erster Eintrag)
→ versionId 2 (nach erstem Update)
→ versionId 3 (nach zweitem Update)
```

### Sequenzdiagramm

```
Eingabe
  │
  ▼
GET Patient (SVNR)
  │
  ▼
GET QuestionnaireResponse/<id>
  │
  ├─ gefunden ──► Merge incoming fields into existing QR
  └─ nicht gefunden ──► Neue QR erstellen
  │
  ▼
PUT QuestionnaireResponse/<id>
  │
  ▼
HAPI speichert neue Version automatisch
```

---

## 7. Modul 2 – StoreLogic

**Datei:** `store_logic.py`

### Konzept: SDC-basierte Vorbefüllung + HAPI Versionierung

StoreLogic verwendet denselben festen ID-Ansatz wie MergeLogic, aber die Vorbefüllung der neuen Response erfolgt über den externen SDC-Server **forms-lab** mittels `$populate`.

### Unterschied zu MergeLogic

Der wesentliche Unterschied liegt in **wie** die neue Response erzeugt wird:

| Aspekt | MergeLogic | StoreLogic |
|---|---|---|
| Vorbefüllung | Manuelles Mergen (lokal, in Python) | `$populate` auf forms-lab (extern, SDC-basiert) |
| Externe Abhängigkeit | Keine | forms-lab muss erreichbar sein |
| Fallback bei Fehler | Nicht notwendig | Fallback auf bestehende QR |

### Workflow

```
1. Kapitel → Questionnaire auflösen
2. Patient per SVNR suchen
3. Feste QR-ID generieren (<kapitel>-<SVNR>)
4. Bestehende QR laden
      │
      ├─ QR vorhanden → POST $populate auf forms-lab
      │                  → Fehler: bestehende QR als Base verwenden
      └─ Keine QR → Neue leere QR erstellen
      │
5. DEK-Feld setzen oder aktualisieren
6. PUT auf feste ID → HAPI speichert neue Version
7. History ausgeben (zur Verifikation)
```

### Warum `$populate`?

`$populate` nutzt FHIRPath-Ausdrücke, die im Questionnaire hinterlegt sind, um Werte aus einer vorherigen Response automatisch in die neue zu übertragen. Das ist besonders relevant, wenn das Formular komplexere Felder oder Berechnungen enthält.

---

## 8. Vergleich der beiden Module

| Aspekt | MergeLogic | StoreLogic |
|---|---|---|
| ID-Schema | `<kapitel>-<SVNR>` | `<kapitel>-<SVNR>` |
| Vorbefüllung | Lokal (Python Merge) | Extern (`$populate` via forms-lab) |
| Externe Abhängigkeit | Keine | forms-lab |
| Robustheit | Hoch (vollständig lokal) | Mittel (Fallback vorhanden) |
| Kontrolle über Merge | Vollständig | Teilweise (SDC übernimmt) |
| Versionierung | HAPI automatisch | HAPI automatisch |
| Anwendungsfall | Direktes Feldupdate | SDC-gestützte Formularlogik |

> **Fazit:** Beide Module schreiben auf dieselbe feste ID und nutzen HAPIs eingebaute Versionierung. StoreLogic ist im Kern MergeLogic mit einer zusätzlichen externen `$populate`-Operation.

---

## 9. Hilfsskripte

### `setup.py`
Initialisiert den HAPI FHIR Server mit Testdaten:
- Lädt den **Questionnaire** auf HAPI und forms-lab hoch
- Legt einen Demo-**Patienten** an (Anna Mustermann, SVNR `1234567890`)
- Erstellt eine initiale **QuestionnaireResponse** mit Beispielwerten

Muss **vor** dem ersten Testlauf ausgeführt werden.

### `cleanUp.py`
Löscht alle `QuestionnaireResponse`-Ressourcen vom HAPI Server. Nach Testläufen verwenden, um einen sauberen Ausgangszustand wiederherzustellen.

---

## 10. Voraussetzungen & Installation

| Anforderung | Detail |
|---|---|
| Python | 3.10 oder neuer |
| Abhängigkeit | `pip install requests` |
| HAPI FHIR Server | Lokal via Docker auf Port `8080` |
| Internetzugang | Erforderlich für forms-lab (`$populate`) |

**HAPI FHIR lokal starten:**
```bash
docker run -p 8080:8080 hapiproject/hapi:latest
```

---

## 11. Ausführungsreihenfolge

```bash
# 1. Abhängigkeiten installieren
pip install requests

# 2. HAPI FHIR Server starten (Docker)
docker run -p 8080:8080 hapiproject/hapi:latest

# 3. Testdaten initialisieren
python setup.py

# 4. MergeLogic testen (idempotentes Upsert)
python merge_logic.py

# 5. StoreLogic testen (SDC-basierte Vorbefüllung)
python store_logic.py

# 6. QuestionnaireResponses bereinigen (optional)
python cleanUp.py
```

---

## 12. Ressourcen-ID-Strategie

| Ressource | ID-Schema | Beispiel |
|---|---|---|
| `Questionnaire` | `<kapitelname>` | `schwangerschaft` |
| `QuestionnaireResponse` | `<kapitelname>-<SVNR>` | `schwangerschaft-1234567890` |

Die feste, deterministische ID ist der Kern beider Module. Sie ermöglicht:
- Direktes Laden ohne Suche
- Idempotentes Überschreiben
- Automatische HAPI-Versionierung auf einer einzigen logischen Ressource

---

## 13. Zentrale Erkenntnisse

- **FHIR bietet eingebaute Versionierung** — eine neue Resource pro Änderung ist nicht notwendig
- **PUT + feste ID** ist die effizienteste Lösung für wiederholte Updates
- **`$populate` ergänzt, ersetzt aber keine Merge-Logik** — bei komplexen Feldern sinnvoll, bei einfachen Feldupdates unnötig
- **HAPI unterstützt SDC nicht vollständig** — forms-lab als externer SDC-Server ist der pragmatische Workaround

---

## 14. Hinweis zu Testdaten

Alle in diesem Repository verwendeten Patientendaten, Identifikatoren und klinischen Werte sind **synthetische Demodaten**, die ausschließlich für Entwicklungs- und Testzwecke erstellt wurden. Diese Implementierung ist nicht für den Produktiveinsatz oder den klinischen Betrieb validiert.
