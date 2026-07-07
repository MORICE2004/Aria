"""Tests for the job tracker and job search agent."""

from fastapi.testclient import TestClient

from src.agents.jobsearch import parse_analysis


# ---------- the JSON parser (pure function, tested directly) ----------

def test_parse_analysis_plain_json() -> None:
    parsed = parse_analysis(
        '{"score": 72, "summary": "ok", "strengths": ["python"], "gaps": ["sql"]}'
    )
    assert parsed == {
        "score": 72, "summary": "ok", "strengths": ["python"], "gaps": ["sql"],
    }


def test_parse_analysis_fenced_json() -> None:
    parsed = parse_analysis('Here you go:\n```json\n{"score": 10}\n```')
    assert parsed is not None and parsed["score"] == 10


def test_parse_analysis_garbage_and_bad_score() -> None:
    assert parse_analysis("I cannot analyze this.") is None
    assert parse_analysis('{"score": 150}') is None
    assert parse_analysis('{"score": "high"}') is None


# ---------- endpoints ----------

def _add_job(client: TestClient, **overrides) -> dict:
    payload = {
        "company": "Acme",
        "role": "Junior Backend Developer",
        "description": "We need Python and FastAPI skills.",
        **overrides,
    }
    response = client.post("/jobs", json=payload)
    assert response.status_code == 201
    return response.json()


def test_job_crud_and_status_flow(client: TestClient) -> None:
    job = _add_job(client)
    assert job["status"] == "saved" and job["match_score"] is None

    updated = client.patch(f"/jobs/{job['id']}", json={"status": "applied"}).json()
    assert updated["status"] == "applied"

    assert client.patch(f"/jobs/{job['id']}", json={"status": "ghosted"}).status_code == 422

    assert [j["id"] for j in client.get("/jobs", params={"status": "applied"}).json()] == [job["id"]]
    client.delete(f"/jobs/{job['id']}")
    assert client.get("/jobs").json() == []


def test_analyze_requires_description(client: TestClient) -> None:
    job = _add_job(client, description="")
    assert client.post(f"/jobs/{job['id']}/analyze").status_code == 422


def test_analyze_with_unstructured_reply_keeps_text_no_fake_score(
    client: TestClient,
) -> None:
    """FakeLLM echoes (not JSON) — the honest outcome is score=None + raw text."""
    job = _add_job(client)
    analyzed = client.post(f"/jobs/{job['id']}/analyze").json()
    assert analyzed["match_score"] is None
    assert "unstructured analysis" in analyzed["match_notes"]


def test_cover_letter_saved_on_job(client: TestClient) -> None:
    job = _add_job(client)
    result = client.post(f"/jobs/{job['id']}/cover-letter", json={}).json()
    assert result["cover_letter"]  # FakeLLM output stored


def test_interview_prep_returns_text(client: TestClient) -> None:
    job = _add_job(client)
    response = client.post(f"/jobs/{job['id']}/interview-prep")
    assert response.status_code == 200 and response.json()["text"]


def test_recruiters_crud(client: TestClient) -> None:
    created = client.post(
        "/recruiters",
        json={"name": "Jane Doe", "company": "TalentCo", "email": "jane@talent.co"},
    )
    assert created.status_code == 201
    contact_id = created.json()["id"]
    assert client.get("/recruiters").json()[0]["name"] == "Jane Doe"
    assert client.post("/recruiters", json={"name": "X", "email": "nope"}).status_code == 422
    assert client.delete(f"/recruiters/{contact_id}").status_code == 204
