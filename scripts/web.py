from flask import Flask, request, redirect, url_for, render_template_string
import json
import requests
import time
from datetime import datetime, timezone

app = Flask(__name__)

HAPI_BASE_URL = "http://localhost:8080/fhir"
FORMSLAB_BASE_URL = "https://fhir.forms-lab.com"

HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json"
}

SVNR_SYSTEM = "urn:oid:1.2.40.0.10.1.4.3.1"

QUESTIONNAIRE_ID = "schwangerschaft-followup"
QUESTIONNAIRE_URL_HAPI = f"{HAPI_BASE_URL}/Questionnaire/{QUESTIONNAIRE_ID}"
QUESTIONNAIRE_URL_FORMSLAB = f"{FORMSLAB_BASE_URL}/Questionnaire/{QUESTIONNAIRE_ID}"

questionnaire = {
    "resourceType": "Questionnaire",
    "id": QUESTIONNAIRE_ID,
    "url": QUESTIONNAIRE_URL_FORMSLAB,
    "status": "active",
    "title": "Schwangerschaft Verlauf",
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
                    "valueString": "Vorherige QuestionnaireResponse"
                }
            ]
        }
    ],
    "item": [
        {
            "linkId": "basic-group",
            "text": "Schwangerschaftsdaten",
            "type": "group",
            "item": [
                {
                    "linkId": "ssw",
                    "text": "Schwangerschaftswoche (SSW)",
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
                    "text": "Entbindungstermin",
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
                },
                {
                    "linkId": "gewicht",
                    "text": "Gewicht in kg",
                    "type": "decimal",
                    "extension": [
                        {
                            "url": "http://hl7.org/fhir/uv/sdc/StructureDefinition/sdc-questionnaire-initialExpression",
                            "valueExpression": {
                                "language": "text/fhirpath",
                                "expression": "%previousResponse.item.where(linkId='basic-group').item.where(linkId='gewicht').answer.first().value"
                            }
                        }
                    ]
                }
            ]
        }
    ]
}

app_state = {
    "setup_done": False,
    "current_form": {
        "svnr": "1234567890",
        "ssw": "",
        "entbindungstermin": "",
        "gewicht": ""
    },
    "prefilled": False,
    "message": "",
    "last_link": "",
    "patient_ref": "",
    "history": []
}


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_new_qr_id():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"schwangerschaft-qr-{timestamp}"


def put_resource(base_url, resource_type, resource_id, body):
    url = f"{base_url}/{resource_type}/{resource_id}"
    response = requests.put(url, headers=HEADERS, json=body, timeout=30)
    return response


def search_patient_by_svnr(svnr):
    url = f"{HAPI_BASE_URL}/Patient?identifier={SVNR_SYSTEM}|{svnr}"
    response = requests.get(url, headers=HEADERS, timeout=30)

    if response.status_code != 200:
        return None, f"Patientensuche fehlgeschlagen: {response.text}"

    bundle = response.json()
    entries = bundle.get("entry", [])

    if not entries:
        return None, "Kein Patient mit dieser SVNR gefunden."

    patient = entries[0]["resource"]
    return patient, None


def search_latest_qr(patient_id):
    url = (
        f"{HAPI_BASE_URL}/QuestionnaireResponse"
        f"?subject=Patient/{patient_id}"
        f"&questionnaire={QUESTIONNAIRE_URL_HAPI}"
        f"&_sort=-authored"
        f"&_count=1"
    )

    response = requests.get(url, headers=HEADERS, timeout=30)

    if response.status_code != 200:
        return None, f"QR-Suche fehlgeschlagen: {response.text}"

    bundle = response.json()
    entries = bundle.get("entry", [])

    if not entries:
        return None, None

    return entries[0]["resource"], None


