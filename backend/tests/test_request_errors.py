"""Two errors seen in use, kept from coming back: a variable linked twice (a 500 on the status page), and an AI request refused as too large (HTTP 413)."""
from app.ai.providers import AIProvider, AIUnavailableError
from app.ai.service import AIService
from app.services import ai_runtime

from tests.test_automatic_evidence import OutcomeMapper, _question_without_outcome
from tests.test_auto_analysis import _setup
from tests.conftest import auth_headers


class RefusesLargePrompts(AIProvider):
    """Stands in for a provider that answers HTTP 413 when the request is too large."""
    name = "refuses-large"

    def __init__(self, limit=6000):
        super().__init__(model="limit-1")
        self.limit = limit
        self.sizes = []

    def complete(self, system, messages, max_tokens=1200):
        size = len(messages[-1]["content"])
        self.sizes.append(size)
        if size > self.limit:
            raise AIUnavailableError("The AI provider returned an error (HTTP 413).")
        return '{"dependent": "gpa", "independent": []}'


def test_a_predictor_the_ai_names_as_the_outcome_is_changed_not_linked_twice(client):
    ai_runtime.set_ai_service(AIService(OutcomeMapper()))
    h = auth_headers(client, "double-link@example.org")
    pid, did, rq1, rq2, h1 = _setup(client, h)
    rq3 = _question_without_outcome(client, h, pid, did)       # social_media_hours is already linked as a predictor

    response = client.get(f"/api/projects/{pid}/ai/automatic-analysis", headers=h, params={"dataset_id": did})
    assert response.status_code == 200, response.text
    saved = next(q for q in client.get(f"/api/projects/{pid}/research-questions", headers=h).json()["research_questions"] if q["id"] == rq3["id"])
    roles = {v["name"]: v["role"] for v in saved["variables"]}
    assert roles.get("gpa") == "dependent" and roles.get("social_media_hours") == "independent"
    assert len(saved["variables"]) == len(roles)                 # one row per variable
    ai_runtime.set_ai_service(None)


def test_a_request_too_large_for_the_provider_is_compacted_and_answered():
    provider = RefusesLargePrompts()
    service = AIService(provider)
    long_items = [f"item {i} " + "x" * 300 for i in range(300)]
    context = {"project": {"title": "Large project"}, "variables": [{"name": "gpa", "label": "GPA", "categories": long_items}],
               "statistical_results": [{"method": "pearson", "notes": long_items}]}
    result = service.map_variables(context, ["gpa", "social_media_hours"])
    assert result["status"] == "mapped" and result["dependent"] == "gpa"
    assert provider.sizes[0] > provider.limit and provider.sizes[-1] <= provider.limit   # the first request was too large, the last fits
