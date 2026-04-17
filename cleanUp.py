import requests

BASE = "http://localhost:8080/fhir"
HEADERS = {
    "Content-Type": "application/fhir+json",
    "Accept": "application/fhir+json"
}

def delete_all(resource):
    r = requests.get(f"{BASE}/{resource}", headers=HEADERS, timeout=30)
    if not r.ok:
        print(f"Could not read {resource}: {r.status_code}")
        return

    entries = r.json().get("entry", [])
    if not entries:
        print(f"No {resource} found.")
        return

    for e in entries:
        rid = e["resource"]["id"]
        link = f"{BASE}/{resource}/{rid}"

        delete_response = requests.delete(
            f"{BASE}/{resource}/{rid}",
            headers=HEADERS,
            timeout=30
        )

        if delete_response.status_code in (200, 204):
            print(f"Found & Deleted: {resource}/{rid}")
            print(f"Check: {link}")
        else:
            print(f"Failed: {resource}/{rid} [{delete_response.status_code}]")
            print(delete_response.text)


print("=== CLEANUP START ===")
delete_all("QuestionnaireResponse")
print("\n=== CLEANUP DONE ===")