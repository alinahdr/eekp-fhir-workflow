import requests
from _StoreLogicTest import process_input

HAPI_BASE_URL = "http://localhost:8080/fhir"

SVNR = "1234567890"
KAPITEL = "mutter-anamnese"
QR_ID = f"{KAPITEL}-{SVNR}"


def get_qr(qr_id):
    response = requests.get(f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}")
    if response.status_code != 200:
        return None
    return response.json()


def get_group_items(qr):
    """Return items inside basic-group."""
    for group in qr.get("item", []):
        if group.get("linkId") == "basic-group":
            return group.get("item", [])
    return []


def test_ssw():
    process_input(SVNR, KAPITEL, "ssw", {"valueInteger": 30})
    qr = get_qr(QR_ID)

    assert qr is not None

    items = get_group_items(qr)

    assert any(
        item["linkId"] == "ssw" and item["answer"][0]["valueInteger"] == 30
        for item in items
    )


def test_add_entbindungstermin():
    process_input(SVNR, KAPITEL, "entbindungstermin", {"valueDate": "2026-07-20"})
    qr = get_qr(QR_ID)

    assert qr is not None

    items = get_group_items(qr)

    assert any(
        item["linkId"] == "entbindungstermin"
        and item["answer"][0]["valueDate"] == "2026-07-20"
        for item in items
    )


def test_update_ssw():
    process_input(SVNR, KAPITEL, "ssw", {"valueInteger": 32})
    qr = get_qr(QR_ID)

    assert qr is not None

    items = get_group_items(qr)

    assert any(
        item["linkId"] == "ssw" and item["answer"][0]["valueInteger"] == 32
        for item in items
    )


def test_patient_not_found():
    missing_svnr = "0000000000"
    missing_qr_id = f"{KAPITEL}-{missing_svnr}"

    process_input(missing_svnr, KAPITEL, "ssw", {"valueInteger": 25})

    qr = get_qr(missing_qr_id)

    assert qr is None