def populate_from_previous(previous_response):
    response = requests.post(
        f"{FORMSLAB_BASE_URL}/Questionnaire/{QUESTIONNAIRE_ID}/$populate",
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

    if response.status_code != 200:
        return None, response.text

    return response.json(), None


def build_qr(qr_id, patient_ref, svnr, ssw, et, gewicht=None, authored=None):
    if not authored:
        authored = now_iso()

    items = [
        {"linkId": "ssw", "answer": [{"valueInteger": int(ssw)}]},
        {"linkId": "entbindungstermin", "answer": [{"valueDate": et}]}
    ]

    if gewicht not in (None, "", "None"):
        items.append({"linkId": "gewicht", "answer": [{"valueDecimal": float(gewicht)}]})

    return {
        "resourceType": "QuestionnaireResponse",
        "id": qr_id,
        "questionnaire": QUESTIONNAIRE_URL_HAPI,
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
        "authored": authored,
        "item": [
            {
                "linkId": "basic-group",
                "item": items
            }
        ]
    }


def prepare_next_qr(base_qr, patient_ref, svnr):
    if "id" in base_qr:
        del base_qr["id"]

    if "meta" in base_qr:
        del base_qr["meta"]

    base_qr["resourceType"] = "QuestionnaireResponse"
    base_qr["questionnaire"] = QUESTIONNAIRE_URL_HAPI
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

    return base_qr


def set_or_add_answer(group_items, link_id, answer_dict):
    for item in group_items:
        if item.get("linkId") == link_id:
            item["answer"] = [answer_dict]
            return

    group_items.append({
        "linkId": link_id,
        "answer": [answer_dict]
    })


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


def read_answers(qr):
    result = {
        "ssw": "",
        "entbindungstermin": "",
        "gewicht": ""
    }

    for group in qr.get("item", []):
        for item in group.get("item", []):
            link_id = item.get("linkId")
            answer = item.get("answer", [{}])[0]

            if link_id == "ssw":
                result["ssw"] = answer.get("valueInteger", "")
            elif link_id == "entbindungstermin":
                result["entbindungstermin"] = answer.get("valueDate", "")
            elif link_id == "gewicht":
                result["gewicht"] = answer.get("valueDecimal", "")

    return result


def load_history_from_hapi(patient_id):
    url = (
        f"{HAPI_BASE_URL}/QuestionnaireResponse"
        f"?subject=Patient/{patient_id}"
        f"&questionnaire={QUESTIONNAIRE_URL_HAPI}"
        f"&_sort=-authored"
        f"&_count=20"
    )

    response = requests.get(url, headers=HEADERS, timeout=30)

    if response.status_code != 200:
        return []

    bundle = response.json()
    entries = bundle.get("entry", [])
    history = []

    for entry in entries:
        qr = entry["resource"]
        answers = read_answers(qr)
        qr_id = qr.get("id", "unknown")
        history.append({
            "id": qr_id,
            "ssw": answers["ssw"],
            "entbindungstermin": answers["entbindungstermin"],
            "gewicht": answers["gewicht"],
            "authored": qr.get("authored", ""),
            "link": f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}"
        })

    return history


TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Schwangerschaft Verlauf</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f6f7fb;
            margin: 0;
            padding: 30px;
        }
        .card {
            max-width: 760px;
            margin: auto;
            background: white;
            border-radius: 14px;
            padding: 28px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.08);
        }
        h1 { margin-top: 0; }
        .info {
            padding: 12px;
            border-radius: 8px;
            background: #eef4ff;
            margin-bottom: 18px;
        }
        .success {
            padding: 12px;
            border-radius: 8px;
            background: #eaf8ee;
            margin-bottom: 18px;
        }
        .row { margin-bottom: 16px; }
        label {
            display: block;
            margin-bottom: 6px;
            font-weight: bold;
        }
        input {
            width: 100%;
            padding: 10px;
            border: 1px solid #ccd3e0;
            border-radius: 8px;
            font-size: 14px;
        }
        .btn-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 20px;
        }
        button, a.btn {
            background: #2d6cdf;
            color: white;
            border: none;
            padding: 10px 16px;
            border-radius: 8px;
            text-decoration: none;
            cursor: pointer;
            font-size: 14px;
            display: inline-block;
        }
        a.btn.secondary {
            background: #7d8aa5;
        }
        a.btn.light {
            background: #4e9e74;
        }
        .responses {
            margin-top: 28px;
        }
        .response-box {
            border: 1px solid #e2e6ef;
            border-radius: 10px;
            padding: 12px;
            margin-bottom: 10px;
            background: #fafbfe;
        }
        .small {
            color: #666;
            font-size: 13px;
        }
        .link-box {
            margin-top: 10px;
            margin-bottom: 18px;
        }
        .link-box a {
            color: #2d6cdf;
            text-decoration: none;
            font-weight: bold;
            word-break: break-all;
        }
        .link-box a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>Schwangerschaft Verlauf</h1>

        {% if message %}
            <div class="{{ 'success' if success else 'info' }}">{{ message }}</div>
        {% endif %}

        {% if last_link %}
            <div class="link-box">
                🔗 <a href="{{ last_link }}" target="_blank">Gespeicherte Response öffnen</a><br>
                <span class="small">{{ last_link }}</span>
            </div>
        {% endif %}

        <div class="small">
            <strong>Setup:</strong> {{ "fertig" if setup_done else "noch nicht durchgeführt" }}<br>
            <strong>Patient:</strong> {{ patient_ref if patient_ref else "noch nicht gesucht" }}<br>
            <strong>Responses gefunden:</strong> {{ history|length }}
        </div>

        <div class="btn-row" style="margin-bottom: 24px;">
            <a href="/setup" class="btn">Setup durchführen</a>
            <a href="/reopen" class="btn light">Mit $populate wieder öffnen</a>
            <a href="/reset" class="btn secondary">Reset</a>
        </div>

        <form method="post" action="/save">
            <div class="row">
                <label>SVNR</label>
                <input type="text" name="svnr" value="{{ form_data.svnr }}" required>
            </div>

            <div class="row">
                <label>Schwangerschaftswoche (SSW)</label>
                <input type="number" name="ssw" value="{{ form_data.ssw }}" required>
            </div>

            <div class="row">
                <label>Entbindungstermin</label>
                <input type="date" name="entbindungstermin" value="{{ form_data.entbindungstermin }}" required>
            </div>

            <div class="row">
                <label>Gewicht in kg</label>
                <input type="number" step="0.1" name="gewicht" value="{{ form_data.gewicht }}">
            </div>

            <button type="submit">Response speichern</button>
        </form>

        <div class="responses">
            <h3>Responses auf HAPI</h3>
            {% if history %}
                {% for r in history %}
                    <div class="response-box">
                        <strong>{{ r.id }}</strong><br>
                        SSW: {{ r.ssw }}<br>
                        ET: {{ r.entbindungstermin }}<br>
                        Gewicht: {{ r.gewicht if r.gewicht != '' else '—' }}<br>
                        <span class="small">authored: {{ r.authored }}</span><br>
                        <a href="{{ r.link }}" target="_blank" class="small">Response öffnen</a>
                    </div>
                {% endfor %}
            {% else %}
                <div class="small">Noch keine Responses gefunden.</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        TEMPLATE,
        setup_done=app_state["setup_done"],
        history=app_state["history"],
        form_data=app_state["current_form"],
        message=app_state["message"],
        success=app_state["prefilled"] is False,
        last_link=app_state["last_link"],
        patient_ref=app_state["patient_ref"]
    )


@app.route("/setup")
def setup():
    r1 = put_resource(FORMSLAB_BASE_URL, "Questionnaire", QUESTIONNAIRE_ID, questionnaire)
    r2 = put_resource(HAPI_BASE_URL, "Questionnaire", QUESTIONNAIRE_ID, {
        **questionnaire,
        "url": QUESTIONNAIRE_URL_HAPI
    })

    if r1.status_code in (200, 201) and r2.status_code in (200, 201):
        app_state["setup_done"] = True
        app_state["message"] = "Questionnaire wurde auf forms-lab und HAPI gespeichert."
    else:
        try:
            app_state["message"] = (
                f"forms-lab: {r1.status_code}\\n{r1.text}\\n\\n"
                f"HAPI: {r2.status_code}\\n{r2.text}"
            )
        except Exception:
            app_state["message"] = "Setup fehlgeschlagen."

    time.sleep(1)
    return redirect(url_for("index"))


