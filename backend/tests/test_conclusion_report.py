"""Charts belong to the review of findings. Conclusions carry no chart, and every report format renders the review and the conclusions."""
from app.database.session import SessionLocal
from app.models import Project, User
from app.reports import renderers
from app.services import ai_runtime, report_service

from tests.conftest import auth_headers
from tests.test_always_answered import _wait_for_runs
from tests.test_auto_analysis import _post, _setup


def _setup_with_analysis(client, email):
    h = auth_headers(client, email)
    pid, did, rq1, rq2, h1 = _setup(client, h)
    plans = _post(client, f"/api/projects/{pid}/ai/auto-analyze", h, {"dataset_id": did})
    _wait_for_runs(client, h, {"items": [{"run": {"id": p["run_id"]}} for p in plans["plans"] if p["run_id"]]})
    _post(client, f"/api/projects/{pid}/evidence/auto", h, {})
    with SessionLocal() as db:
        project = db.get(Project, pid)
        user = db.get(User, project.owner_id)
        return report_service.build_report_content(db, project, user, "Chart placement", None, None)


def test_the_finding_chart_sits_in_the_review_and_every_format_renders(client):
    ai_runtime.set_ai_service(None)
    content, images = _setup_with_analysis(client, "report-chart@example.org")
    figures = [payload for kind, payload in renderers._section_blocks(content, "review_findings") if kind == "figure"]
    assert figures and all(fig["image_key"] in images for fig in figures)
    # no conclusion section carries a figure
    assert not any(kind == "figure" for kind, _ in renderers._section_blocks(content, "conclusions"))
    assert renderers.render_pdf(content, images).startswith(b"%PDF")
    assert renderers.render_docx(content, images).startswith(b"PK")
