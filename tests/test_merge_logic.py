from scripts.merge_logic import merge_questionnaire_responses


def build_qr(fields: dict):
    """Helper: erstellt eine einfache QR mit basic-group"""
    items = []
    for key, value in fields.items():
        items.append({
            "linkId": key,
            "answer": [value]
        })

    return {
        "resourceType": "QuestionnaireResponse",
        "item": [
            {
                "linkId": "basic-group",
                "item": items
            }
        ]
    }


def test_add_new_field():
    existing = build_qr({"ssw": {"valueInteger": 32}})
    incoming = build_qr({"gewicht": {"valueDecimal": 68.5}})

    result = merge_questionnaire_responses(existing, incoming)

    items = result["item"][0]["item"]
    link_ids = [i["linkId"] for i in items]

    assert "ssw" in link_ids
    assert "gewicht" in link_ids


def test_overwrite_field():
    existing = build_qr({"gewicht": {"valueDecimal": 68.5}})
    incoming = build_qr({"gewicht": {"valueDecimal": 70.2}})

    result = merge_questionnaire_responses(existing, incoming)

    items = result["item"][0]["item"]

    gewicht = next(i for i in items if i["linkId"] == "gewicht")
    assert gewicht["answer"][0]["valueDecimal"] == 70.2


def test_merge_multiple_fields():
    existing = build_qr({"ssw": {"valueInteger": 32}})
    incoming = build_qr({
        "gewicht": {"valueDecimal": 68.5},
        "entbindungstermin": {"valueDate": "2026-07-15"}
    })

    result = merge_questionnaire_responses(existing, incoming)

    items = result["item"][0]["item"]
    link_ids = [i["linkId"] for i in items]

    assert "ssw" in link_ids
    assert "gewicht" in link_ids
    assert "entbindungstermin" in link_ids