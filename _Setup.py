import requests

HAPI_BASE_URL = "http://localhost:8080/fhir"
FORMSLAB_BASE_URL = "https://fhir.forms-lab.com"

HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json"
}

SVNR_SYSTEM = "urn:oid:1.2.40.0.10.1.4.3.1"

KAPITEL = "mutter-anamnese"
PATIENT_ID = "test-patient-1"
SVNR = "1234567890"

QUESTIONNAIRE_ID = KAPITEL
QUESTIONNAIRE_RESPONSE_ID = f"{KAPITEL}-{SVNR}"


def put(base_url: str, resource: str, resource_id: str, body: dict) -> None:
    """
    Create or update a FHIR resource on the target server
    and print the result for verification.
    """
    url = f"{base_url}/{resource}/{resource_id}"

    put_response = requests.put(
        url,
        json=body,
        headers=HEADERS,
        timeout=30
    )

    get_response = requests.get(url, headers=HEADERS, timeout=30)

    print(f"{base_url} -> {resource} {resource_id}")
    print(f"PUT:  {put_response.status_code}")
    print(f"GET:  {get_response.status_code}")
    print(f"Link: {url}")
    print("-" * 70)


questionnaire_body = {
    "resourceType": "Questionnaire",
    "id": QUESTIONNAIRE_ID,
    "url": f"{FORMSLAB_BASE_URL}/Questionnaire/{QUESTIONNAIRE_ID}",
    "status": "active",
    "title": "Mother anamnesis follow-up",
    "text": {
        "status": "generated",
        "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Mother anamnesis questionnaire</div>"
    },
    "extension": [
        {
            "url": "http://hl7.org/fhir/uv/sdc/StructureDefinition/sdc-questionnaire-launchContext",
            "extension": [
                {
                    "url": "name",
                    "valueCoding": {
                        "system": "http://hl7.org/fhir/uv/sdc/CodeSystem/launchContext",
                        "code": "previousResponse"
                    }
                },
                {
                    "url": "type",
                    "valueCode": "QuestionnaireResponse"
                },
                {
                    "url": "description",
                    "valueString": "Previous QuestionnaireResponse used for prefilling follow-up data"
                }
            ]
        }
    ],
    "item": [
        {
            "linkId": "basic-group",
            "text": "Mother anamnesis data",
            "type": "group",
            "item": [
                {
                    "linkId": "ssw",
                    "text": "Pregnancy week",
                    "type": "integer",
                    "extension": [
                        {
                            "url": "http://hl7.org/fhir/uv/sdc/StructureDefinition/sdc-questionnaire-initialExpression",
                            "valueExpression": {
                                "language": "text/fhirpath",
                                "expression": "%previousResponse.item.where(linkId='basic-group').item.where(linkId='ssw').answer.first().value"
                            }
                        }
                    ]
                },
                {
                    "linkId": "entbindungstermin",
                    "text": "Expected delivery date",
                    "type": "date",
                    "extension": [
                        {
                            "url": "http://hl7.org/fhir/uv/sdc/StructureDefinition/sdc-questionnaire-initialExpression",
                            "valueExpression": {
                                "language": "text/fhirpath",
                                "expression": "%previousResponse.item.where(linkId='basic-group').item.where(linkId='entbindungstermin').answer.first().value"
                            }
                        }
                    ]
                }
            ]
        }
    ]
}

patient_body = {
    "resourceType": "Patient",
    "id": PATIENT_ID,
    "text": {
        "status": "generated",
        "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Anna Mustermann</div>"
    },
    "identifier": [
        {
            "system": SVNR_SYSTEM,
            "value": SVNR
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
}

qr_body = {
    "resourceType": "QuestionnaireResponse",
    "id": QUESTIONNAIRE_RESPONSE_ID,
    "text": {
        "status": "generated",
        "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Mother anamnesis response</div>"
    },
    "questionnaire": f"{HAPI_BASE_URL}/Questionnaire/{QUESTIONNAIRE_ID}",
    "status": "completed",
    "subject": {
        "reference": f"Patient/{PATIENT_ID}"
    },
    "identifier": [
        {
            "system": SVNR_SYSTEM,
            "value": SVNR
        }
    ],
    "item": [
        {
            "linkId": "basic-group",
            "text": "Mother anamnesis data",
            "item": [
                {
                    "linkId": "ssw",
                    "text": "Pregnancy week",
                    "answer": [
                        {
                            "valueInteger": 27
                        }
                    ]
                },
                {
                    "linkId": "entbindungstermin",
                    "text": "Expected delivery date",
                    "answer": [
                        {
                            "valueDate": "2026-07-12"
                        }
                    ]
                }
            ]
        }
    ]
}

# Upload the Questionnaire to both servers.
# forms-lab needs it for $populate, HAPI stores the local reference.
put(HAPI_BASE_URL, "Questionnaire", QUESTIONNAIRE_ID, {
    **questionnaire_body,
    "url": f"{HAPI_BASE_URL}/Questionnaire/{QUESTIONNAIRE_ID}"
})
put(FORMSLAB_BASE_URL, "Questionnaire", QUESTIONNAIRE_ID, questionnaire_body)

# Patient and QuestionnaireResponse are stored on HAPI.
put(HAPI_BASE_URL, "Patient", PATIENT_ID, patient_body)
put(HAPI_BASE_URL, "QuestionnaireResponse", QUESTIONNAIRE_RESPONSE_ID, qr_body)