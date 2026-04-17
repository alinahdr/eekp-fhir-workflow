import requests

HAPI_BASE_URL = "http://localhost:8080/fhir"

HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json"
}

SVNR_SYSTEM = "urn:oid:1.2.40.0.10.1.4.3.1"


def put(resource: str, resource_id: str, body: dict) -> None:
    url = f"{HAPI_BASE_URL}/{resource}/{resource_id}"

    put_response = requests.put(
        url,
        json=body,
        headers=HEADERS,
        timeout=30
    )

    get_response = requests.get(url, headers=HEADERS, timeout=30)

    print(f"{resource} {resource_id}")
    print(f"PUT:  {put_response.status_code}")
    print(f"GET:  {get_response.status_code}")
    print(f"Link: {url}")
    print("-" * 70)


put("Questionnaire", "kapitel-schwangerschaft", {
    "resourceType": "Questionnaire",
    "id": "kapitel-schwangerschaft",
    "url": f"{HAPI_BASE_URL}/Questionnaire/kapitel-schwangerschaft",
    "status": "active",
    "text": {
        "status": "generated",
        "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Fragebogen Schwangerschaft</div>"
    },
    "item": [
        {
            "linkId": "basic-group",
            "text": "Schwangerschaftsdaten",
            "type": "group",
            "item": [
                {
                    "linkId": "ssw",
                    "text": "Schwangerschaftswoche",
                    "type": "integer"
                },
                {
                    "linkId": "entbindungstermin",
                    "text": "Entbindungstermin",
                    "type": "date"
                }
            ]
        }
    ]
})

put("Patient", "test-patient-1", {
    "resourceType": "Patient",
    "id": "test-patient-1",
    "text": {
        "status": "generated",
        "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Anna Mustermann</div>"
    },
    "identifier": [
        {
            "system": SVNR_SYSTEM,
            "value": "1234567890"
        }
    ],
    "name": [
        {
            "use": "official",
            "family": "Mustermann",
            "given": ["Anna"]
        }
    ],
    "gender": "female",
    "birthDate": "1995-05-10"
})

put("QuestionnaireResponse", "kapitel-schwangerschaft-1234567890", {
    "resourceType": "QuestionnaireResponse",
    "id": "kapitel-schwangerschaft-1234567890",
    "text": {
        "status": "generated",
        "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Antwort Schwangerschaft</div>"
    },
    "questionnaire": f"{HAPI_BASE_URL}/Questionnaire/kapitel-schwangerschaft",
    "status": "completed",
    "subject": {
        "reference": "Patient/test-patient-1"
    },
    "identifier": {
        "system": SVNR_SYSTEM,
        "value": "1234567890"
    },
    "item": [
        {
            "linkId": "basic-group",
            "item": [
                {
                    "linkId": "ssw",
                    "answer": [
                        {"valueInteger": 27}
                    ]
                },
                {
                    "linkId": "entbindungstermin",
                    "answer": [
                        {"valueDate": "2026-07-12"}
                    ]
                }
            ]
        }
    ]
})