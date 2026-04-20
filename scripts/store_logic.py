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

SVNR_SYSTEM = "urn:oid:1.2.40.0.10.1.4.3.1"

QUESTIONNAIRE_MAP = {
    "mutter-anamnese": {
        "id": "mutter-anamnese",
        "url_hapi": f"{HAPI_BASE_URL}/Questionnaire/mutter-anamnese",
        "url_formslab": f"{FORMSLAB_BASE_URL}/Questionnaire/mutter-anamnese"
    }
}


# ---------------------------
# Helper functions
# ---------------------------

def print_line(title):
    """Print a visible section header in the console output."""
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def now_iso():
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pretty_print(data):
    """Print JSON data in a readable format."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def get_questionnaire_info(kapitel):
    """Return the Questionnaire configuration for a given chapter."""
    info = QUESTIONNAIRE_MAP.get(kapitel)
    if not info:
        raise ValueError(f"No Questionnaire mapping found for chapter '{kapitel}'.")
    return info


def build_qr_id(kapitel, svnr):
    """
    Build the fixed QuestionnaireResponse ID.
    Format: <chapter-name>-<SVNR>
    """
    return f"{kapitel}-{svnr}"


# ---------------------------
# HAPI: Patient search
# ---------------------------

def search_patient_by_svnr(svnr):
    """Search the HAPI server for a patient by SVNR."""
    url = f"{HAPI_BASE_URL}/Patient?identifier={SVNR_SYSTEM}|{svnr}"
    response = requests.get(url, headers=HEADERS, timeout=30)

    print("Search URL:", url)
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
# HAPI: Search current QR by fixed ID
# ---------------------------

def get_existing_qr(qr_id):
    """Read the current QuestionnaireResponse by fixed ID."""
    url = f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}"
    response = requests.get(url, headers=HEADERS, timeout=30)

    print(f"[{response.status_code}] GET QuestionnaireResponse/{qr_id}")

    if response.status_code == 404:
        return None

    if response.status_code != 200:
        print(response.text)
        return None

    return response.json()


# ---------------------------
# HAPI: Read history
# ---------------------------

def get_qr_history(qr_id):
    """Read the technical version history of one QuestionnaireResponse."""
    url = f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}/_history"
    response = requests.get(url, headers=HEADERS, timeout=30)

    print(f"[{response.status_code}] GET QuestionnaireResponse/{qr_id}/_history")

    if response.status_code != 200:
        print(response.text)
        return []

    bundle = response.json()
    entries = bundle.get("entry", [])
    history = []

    for entry in entries:
        resource = entry.get("resource", {})
        meta = resource.get("meta", {})
        history.append({
            "versionId": meta.get("versionId", ""),
            "lastUpdated": meta.get("lastUpdated", ""),
            "authored": resource.get("authored", "")
        })

    return history


# ---------------------------
# forms-lab: Populate
# ---------------------------

def populate_from_previous(questionnaire_id, previous_response):
    """
    Call forms-lab $populate and pass the previous response
    as launch context so values can be prefilled.
    """
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

    populated_qr = response.json()

    print_line("Populate result from forms-lab")
    pretty_print(populated_qr)

    return populated_qr


# ---------------------------
# QR manipulation
# ---------------------------

def ensure_basic_group(qr):
    """
    Ensure that the QuestionnaireResponse contains the expected group.
    Return the group object.
    """
    if "item" not in qr or not qr["item"]:
        qr["item"] = [{
            "linkId": "basic-group",
            "text": "Mother anamnesis data",
            "item": []
        }]
        return qr["item"][0]

    for group in qr["item"]:
        if group.get("linkId") == "basic-group":
            if "item" not in group:
                group["item"] = []
            return group

    new_group = {
        "linkId": "basic-group",
        "text": "Mother anamnesis data",
        "item": []
    }
    qr["item"].append(new_group)
    return new_group


def set_or_add_answer(group_items, link_id, answer_dict):
    """
    Update an existing answer if the linkId already exists.
    Otherwise add a new item with the given answer.
    """
    for item in group_items:
        if item.get("linkId") == link_id:
            item["answer"] = [answer_dict]
            return

    group_items.append({
        "linkId": link_id,
        "answer": [answer_dict]
    })


def create_new_qr(questionnaire_url_hapi, patient_ref, svnr):
    """Create a new QuestionnaireResponse with grouped item structure."""
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
                "text": "Mother anamnesis data",
                "item": []
            }
        ]
    }


def prepare_next_qr(base_qr, questionnaire_url_hapi, patient_ref, svnr):
    """
    Normalize a populated QuestionnaireResponse before saving it to HAPI.
    Remove server-managed fields and set the current metadata.
    """
    if "id" in base_qr:
        del base_qr["id"]

    if "meta" in base_qr:
        del base_qr["meta"]

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

    ensure_basic_group(base_qr)
    return base_qr


# ---------------------------
# HAPI: Save QR with fixed ID
# ---------------------------

def save_qr_to_hapi(qr, qr_id):
    """
    Save the QuestionnaireResponse with a fixed ID.
    Repeated PUT requests create new technical versions on the server.
    """
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

    try:
        saved = response.json()
        version_id = saved.get("meta", {}).get("versionId", "")
        if version_id:
            print(f"Stored new version: {version_id}")
    except Exception:
        pass

    return True


# ---------------------------
# Main business logic
# ---------------------------

def process_input(svnr, kapitel, dek_field, answer_dict):
    """
    Process one input value for a patient and chapter.

    Workflow:
    1. Resolve the Questionnaire for the chapter
    2. Find the patient by SVNR
    3. Look for an existing QuestionnaireResponse by fixed ID
    4. If one exists, prefill via forms-lab $populate
    5. Update or add the requested answer
    6. Save the QuestionnaireResponse back to HAPI
    7. Print the technical history from HAPI
    """
    print_line("1. Chapter to Questionnaire")
    questionnaire_info = get_questionnaire_info(kapitel)

    questionnaire_id = questionnaire_info["id"]
    questionnaire_url_hapi = questionnaire_info["url_hapi"]

    print(f"Chapter: {kapitel}")
    print(f"Questionnaire ID: {questionnaire_id}")

    print_line("2. Search patient by SVNR on HAPI")
    patient = search_patient_by_svnr(svnr)

    if not patient:
        print("No patient found for this SVNR.")
        return

    patient_id = patient["id"]
    patient_ref = f"Patient/{patient_id}"
    qr_id = build_qr_id(kapitel, svnr)

    print(f"Patient found: {patient_ref}")
    print(f"Fixed QuestionnaireResponse ID: {qr_id}")

    print_line("3. Search existing QuestionnaireResponse on HAPI")
    existing_qr = get_existing_qr(qr_id)

    if existing_qr:
        print("Existing QuestionnaireResponse found, starting forms-lab $populate")
        new_qr = populate_from_previous(questionnaire_id, existing_qr)

        if not new_qr:
            print("$populate failed, using the existing QuestionnaireResponse as base")
            new_qr = existing_qr

        new_qr = prepare_next_qr(new_qr, questionnaire_url_hapi, patient_ref, svnr)
    else:
        print("No QuestionnaireResponse found, creating a new one")
        new_qr = create_new_qr(questionnaire_url_hapi, patient_ref, svnr)

    print_line("4. Add or update DEK field")
    basic_group = ensure_basic_group(new_qr)
    set_or_add_answer(basic_group["item"], dek_field, answer_dict)
    pretty_print(new_qr)

    print_line("5. Save QuestionnaireResponse to HAPI")
    success = save_qr_to_hapi(new_qr, qr_id)

    if success:
        print("QuestionnaireResponse saved successfully.")

    print_line("6. Show technical history")
    history = get_qr_history(qr_id)

    if not history:
        print("No history found.")
        return

    for version in history:
        print(
            f"versionId={version['versionId']} | "
            f"lastUpdated={version['lastUpdated']} | "
            f"authored={version['authored']}"
        )


# ---------------------------
# Example calls
# ---------------------------

if __name__ == "__main__":
    process_input(
        svnr="1234567890",
        kapitel="mutter-anamnese",
        dek_field="ssw",
        answer_dict={"valueInteger": 32}
    )

    process_input(
        svnr="1234567890",
        kapitel="mutter-anamnese",
        dek_field="entbindungstermin",
        answer_dict={"valueDate": "2026-07-15"}
    )