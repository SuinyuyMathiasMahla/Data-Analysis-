"""Personal and client projects: the client's details, and the client's name in the report."""
from app.reports.renderers import _cover_rows
from tests.conftest import auth_headers, make_project

CLIENT = {"client_name": "Mbah Consulting", "client_email": "Contact@Mbah.example", "client_whatsapp": "+237 677-00-00-00"}


def _report_content(client, h, pid: int) -> dict:
    report = client.post(f"/api/projects/{pid}/reports", headers=h, json={"format": "docx"})
    assert report.status_code == 201, report.text
    version = report.json()["latest_version"]["version_number"]
    response = client.get(f"/api/reports/{report.json()['id']}/versions/{version}/content", headers=h)
    assert response.status_code == 200, response.text
    return response.json()


def test_personal_project_keeps_no_client_details(client):
    h = auth_headers(client, "personal@example.org")
    project = make_project(client, h, client_name="Ignored", client_whatsapp="237677000000")
    assert project["project_type"] == "personal"
    assert project["client_name"] is None and project["client_email"] is None and project["client_whatsapp"] is None


def test_client_project_needs_name_email_and_whatsapp(client):
    h = auth_headers(client, "missing@example.org")
    no_number = client.post("/api/projects", headers=h, json={"title": "Client survey", "academic_level": "masters",
                                                            "project_type": "client", "client_name": "Mbah Consulting",
                                                            "client_email": "contact@mbah.example"})
    assert no_number.status_code == 400 and "WhatsApp" in no_number.json()["error"]["message"]
    bad_email = client.post("/api/projects", headers=h, json={"title": "Client survey", "academic_level": "masters",
                                                            "project_type": "client", **CLIENT, "client_email": "not-an-email"})
    assert bad_email.status_code == 400 and "e-mail" in bad_email.json()["error"]["message"]


def test_client_whatsapp_is_stored_as_digits_with_country_code(client):
    h = auth_headers(client, "whatsapp@example.org")
    project = make_project(client, h, project_type="client", **CLIENT)
    assert project["project_type"] == "client"
    assert project["client_name"] == "Mbah Consulting"
    assert project["client_email"] == "contact@mbah.example"
    assert project["client_whatsapp"] == "237677000000"


def test_project_type_is_fixed_after_creation(client):
    h = auth_headers(client, "fixed@example.org")
    project = make_project(client, h, project_type="client", **CLIENT)
    response = client.put(f"/api/projects/{project['id']}", headers=h, json={"project_type": "personal"})
    assert response.status_code == 400 and "cannot be changed" in response.json()["error"]["message"]