@app.route("/save", methods=["POST"])
def save():
    if not app_state["setup_done"]:
        app_state["message"] = "Bitte zuerst Setup durchführen."
        return redirect(url_for("index"))

    svnr = request.form.get("svnr", "").strip()
    ssw = request.form.get("ssw", "").strip()
    et = request.form.get("entbindungstermin", "").strip()
    gewicht = request.form.get("gewicht", "").strip()

    app_state["current_form"] = {
        "svnr": svnr,
        "ssw": ssw,
        "entbindungstermin": et,
        "gewicht": gewicht
    }

    patient, error = search_patient_by_svnr(svnr)
    if error:
        app_state["message"] = error
        return redirect(url_for("index"))

    patient_id = patient["id"]
    patient_ref = f"Patient/{patient_id}"
    app_state["patient_ref"] = patient_ref

    qr_id = build_new_qr_id()
    response_link = f"{HAPI_BASE_URL}/QuestionnaireResponse/{qr_id}"

    qr = build_qr(qr_id, patient_ref, svnr, ssw, et, gewicht)

    r = put_resource(HAPI_BASE_URL, "QuestionnaireResponse", qr_id, qr)

    if r.status_code in (200, 201):
        app_state["history"] = load_history_from_hapi(patient_id)
        app_state["message"] = f"{qr_id} wurde auf HAPI gespeichert."
        app_state["prefilled"] = False
        app_state["last_link"] = response_link
    else:
        try:
            app_state["message"] = json.dumps(r.json(), indent=2, ensure_ascii=False)
        except Exception:
            app_state["message"] = r.text
        app_state["last_link"] = ""

    return redirect(url_for("index"))


@app.route("/reopen")
def reopen():
    svnr = app_state["current_form"]["svnr"].strip()

    if not svnr:
        app_state["message"] = "Bitte zuerst eine SVNR eingeben."
        return redirect(url_for("index"))

    patient, error = search_patient_by_svnr(svnr)
    if error:
        app_state["message"] = error
        return redirect(url_for("index"))

    patient_id = patient["id"]
    patient_ref = f"Patient/{patient_id}"
    app_state["patient_ref"] = patient_ref

    latest_qr, error = search_latest_qr(patient_id)
    if error:
        app_state["message"] = error
        return redirect(url_for("index"))

    if not latest_qr:
        app_state["message"] = "Keine vorherige Response auf HAPI vorhanden."
        app_state["history"] = []
        return redirect(url_for("index"))

    populated_qr, error = populate_from_previous(latest_qr)
    if error:
        app_state["message"] = error
        return redirect(url_for("index"))

    answers = read_answers(populated_qr)
    app_state["current_form"] = {
        "svnr": svnr,
        "ssw": str(answers["ssw"]),
        "entbindungstermin": answers["entbindungstermin"],
        "gewicht": str(answers["gewicht"]) if answers["gewicht"] != "" else ""
    }
    app_state["history"] = load_history_from_hapi(patient_id)
    app_state["prefilled"] = True
    app_state["message"] = "Formular wurde mit $populate aus der letzten HAPI-Response vorbefüllt."

    return redirect(url_for("index"))


@app.route("/reset")
def reset():
    app_state["setup_done"] = False
    app_state["current_form"] = {
        "svnr": "1234567890",
        "ssw": "",
        "entbindungstermin": "",
        "gewicht": ""
    }
    app_state["prefilled"] = False
    app_state["message"] = "Zurückgesetzt."
    app_state["last_link"] = ""
    app_state["patient_ref"] = ""
    app_state["history"] = []
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)