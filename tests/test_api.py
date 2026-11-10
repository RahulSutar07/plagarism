import io
import time
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_limits_exposed_before_upload():
    body = client.get("/limits").json()
    assert body["max_file_mb"] == 7
    assert "pre-check" in body["positioning"]
    assert body["min_words"] == 100


def test_paste_under_word_limit_rejected():
    short_text = "This is a very short text with only ten words here."
    res = client.post("/api/check/paste", json={"text": short_text})
    assert res.status_code == 400
    assert "under the minimum" in res.json()["detail"]


def test_paste_over_2000_word_limit_rejected():
    long_text = "word " * 2050
    res = client.post("/api/check/paste", json={"text": long_text, "title": "Too Long"})
    assert res.status_code == 400
    assert "2000 words" in res.json()["detail"]


def test_paste_valid_text_and_polling():
    # Academic paragraph repeated to exceed 100 words
    paragraph = (
        "Convolutional neural networks represent a specialized category of deep artificial "
        "neural networks designed primarily for processing structured grid data such as digital images. "
        "By utilizing convolutional layers and pooling operations, these networks extract hierarchical "
        "spatial features from low-level edges to complex semantic objects. "
    ) * 4
    words = paragraph.split()
    assert len(words) >= 100

    # Submit job
    submit_res = client.post(
        "/api/check/paste",
        json={
            "text": paragraph,
            "title": "CNN Academic Paper",
            "enable_web_search": False,
            "enable_paraphrase": False,
        },
        headers={"X-Forwarded-For": "192.0.2.1"},
    )
    assert submit_res.status_code == 202
    data = submit_res.json()
    assert "job_id" in data
    assert data["status"] == "queued"
    job_id = data["job_id"]

    # Poll status until finished
    completed = False
    for _ in range(30):
        poll_res = client.get(f"/api/jobs/{job_id}")
        assert poll_res.status_code == 200
        poll_data = poll_res.json()
        if poll_data["status"] == "completed":
            completed = True
            assert poll_data["progress_pct"] == 100
            assert poll_data["result"] is not None
            assert poll_data["result"]["total_words"] >= 100
            assert poll_data["result"]["overall_similarity_pct"] > 50.0
            break
        time.sleep(0.3)

    assert completed is True


def test_upload_magic_bytes_rejection():
    fake_pdf = b"This is plain text with a renamed extension, not a real PDF binary."
    res = client.post(
        "/api/check/upload",
        files={"file": ("fake_paper.pdf", io.BytesIO(fake_pdf), "application/pdf")},
    )
    assert res.status_code == 400
    assert "magic bytes mismatch" in res.json()["detail"]


def test_upload_valid_txt_file():
    txt_content = (
        "Central banks utilize monetary policy instruments including benchmark interest rates, "
        "open market operations, and quantitative easing to achieve price stability and sustainable "
        "economic expansion across domestic and international markets. "
    ) * 4

    res = client.post(
        "/api/check/upload",
        files={"file": ("monetary_policy.txt", io.BytesIO(txt_content.encode("utf-8")), "text/plain")},
        data={"title": "Monetary Policy Study", "enable_paraphrase": "false"},
        headers={"X-Forwarded-For": "192.0.2.2"},
    )
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    assert job_id.startswith("job-")


def test_job_not_found():
    res = client.get("/api/jobs/job-nonexistent-123")
    assert res.status_code == 404


def test_serve_frontend():
    res = client.get("/")
    assert res.status_code == 200
    assert "Plagiarism Pre-Check" in res.text


def test_download_pdf_report_lifecycle():
    # Submit short academic text
    text = (
        "Quantum computing harnesses the unique phenomena of quantum mechanics, notably "
        "superposition and entanglement, to perform complex computations exponentially "
        "faster than classical digital processors across specific algorithmic problem spaces. "
    ) * 4
    submit_res = client.post(
        "/api/check/paste",
        json={"text": text, "title": "Quantum Paper", "enable_paraphrase": False},
        headers={"X-Forwarded-For": "192.0.2.3"},
    )
    assert submit_res.status_code == 202
    job_id = submit_res.json()["job_id"]

    # Poll until complete
    for _ in range(30):
        r = client.get(f"/api/jobs/{job_id}")
        if r.json()["status"] == "completed":
            break
        time.sleep(0.3)

    # Download PDF report
    pdf_res = client.get(f"/api/jobs/{job_id}/report.pdf")
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert pdf_res.content.startswith(b"%PDF-")
    assert len(pdf_res.content) > 1000

    # Nonexistent job PDF report
    not_found_res = client.get("/api/jobs/job-nonexistent-999/report.pdf")
    assert not_found_res.status_code == 404


def test_user_jobs_history_and_pagination():
    import uuid
    email = f"user.{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/api/auth/register", json={"email": email, "password": "Password123!"})
    assert reg.status_code == 201
    token = reg.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Submit a job under this user
    paragraph = (
        "Convolutional neural networks represent a specialized category of deep artificial "
        "neural networks designed primarily for processing structured grid data such as digital images. "
    ) * 5
    res = client.post(
        "/api/check/paste",
        json={"text": paragraph, "title": "History Test Document", "enable_paraphrase": False},
        headers=auth_headers,
    )
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Poll until completed
    for _ in range(30):
        poll = client.get(f"/api/jobs/{job_id}")
        if poll.json()["status"] == "completed":
            break
        time.sleep(0.3)

    # Query history
    history_res = client.get("/api/user/jobs?limit=10&offset=0", headers=auth_headers)
    assert history_res.status_code == 200
    history = history_res.json()
    assert len(history) >= 1
    assert any(j["job_id"] == job_id for j in history)
    matched = next(j for j in history if j["job_id"] == job_id)
    assert matched["title"] == "History Test Document"
    assert matched["status"] == "completed"