def test_client_details_can_be_edited_and_are_validated(client):
    h = auth_headers(client, "edit@example.org")
    project = make_project(client, h, project_type="client", **CLIENT)
    edited = client.put(f"/api/projects/{project['id']}", headers=h,
                        json={"client_whatsapp": "+256 700 111 222", "client_name": "Mbah Consulting Ltd"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["client_whatsapp"] == "256700111222"
    assert edited.json()["client_name"] == "Mbah Consulting Ltd"
    refused = client.put(f"/api/projects/{project['id']}", headers=h, json={"client_whatsapp": "call me"})
    assert refused.status_code == 400


def test_report_is_addressed_to_the_client(client):
    h = auth_headers(client, "report@example.org", "Ada Researcher")
    client_project = make_project(client, h, project_type="client", **CLIENT)
    content = _report_content(client, h, client_project["id"])
    assert content["project"]["researcher"] == "Mbah Consulting"
    assert content["project"]["researcher_label"] == "Client"
    assert ("Client", "Mbah Consulting") in _cover_rows(content)

    personal = make_project(client, h, title="Personal thesis project")
    content = _report_content(client, h, personal["id"])
    assert content["project"]["researcher"] == "Ada Researcher"
    assert content["project"]["researcher_label"] == "Researcher"


def test_report_details_appear_in_the_background_references_and_ethics(client):
    from app.reports.renderers import _section_blocks

    h = auth_headers(client, "details@example.org", "Ada Researcher")
    project = make_project(client, h, title="Plain English report study")
    saved = client.put(f"/api/projects/{project['id']}/report-details", headers=h, json={
        "background": "Earlier studies found that sleep affects grades.\n\nFew studies used local data.",
        "references": ["  Smith, J. (2020). Sleep and grades. Journal of Learning, 12(3), 1-10.  ", "   "],
        "ethics_committee": "Faculty Ethics Committee", "ethics_reference": "FEC/2026/014, 3 March 2026",
        "consent_method": "Written informed consent",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["references"] == ["Smith, J. (2020). Sleep and grades. Journal of Learning, 12(3), 1-10."]
    assert client.get(f"/api/projects/{project['id']}/report-details", headers=h).json()["ethics_reference"] == "FEC/2026/014, 3 March 2026"

    content = _report_content(client, h, project["id"])
    background = [p for kind, p in _section_blocks(content, "background") if kind == "p"]
    assert "Earlier studies found that sleep affects grades." in background and "Few studies used local data." in background
    references = [p for kind, p in _section_blocks(content, "references") if kind == "bullet"]
    assert references == ["Smith, J. (2020). Sleep and grades. Journal of Learning, 12(3), 1-10."]
    methods_text = " ".join(str(p) for _, p in _section_blocks(content, "methods"))
    assert "FEC/2026/014" in methods_text and "Written informed consent" in methods_text


def test_empty_report_details_are_flagged_not_invented(client):
    from app.reports.renderers import _section_blocks

    h = auth_headers(client, "empty.details@example.org")
    project = make_project(client, h)
    content = _report_content(client, h, project["id"])
    notes = [p for kind, p in _section_blocks(content, "references") if kind == "note"]
    assert any("No sources have been entered" in note for note in notes)
    assert any("literature review has not been entered" in str(p) for _, p in _section_blocks(content, "background"))


def test_title_page_names_the_supervisor(client):
    from tests.conftest import grant_role

    owner = auth_headers(client, "owner.sup@example.org", "Ada Researcher")
    auth_headers(client, "supervisor.sup@example.org", "Grace Supervisor")
    grant_role("supervisor.sup@example.org", "supervisor")
    project = make_project(client, owner)
    added = client.post(f"/api/projects/{project['id']}/members", headers=owner,
                        json={"email": "supervisor.sup@example.org", "member_role": "supervisor"})
    assert added.status_code == 201, added.text
    content = _report_content(client, owner, project["id"])
    assert content["project"]["supervisors"] == ["Grace Supervisor"]
    assert ("Supervisor", "Grace Supervisor") in _cover_rows(content)


def test_approximate_costs_are_totalled_listed_and_removed_with_the_project(client):
    h = auth_headers(client, "costs@example.org")
    project = make_project(client, h, title="Costed study")
    saved = client.put(f"/api/projects/{project['id']}/costs", headers=h, json={"currency": "XAF", "items": [
        {"description": "Printing 200 questionnaires", "category": "Printing and binding", "amount": 12500},
        {"description": "Transport to schools", "category": "Travel", "amount": 7500.5},
    ]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["total"] == 20000.5 and saved.json()["currency"] == "XAF"
    listed = [p for p in client.get("/api/projects", headers=h).json()["projects"] if p["id"] == project["id"]][0]
    assert listed["approximate_cost"] == 20000.5 and listed["cost_currency"] == "XAF"
    invalid = client.put(f"/api/projects/{project['id']}/costs", headers=h, json={"items": [{"description": "Bad", "amount": -5}]})
    assert invalid.status_code == 422
    deleted = client.delete(f"/api/projects/{project['id']}", headers=h)
    assert deleted.status_code == 200
    from app.services import project_costs
    from app.services.storage import get_storage
    assert not get_storage().exists(project_costs.storage_key(project["id"]))


def test_a_local_number_with_a_leading_zero_is_refused(client):
    h = auth_headers(client, "leading.zero@example.org")
    response = client.post("/api/projects", headers=h, json={"title": "Zero probe project", "academic_level": "masters",
                                                            "project_type": "client", "client_name": "Mbah Consulting",
                                                            "client_email": "contact@mbah.example", "client_whatsapp": "0677000000"})
    assert response.status_code == 400 and "without the leading 0" in response.json()["error"]["message"]


def test_a_reference_entry_longer_than_1000_characters_is_refused(client):
    h = auth_headers(client, "long.reference@example.org")
    project = make_project(client, h, title="Reference length study")
    too_long = client.put(f"/api/projects/{project['id']}/report-details", headers=h, json={"references": ["x" * 2000]})
    assert too_long.status_code == 422
    assert "at most 1000 characters" in too_long.text
    ok = client.put(f"/api/projects/{project['id']}/report-details", headers=h, json={"references": ["x" * 1000]})
    assert ok.status_code == 200


def test_the_project_list_reads_each_cost_file_once(client, monkeypatch):
    from app.services import project_costs
    h = auth_headers(client, "list-costs@example.org")
    for title in ("First costed project", "Second costed project"):
        pid = make_project(client, h, title=title)["id"]
        client.put(f"/api/projects/{pid}/costs", headers=h, json={"currency": "EUR", "items": [{"description": "Paper", "amount": 10}]})
    reads = []
    original = project_costs.get
    monkeypatch.setattr(project_costs, "get", lambda project_id: (reads.append(project_id), original(project_id))[1])
    listed = client.get("/api/projects", headers=h).json()["projects"]
    assert sorted(reads) == sorted(p["id"] for p in listed)          # exactly one read per project
    assert all(p["approximate_cost"] == 10 and p["cost_currency"] == "EUR" for p in listed)
