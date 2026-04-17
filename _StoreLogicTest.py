import json
import requests
from datetime import datetime, timezone

# ---------------------------
# Configuration
# ---------------------------

HAPI_BASE_URL = "http://localhost:8080/fhir"
FORMSLAB_BASE_URL = "https://fhir.forms-lab.com"

HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json"
}

QUESTIONNAIRE_MAP = {
    "schwangerschaft": {
        "id": "schwangerschaft-followup",
        "url_hapi": f"{HAPI_BASE_URL}/Questionnaire/schwangerschaft-followup",
        "url_formslab": f"{FORMSLAB_BASE_URL}/Questionnaire/schwangerschaft-followup"
    }
}

SVNR_SYSTEM = "urn:oid:1.2.40.0.10.1.4.3.1"


# ---------------------------
# Helpers
# ---------------------------

def print_line(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pretty_print(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def get_questionnaire_info(kapitel):
    info = QUESTIONNAIRE_MAP.get(kapitel)
    if not info:
        raise ValueError(f"Kein Questionnaire-Mapping für Kapitel '{kapitel}' gefunden.")
    return info


# ---------------------------
# HAPI: Patient search
# ---------------------------

def search_patient_by_svnr(svnr):
    url = f"{HAPI_BASE_URL}/Patient?identifier={SVNR_SYSTEM}|{svnr}"
    response = requests.get(url, headers=HEADERS, timeout=30)
    print("Such-URL:", url)

    print(f"[{response.status_code}] GET Patient by SVNR")

    if response.status_code != 200:
        print(response.text)
        return None

    bundle = response.json()
    entries = bundle.get("entry", [])

    if not entries:
        return None

    return entries[0]["resource"]


# ---------------------------
# HAPI: Search latest QR
# ---------------------------

def search_latest_qr(patient_id, questionnaire_url_hapi):
    url = (
        f"{HAPI_BASE_URL}/QuestionnaireResponse"
        f"?subject=Patient/{patient_id}"
        f"&questionnaire={questionnaire_url_hapi}"
        f"&_sort=-authored"
        f"&_count=1"
    )

    response = requests.get(url, headers=HEADERS, timeout=30)
    print(f"[{response.status_code}] GET latest QuestionnaireResponse")

    if response.status_code != 200:
        print(response.text)
        return None

    bundle = response.json()
    entries = bundle.get("entry", [])

    if not entries:
        return None

    return entries[0]["resource"]


# ---------------------------
# forms-lab: Populate
# ---------------------------

def populate_from_previous(questionnaire_id, previous_response):
    response = requests.post(
        f"{FORMSLAB_BASE_URL}/Questionnaire/{questionnaire_id}/$populate",
        headers=HEADERS,
        json={
            "resourceType": "Parameters",
            "parameter": [
                {
                    "name": "context",
                    "part": [
                        {"name": "name", "valueString": "previousResponse"},
                        {"name": "content", "resource": previous_response}
                    ]
                }
            ]
        },
        timeout=30
    )

    print(f"[{response.status_code}] POST $populate")

    if response.status_code != 200:
        print(response.text)
        return None

    return response.json()


# ---------------------------
# QR manipulation
# ---------------------------

def ensure_basic_group(qr):
    if "item" not in qr or not qr["item"]:
        qr["item"] = [{"linkId": "basic-group", "item": []}]
        return qr["item"][0]

    for group in qr["item"]:
        if group.get("linkId") == "basic-group":
            if "item" not in group:
                group["item"] = []
            return group

    new_group = {"linkId": "basic-group", "item": []}
    qr["item"].append(new_group)
    return new_group


def set_or_add_answer(group_items, link_id, answer_dict):
    for item in group_items:
        if item.get("linkId") == link_id:
            item["answer"] = [answer_dict]
            return

    group_items.append({
        "linkId": link_id,
        "answer": [answer_dict]
    })


def create_new_qr(questionnaire_url_hapi, patient_ref, svnr):
    return {
        "resourceType": "QuestionnaireResponse",
        "questionnaire": questionnaire_url_hapi,
        "status": "completed",
        "subject": {
            "reference": patient_ref
        },
        "identifier": [
            {
                "system": SVNR_SYSTEM,
                "value": svnr
            }
        ],
        "authored": now_iso(),
        "item": [
            {
                "linkId": "basic-group",
                "item": []
            }
        ]
    }


def prepare_next_qr(base_qr, questionnaire_url_hapi, patient_ref, svnr):
    base_qr["resourceType"] = "QuestionnaireResponse"
    base_qr["questionnaire"] = questionnaire_url_hapi
    base_qr["status"] = "completed"
    base_qr["subject"] = {
        "reference": patient_ref
    }
    base_qr["identifier"] = [
        {
            "system": SVNR_SYSTEM,
            "value": svnr
        }
    ]
    base_qr["authored"] = now_iso()

    if "id" in base_qr:
        del base_qr["id"]

    return base_qr


# ---------------------------
# HAPI: Save QR
# ---------------------------

def build_new_qr_id(kapitel):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{kapitel}-qr-{timestamp}"


def save_qr_to_hapi(qr, qr_id):
    qr["id"] = qr_id

    response = requests.put(
        f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}",
        headers=HEADERS,
        json=qr,
        timeout=30
    )

    print(f"[{response.status_code}] PUT QuestionnaireResponse/{qr_id}")

    if response.status_code not in (200, 201):
        print(response.text)
        return False

    return True

# ---------------------------
# Main business logic
# ---------------------------

def process_input(svnr, kapitel, dek_field, answer_dict):
    print_line("1. Kapitel -> Questionnaire")
    questionnaire_info = get_questionnaire_info(kapitel)

    questionnaire_id = questionnaire_info["id"]
    questionnaire_url_hapi = questionnaire_info["url_hapi"]

    print(f"Kapitel: {kapitel}")
    print(f"Questionnaire ID: {questionnaire_id}")

    print_line("2. Patient über SVNR auf HAPI suchen")
    patient = search_patient_by_svnr(svnr)

    if not patient:
        print("Kein Patient mit dieser SVNR gefunden.")
        return

    patient_id = patient["id"]
    patient_ref = f"Patient/{patient_id}"
    print(f"Patient gefunden: {patient_ref}")

    print_line("3. Vorhandene QR auf HAPI suchen")
    latest_qr = search_latest_qr(patient_id, questionnaire_url_hapi)

    if latest_qr:
        print("Vorhandene QR gefunden -> forms-lab $populate")
        new_qr = populate_from_previous(questionnaire_id, latest_qr)

        if not new_qr:
            return

        new_qr = prepare_next_qr(new_qr, questionnaire_url_hapi, patient_ref, svnr)

    else:
        print("Keine QR gefunden -> neue QR erstellen")
        new_qr = create_new_qr(questionnaire_url_hapi, patient_ref, svnr)

    print_line("4. DEK-Feld ergänzen")
    basic_group = ensure_basic_group(new_qr)
    set_or_add_answer(basic_group["item"], dek_field, answer_dict)

    pretty_print(new_qr)

    print_line("5. Neue QR auf HAPI speichern")
    new_qr_id = build_new_qr_id(kapitel)
    success = save_qr_to_hapi(new_qr, new_qr_id)

    if success:
        print("QR erfolgreich gespeichert.")


# ---------------------------
# Example calls
# ---------------------------

if __name__ == "__main__":
    process_input(
        svnr="1234567890",
        kapitel="schwangerschaft",
        dek_field="ssw",
        answer_dict={"valueInteger": 32}
    )

    process_input(
        svnr="1234567890",
        kapitel="schwangerschaft",
        dek_field="gewicht",
        answer_dict={"valueDecimal": 68.5}
    )

    # process_input(
    #     svnr="1234567890",
    #     kapitel="schwangerschaft",
    #     dek_field="gewicht",
    #     answer_dict={"valueDecimal": 68.5}
    # )

    # process_input(
    #     svnr="1234567890",
    #     kapitel="schwangerschaft",
    #     dek_field="entbindungstermin",
    #     answer_dict={"valueDate": "2026-07-15"}
    # )