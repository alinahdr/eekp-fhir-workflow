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

CHAPTER_TO_QUESTIONNAIRE = {
    "schwangerschaft": "kapitel-schwangerschaft",
    "labor": "kapitel-labor",
    "aufnahme": "kapitel-aufnahme"
}


def print_line(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pretty_print(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def get_questionnaire_info(chapter_name: str) -> dict:
    questionnaire_id = CHAPTER_TO_QUESTIONNAIRE.get(chapter_name.lower())
    if not questionnaire_id:
        raise ValueError(f"Unknown chapter: {chapter_name}")

    return {
        "id": questionnaire_id,
        "url_hapi": f"{HAPI_BASE_URL}/Questionnaire/{questionnaire_id}"
    }


def build_qr_id(questionnaire_url_hapi: str, svnr: str) -> str:
    kapitelname = questionnaire_url_hapi.rstrip("/").split("/")[-1]
    return f"{kapitelname}-{svnr}"


def build_incoming_qr(svnr: str, chapter_name: str, field_name: str, answer_dict: dict) -> dict:
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


def extract_svnr(incoming_qr: dict) -> str | None:
    identifiers = incoming_qr.get("identifier", [])

    if isinstance(identifiers, dict):
        identifiers = [identifiers]

    for identifier in identifiers:
        if identifier.get("system") == SVNR_SYSTEM:
            return identifier.get("value")

    return None


def search_patient_by_svnr(svnr: str) -> dict | None:
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


def search_latest_qr(patient_id: str, questionnaire_url_hapi: str) -> dict | None:
    response = requests.get(
        f"{HAPI_BASE_URL}/QuestionnaireResponse",
        params={
            "subject": f"Patient/{patient_id}",
            "questionnaire": questionnaire_url_hapi,
            "_sort": "-_lastUpdated",
            "_count": 1
        },
        headers=HEADERS,
        timeout=30
    )

    print(f"[{response.status_code}] GET latest QuestionnaireResponse")
    print(f"Search URL: {response.url}")

    if response.status_code != 200:
        print(response.text)
        return None

    entries = response.json().get("entry", [])
    return entries[0]["resource"] if entries else None


def ensure_basic_group(qr: dict) -> dict:
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


def prepare_qr_for_save(qr: dict, patient_ref: str, svnr: str, questionnaire_url_hapi: str, qr_id: str) -> dict:
    new_qr = copy.deepcopy(qr)

    new_qr["resourceType"] = "QuestionnaireResponse"
    new_qr["id"] = qr_id
    new_qr["questionnaire"] = questionnaire_url_hapi
    new_qr["status"] = "completed"
    new_qr["subject"] = {"reference": patient_ref}

    # R4: QuestionnaireResponse.identifier = object, not array
    new_qr["identifier"] = {
        "system": SVNR_SYSTEM,
        "value": svnr
    }

    new_qr["authored"] = now_iso()
    ensure_basic_group(new_qr)

    if "meta" in new_qr:
        del new_qr["meta"]

    return new_qr


def save_qr(qr: dict, qr_id: str) -> str | None:
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


def process(incoming_qr: dict, label: str) -> str | None:
    print_line(f"TEST CASE: {label}")
    print("Incoming QR:")
    pretty_print(incoming_qr)

    svnr = extract_svnr(incoming_qr)
    questionnaire_url_hapi = incoming_qr.get("questionnaire")

    if not svnr:
        print("No SVNR found in incoming QR.")
        return None

    if not questionnaire_url_hapi:
        print("No questionnaire reference found in incoming QR.")
        return None

    print_line("1. Search patient by SVNR")
    patient = search_patient_by_svnr(svnr)
    if not patient:
        print("No patient found.")
        return None

    patient_ref = f"Patient/{patient['id']}"
    print(f"Patient found: {patient_ref}")

    print_line("2. Search latest QR for patient + questionnaire")
    existing_qr = search_latest_qr(patient["id"], questionnaire_url_hapi)

    qr_id = build_qr_id(questionnaire_url_hapi, svnr)

    if existing_qr:
        print("Existing QR found. Merge incoming QR into the existing QR.")
        merged_qr = merge_questionnaire_responses(existing_qr, incoming_qr)
        final_qr = prepare_qr_for_save(
            qr=merged_qr,
            patient_ref=patient_ref,
            svnr=svnr,
            questionnaire_url_hapi=questionnaire_url_hapi,
            qr_id=qr_id
        )
    else:
        print("No existing QR found. Create a new QR.")
        final_qr = prepare_qr_for_save(
            qr=incoming_qr,
            patient_ref=patient_ref,
            svnr=svnr,
            questionnaire_url_hapi=questionnaire_url_hapi,
            qr_id=qr_id
        )

    print_line("3. Final QR")
    pretty_print(final_qr)

    print_line("4. Save QuestionnaireResponse")
    link = save_qr(final_qr, qr_id)

    if link:
        print(f"Saved: {link}")

    return link


if __name__ == "__main__":
    print_line("MERGE WORKFLOW TEST START")

    incoming_qr_existing = build_incoming_qr(
        svnr="1234567890",
        chapter_name="schwangerschaft",
        field_name="gewicht",
        answer_dict={"valueDecimal": 68.5}
    )
    link_existing = process(
        incoming_qr=incoming_qr_existing,
        label="schwangerschaft-update"
    )

    incoming_qr_overwrite = build_incoming_qr(
        svnr="1234567890",
        chapter_name="schwangerschaft",
        field_name="gewicht",
        answer_dict={"valueDecimal": 70.2}
    )
    link_overwrite = process(
        incoming_qr=incoming_qr_overwrite,
        label="schwangerschaft-overwrite"
    )

    incoming_qr_new = build_incoming_qr(
        svnr="1234567890",
        chapter_name="labor",
        field_name="hb",
        answer_dict={"valueDecimal": 12.4}
    )
    link_new = process(
        incoming_qr=incoming_qr_new,
        label="labor-neu"
    )

    print_line("SUMMARY")
    print(f"Pregnancy QR:           {link_existing}")
    print(f"Pregnancy QR overwrite: {link_overwrite}")
    print(f"Labor QR:               {link_new}")