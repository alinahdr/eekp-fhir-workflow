# FHIR QuestionnaireResponse Workflow

**Version:** 1.0  
**Standard:** HL7 FHIR R4  
**Infrastruktur:** HAPI FHIR Server (lokal) · Forms-Lab (extern)

---

## Inhaltsverzeichnis

1. [Systemarchitektur](#systemarchitektur)
2. [Ressourcen-ID-Strategie](#ressourcen-id-strategie)
3. [Modul 1 – MergeLogic](#modul-1--mergelogic)
4. [Modul 2 – StoreLogic](#modul-2--storelogic)
5. [Vergleich: MergeLogic vs. StoreLogic](#vergleich-mergelogic-vs-storelogic)
6. [Infrastruktur & Hilfsskripte](#infrastruktur--hilfsskripte)
7. [Systemvoraussetzungen](#systemvoraussetzungen)
8. [Deployment & Ausführungsreihenfolge](#deployment--ausführungsreihenfolge)
9. [Haftungsausschluss](#haftungsausschluss)

---

## Systemarchitektur

Dieses Repository demonstriert einen automatisierten Workflow zur Verarbeitung medizinischer Fragebögen auf Basis des HL7 FHIR R4 Standards. Es zeigt zwei verschiedene Strategien zur Speicherung von Patientenantworten als `QuestionnaireResponse`-Ressourcen.

Die Implementierung nutzt ein hybrides Server-Setup:

| Rolle | URL |
|---|---|
| HAPI FHIR Server (lokal) | `http://localhost:8080/fhir` |
| Forms-Lab Server (extern) | `https://fhir.forms-lab.com` |

Beide Module arbeiten mit derselben grundlegenden Eingabestruktur:

| Parameter | FHIR-Feld | Beispiel | Beschreibung |
|---|---|---|---|
| `SVNr` | `identifier.value` | `1234567890` | Patienten-Identifikator (Sozialversicherungsnummer) |
| `Kapitel` | `questionnaire` | `schwangerschaft` | Kapitelname, der einem Questionnaire zugeordnet wird |
| `DEK-Feld` | `item[].linkId` | `gewicht` | Feldbezeichner innerhalb der QuestionnaireResponse |
| `Wert` | `item[].answer[]` | `{ "valueDecimal": 68.5 }` | Typisierter FHIR-Antwortwert |

---

## Ressourcen-ID-Strategie

Das Repository folgt klaren Namenskonventionen für FHIR-Ressourcen:

| Ressource | ID-Muster | Beispiel |
|---|---|---|
| `Questionnaire` | `<kapitelname>` | `kapitel-schwangerschaft` |
| `QuestionnaireResponse` – MergeLogic | `<questionnaire-id>-<SVNR>` | `kapitel-schwangerschaft-1234567890` |
| `QuestionnaireResponse` – StoreLogic | `<kapitel>-qr-<timestamp>` | `schwangerschaft-qr-20260417143012` |

---

## Modul 1 – MergeLogic

**Datei:** `_MergeLogic.py`

### Strategie: Idempotentes Upsert

MergeLogic verwendet eine zusammenführungsbasierte Aktualisierungsstrategie. Ziel ist es, eine einzige persistente `QuestionnaireResponse` pro Patient und Fragebogen zu pflegen. Neue Werte werden in die bestehende Ressource integriert, unveränderte Daten bleiben erhalten.


### Verarbeitungsschritte

1. `Questionnaire`-Referenz aus dem Kapitelnamen auflösen
2. `Patient` anhand der `SVNr` auf dem HAPI FHIR Server suchen
3. Neueste vorhandene `QuestionnaireResponse` für Patient und Fragebogen abrufen
4. Falls eine Response existiert, eingehende Felder in die bestehende Ressource zusammenführen
5. Falls keine Response existiert, neue `QuestionnaireResponse` anlegen
6. Ergebnis via `PUT QuestionnaireResponse/<questionnaire-id>-<SVNR>` speichern

### Zusammenführungsverhalten

- Vorhandene `linkId` → Antwort wird **überschrieben**
- Neue `linkId` → Element wird **angehängt**
- Die Zusammenführung erfolgt innerhalb des `basic-group`-Containers
- Die resultierende Ressource behält eine **stabile und deterministische ID**

### Sequenzdiagramm


```mermaid
sequenceDiagram
    participant Input
    participant System
    participant HAPI

    Input->>System: Eingehende Werte (SVNR, Feld, Wert)
    System->>HAPI: GET Patient by SVNr
    HAPI-->>System: Patient
    System->>HAPI: GET neueste QuestionnaireResponse
    HAPI-->>System: QR oder leeres Ergebnis

    alt QR existiert
        System->>System: Eingehende Felder in bestehende QR zusammenführen
    else Keine QR vorhanden
        System->>System: Neue QR erstellen
    end

    System->>HAPI: PUT QuestionnaireResponse/<questionnaire-id>-<SVNR>
    HAPI-->>System: 200 OK / 201 Created

```
## Modul 2 – StoreLogic

**Datei:** `_StoreLogicTest.py`

### Strategie: Update mit Versionierung + $populate

StoreLogic verwendet eine aktualisierungsbasierte Strategie mit einer festen `QuestionnaireResponse`-ID.  
Anstatt bei jeder Ausführung eine neue Ressource zu erzeugen, wird dieselbe `QuestionnaireResponse` unter derselben ID aktualisiert.

Die Historie der Änderungen wird dabei automatisch durch den HAPI FHIR Server über die technische Versionierung (`_history`) gespeichert.

Zusätzlich wird `$populate` verwendet, um bestehende Antworten vor dem Update automatisch zu übernehmen.

---

### Verarbeitungsschritte

1. `Questionnaire`-Referenz aus dem Kapitelnamen auflösen  
2. `Patient` anhand der `SVNr` suchen  
3. Bestehende `QuestionnaireResponse` über feste ID abrufen:  
   `<kapitel>-<SVNR>`  
4. Falls eine Response existiert → `$populate` auf Forms-Lab aufrufen  
5. Falls keine Response existiert → neue leere QR erstellen  
6. `basic-group` sicherstellen  
7. DEK-Feld setzen oder aktualisieren  
8. QR via `PUT QuestionnaireResponse/<kapitel>-<SVNR>` speichern  

---

### Verhalten

- Vorhandene Werte bleiben erhalten (durch `$populate`)  
- Geänderte Felder werden überschrieben  
- Neue Felder werden ergänzt  
- Die ID bleibt konstant  
- Änderungen werden als Versionen in `_history` gespeichert  

---

### Sequenzdiagramm
```mermaid
sequenceDiagram
    participant Input
    participant System
    participant FormsLab
    participant HAPI

    Input->>System: Eingehende Werte (SVNR, Feld, Wert)

    System->>HAPI: GET Patient?identifier=SVNR
    HAPI-->>System: Patient

    System->>HAPI: GET QuestionnaireResponse/<kapitel>-<SVNR>
    
    alt QR vorhanden (200)
        HAPI-->>System: Existing QR
        System->>FormsLab: POST $populate (previousResponse)
        FormsLab-->>System: Prefilled QR
    else Keine QR (404)
        HAPI-->>System: Not Found
        System->>System: Neue QR erstellen
    end

    System->>System: Feld in basic-group setzen/aktualisieren

    System->>HAPI: PUT QuestionnaireResponse/<kapitel>-<SVNR>
    HAPI-->>System: 200 OK (neue Version)

    System->>HAPI: GET _history
    HAPI-->>System: Versionen
```

## Hinweis

Alle in diesem Repository verwendeten Patientendaten, Identifikatoren und klinischen Werte sind synthetische Demodaten, die ausschließlich für Entwicklungs- und Testzwecke erstellt wurden. Diese Implementierung ist nicht für den Produktiveinsatz oder den klinischen Betrieb validiert.