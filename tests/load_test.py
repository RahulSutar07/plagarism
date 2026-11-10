"""Locust load test suite for Plagiarism Pre-Check platform.

Simulates 50-100 concurrent students performing document submissions,
status polling, report downloads, and certificate verifications.

Usage:
  locust -f tests/load_test.py --headless -u 50 -r 5 --run-time 1m --host http://localhost:8000
"""
from __future__ import annotations

import random
import time

try:
    from locust import HttpUser, between, task
except ImportError:
    # Graceful fallback if running in an environment without locust installed
    class HttpUser:  # type: ignore
        pass

    def task(weight: int = 1):  # type: ignore
        def decorator(f):
            return f
        return decorator

    def between(a: float, b: float):  # type: ignore
        return lambda: random.uniform(a, b)


SAMPLE_ACADEMIC_PARAGRAPHS = [
    (
        "Machine learning models rely heavily on large-scale annotated corpora to generalize "
        "effectively across unseen test distributions. Deep neural networks, particularly transformer "
        "architectures, optimize millions of parameters using backpropagation and stochastic gradient "
        "descent to minimize empirical risk across complex multi-dimensional representations. "
    ) * 3,
    (
        "Renewable energy integration within modern electrical grids introduces intermittent power "
        "generation challenges that necessitate advanced energy storage systems, demand-response algorithms, "
        "and resilient microgrid topologies to maintain frequency stability and supply continuity. "
    ) * 3,
    (
        "Quantitative easing and central bank balance sheet expansions stimulate aggregate demand "
        "during deflationary recessions by lowering benchmark yields, flattening the sovereign yield "
        "curve, and incentivizing private capital formation across diverse economic sectors. "
    ) * 3,
]


class StudentUser(HttpUser):
    """Simulates realistic student behavior submitting documents and polling for results."""
    wait_time = between(1.0, 3.0)

    def on_start(self) -> None:
        """Register or generate unique student session."""
        self.student_ip = f"10.{random.randint(1, 250)}.{random.randint(1, 250)}.{random.randint(1, 250)}"
        self.headers = {"X-Forwarded-For": self.student_ip}

    @task(4)
    def check_paste_submission_lifecycle(self) -> None:
        """Submit pasted academic text, poll for completion, and download PDF outputs."""
        text = random.choice(SAMPLE_ACADEMIC_PARAGRAPHS)
        title = f"Student Research Essay #{random.randint(100, 999)}"

        payload = {
            "text": text,
            "title": title,
            "enable_web_search": False,
            "enable_paraphrase": False,
        }

        # 1. Submit scan
        with self.client.post(
            "/api/check/paste",
            json=payload,
            headers=self.headers,
            catch_response=True,
        ) as response:
            if response.status_code == 202:
                response.success()
                job_id = response.json().get("job_id")
            elif response.status_code in (429, 503):
                # Valid backpressure responses (queue full or daily rate limit)
                response.success()
                return
            else:
                response.failure(f"Unexpected submission status: {response.status_code}")
                return

        if not job_id:
            return

        # 2. Poll job status until completion
        for _ in range(15):
            time.sleep(0.5)
            with self.client.get(
                f"/api/jobs/{job_id}",
                headers=self.headers,
                catch_response=True,
            ) as poll_res:
                if poll_res.status_code == 200:
                    status_data = poll_res.json()
                    if status_data.get("status") == "completed":
                        poll_res.success()
                        break
                else:
                    poll_res.failure(f"Polling failed with status {poll_res.status_code}")
                    break

        # 3. Download generated PDF report
        self.client.get(f"/api/jobs/{job_id}/report.pdf", headers=self.headers)

        # 4. Download generated Certificate
        self.client.get(f"/api/jobs/{job_id}/certificate.pdf", headers=self.headers)

    @task(2)
    def check_limits_and_rules(self) -> None:
        """Fetch upload limits and legal positioning."""
        self.client.get("/limits", headers=self.headers)

    @task(1)
    def check_system_health(self) -> None:
        """Operational health ping."""
        self.client.get("/health", headers=self.headers)

    @task(1)
    def visit_legal_pages(self) -> None:
        """Check privacy policy and terms."""
        self.client.get("/legal/privacy", headers=self.headers)
        self.client.get("/legal/terms", headers=self.headers)
