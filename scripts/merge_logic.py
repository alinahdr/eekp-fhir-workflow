import copy
import json
import requests
from datetime import datetime, timezone

HAPI_BASE_URL = "http://localhost:8080/fhir"

HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json"
}

SVNR_SYSTEM = "urn:oid:1.2.40.0.10.1.4.3.1"

# The Questionnaire ID is the same as the chapter name.
CHAPTER_TO_QUESTIONNAIRE = {
    "schwangerschaft": "schwangerschaft",
    "labor": "labor",
    "aufnahme": "aufnahme"
}


def print_line(title: str) -> None:
    """Print a visible section header in the console output."""
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pretty_print(data: dict) -> None:
    """Print JSON data in a readable format."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def get_questionnaire_info(chapter_name: str) -> dict:
    """
    Resolve the Questionnaire configuration for the given chapter name.
    The Questionnaire ID is expected to match the chapter name.
    """
    chapter_name = chapter_name.lower()
    questionnaire_id = CHAPTER_TO_QUESTIONNAIRE.get(chapter_name)

    if not questionnaire_id:
        raise ValueError(f"Unknown chapter: {chapter_name}")

    return {
        "id": questionnaire_id,
        "url_hapi": f"{HAPI_BASE_URL}/Questionnaire/{questionnaire_id}"
    }


def build_qr_id(chapter_name: str, svnr: str) -> str:
    """
    Build the fixed QuestionnaireResponse ID.

    Format:
    <chapter-name>-<SVNR>

    Example:
    schwangerschaft-1234567890
    """
    return f"{chapter_name.lower()}-{svnr}"


def build_incoming_qr(svnr: str, chapter_name: str, field_name: str, answer_dict: dict) -> dict:
    """
    Build a minimal incoming QuestionnaireResponse from raw input values.

    This function is used to convert simple input parameters
    (chapter, field, answer, patient identifier) into a FHIR-like structure
    that can then be merged with an existing QuestionnaireResponse.
    """
    questionnaire_info = get_questionnaire_info(chapter_name)

    return {
        "resourceType": "QuestionnaireResponse",
        "questionnaire": questionnaire_info["url_hapi"],
        "identifier": [
            {
                "system": SVNR_SYSTEM,
                "value": svnr
            }
        ],
        "item": [
            {
                "linkId": "basic-group",
                "item": [
                    {
                        "linkId": field_name,
                        "answer": [answer_dict]
                    }
                ]
            }
        ]
    }


def search_patient_by_svnr(svnr: str) -> dict | None:
    """
    Search the HAPI server for a Patient by SVNR.
    Return the Patient resource if found, otherwise None.
    """
    response = requests.get(
        f"{HAPI_BASE_URL}/Patient",
        params={"identifier": f"{SVNR_SYSTEM}|{svnr}"},
        headers=HEADERS,
        timeout=30
    )

    print(f"[{response.status_code}] GET Patient by SVNR")
    print(f"Search URL: {response.url}")

    if response.status_code != 200:
        print(response.text)
        return None

    entries = response.json().get("entry", [])
    return entries[0]["resource"] if entries else None


def get_existing_qr(qr_id: str) -> dict | None:
    """
    Read an existing QuestionnaireResponse directly by its fixed ID.

    This supports the design decision that there is exactly one
    QuestionnaireResponse per patient and chapter.
    """
    response = requests.get(
        f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}",
        headers=HEADERS,
        timeout=30
    )

    print(f"[{response.status_code}] GET QuestionnaireResponse/{qr_id}")

    if response.status_code == 404:
        return None

    if response.status_code != 200:
        print(response.text)
        return None

    return response.json()


def ensure_basic_group(qr: dict) -> dict:
    """
    Ensure that the QuestionnaireResponse contains a 'basic-group'.

    If the group does not exist, it is created.
    The function returns the group object so it can be updated directly.
    """
    if "item" not in qr or not qr["item"]:
        qr["item"] = [{"linkId": "basic-group", "item": []}]
        return qr["item"][0]

    for group in qr["item"]:
        if group.get("linkId") == "basic-group":
            group.setdefault("item", [])
            return group

    new_group = {"linkId": "basic-group", "item": []}
    qr["item"].append(new_group)
    return new_group


def merge_questionnaire_responses(existing_qr: dict, incoming_qr: dict) -> dict:
    """
    Merge the incoming QuestionnaireResponse into the existing one.

    Rules:
    - If a field already exists, its answer is overwritten.
    - If a field does not exist, it is added.
    - Only items inside 'basic-group' are processed here.
    """
    merged_qr = copy.deepcopy(existing_qr)

    existing_group = ensure_basic_group(merged_qr)
    incoming_group = ensure_basic_group(incoming_qr)

    existing_items = {
        item.get("linkId"): item
        for item in existing_group["item"]
        if item.get("linkId")
    }

    for incoming_item in incoming_group["item"]:
        link_id = incoming_item.get("linkId")
        if not link_id:
            continue

        if link_id in existing_items:
            existing_items[link_id]["answer"] = copy.deepcopy(incoming_item.get("answer", []))
            print(f"→ Field '{link_id}' overwritten")
        else:
            existing_group["item"].append(copy.deepcopy(incoming_item))
            print(f"→ Field '{link_id}' added")

    return merged_qr


def prepare_qr_for_save(
    qr: dict,
    patient_ref: str,
    svnr: str,
    questionnaire_url_hapi: str,
    qr_id: str
) -> dict:
    """
    Prepare the final QuestionnaireResponse before saving it to HAPI.

    This function normalizes the resource and sets the required fields:
    - id
    - questionnaire reference
    - subject
    - status
    - identifier
    - authored
    """
    new_qr = copy.deepcopy(qr)

    new_qr["resourceType"] = "QuestionnaireResponse"
    new_qr["id"] = qr_id
    new_qr["questionnaire"] = questionnaire_url_hapi
    new_qr["status"] = "completed"
    new_qr["subject"] = {"reference": patient_ref}
    new_qr["identifier"] = [
        {
            "system": SVNR_SYSTEM,
            "value": svnr
        }
    ]
    new_qr["authored"] = now_iso()

    ensure_basic_group(new_qr)

    # Remove server-managed metadata before saving.
    if "meta" in new_qr:
        del new_qr["meta"]

    return new_qr


def save_qr(qr: dict, qr_id: str) -> str | None:
    """
    Save the QuestionnaireResponse to HAPI using PUT on the fixed ID.

    Repeated saves to the same ID update the same logical resource.
    HAPI stores technical versions in the background.
    """
    response = requests.put(
        f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}",
        headers=HEADERS,
        json=qr,
        timeout=30
    )

    print(f"[{response.status_code}] PUT QuestionnaireResponse/{qr_id}")

    if not response.ok:
        print(response.text)
        return None

    return f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}?_format=json"


def process_input(
    svnr: str,
    chapter_name: str,
    field_name: str,
    answer_dict: dict
) -> str | None:
    """
    Process one input value for one patient and one chapter.

    Workflow:
    1. Resolve the Questionnaire from the chapter name
    2. Search the patient by SVNR
    3. Build the fixed QuestionnaireResponse ID
    4. Read the existing QuestionnaireResponse by ID
    5. If it exists, merge the new field into it
    6. If it does not exist, create a new QuestionnaireResponse
    7. Normalize the final resource
    8. Save it back to HAPI with PUT
    """
    print_line("1. Resolve chapter to Questionnaire")
    questionnaire_info = get_questionnaire_info(chapter_name)
    questionnaire_url_hapi = questionnaire_info["url_hapi"]

    print(f"Chapter: {chapter_name}")
    print(f"Questionnaire: {questionnaire_url_hapi}")

    print_line("2. Search patient by SVNR")
    patient = search_patient_by_svnr(svnr)
    if not patient:
        print("No patient found.")
        return None

    patient_ref = f"Patient/{patient['id']}"
    print(f"Patient found: {patient_ref}")

    print_line("3. Build fixed QuestionnaireResponse ID")
    qr_id = build_qr_id(chapter_name, svnr)
    print(f"QuestionnaireResponse ID: {qr_id}")

    print_line("4. Build incoming QuestionnaireResponse")
    incoming_qr = build_incoming_qr(svnr, chapter_name, field_name, answer_dict)
    pretty_print(incoming_qr)

    print_line("5. Read existing QuestionnaireResponse")
    existing_qr = get_existing_qr(qr_id)

    if existing_qr:
        print("Existing QuestionnaireResponse found. Start merge.")
        merged_qr = merge_questionnaire_responses(existing_qr, incoming_qr)
        final_qr = prepare_qr_for_save(
            qr=merged_qr,
            patient_ref=patient_ref,
            svnr=svnr,
            questionnaire_url_hapi=questionnaire_url_hapi,
            qr_id=qr_id
        )
    else:
        print("No existing QuestionnaireResponse found. Create a new one.")
        final_qr = prepare_qr_for_save(
            qr=incoming_qr,
            patient_ref=patient_ref,
            svnr=svnr,
            questionnaire_url_hapi=questionnaire_url_hapi,
            qr_id=qr_id
        )

    print_line("6. Final QuestionnaireResponse")
    pretty_print(final_qr)

    print_line("7. Save QuestionnaireResponse")
    link = save_qr(final_qr, qr_id)

    if link:
        print(f"Saved: {link}")

    return link


if __name__ == "__main__":

    print("\n=== TEST 1: Erstes Feld setzen (SSW) ===")
    process_input(
        svnr="1234567890",
        chapter_name="schwangerschaft",
        field_name="ssw",
        answer_dict={"valueInteger": 32}
    )

    print("\n=== TEST 2: Zweites Feld hinzufügen (Gewicht) ===")
    process_input(
        svnr="1234567890",
        chapter_name="schwangerschaft",
        field_name="gewicht",
        answer_dict={"valueDecimal": 68.5}
    )

    print("\n=== TEST 3: Drittes Feld hinzufügen (Entbindungstermin) ===")
    process_input(
        svnr="1234567890",
        chapter_name="schwangerschaft",
        field_name="entbindungstermin",
        answer_dict={"valueDate": "2026-07-15"}
    )

    print("\n=== TEST 4: Feld überschreiben (Gewicht ändern) ===")
    process_input(
        svnr="1234567890",
        chapter_name="schwangerschaft",
        field_name="gewicht",
        answer_dict={"valueDecimal": 70.2}
    )