"""
Docker Stack Integration & Smoke Test Suite for SmallBook.

Can be run:
1. Directly via Python: `python tests/test_docker_stack.py`
2. Via Pytest: `pytest tests/test_docker_stack.py` (automatically skips if containers are not running)

Validates:
- Web container /health endpoint returns 200 OK and valid JSON.
- Landing page server-side Jinja2 rendering.
- Static assets delivery (theme.js).
- Redis broker responsiveness inside container network.
- Celery worker registration and event loop status.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import pytest


def _is_docker_running() -> bool:
    """Checks if the web container is reachable."""
    try:
        req = urllib.request.Request("http://localhost:8000/health")
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


# Pytest fixture to skip tests if docker stack is offline
@pytest.fixture(scope="module")
def require_docker_stack():
    if not _is_docker_running():
        pytest.skip("SmallBook Docker stack is not running on http://localhost:8000. Start it with: docker compose up -d")


def test_docker_health_endpoint(require_docker_stack):
    """Verifies that the /health endpoint responds with 200 OK and expected status payload."""
    url = "http://localhost:8000/health"
    req = urllib.request.Request(url, headers={"User-Agent": "SmallBook-Verifier/1.0"})
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert data.get("status") == "ok"
        assert data.get("service") == "smallbook"


def test_docker_landing_page(require_docker_stack):
    """Verifies that the root landing page renders correctly via Jinja2 SSR."""
    url = "http://localhost:8000/"
    req = urllib.request.Request(url, headers={"User-Agent": "SmallBook-Verifier/1.0"})
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
        html = response.read().decode("utf-8", errors="ignore")
        assert "SmallBook" in html


def test_docker_static_assets(require_docker_stack):
    """Verifies static JavaScript/CSS assets are served without caching/404 issues."""
    url = "http://localhost:8000/static/js/core/theme.js"
    req = urllib.request.Request(url, headers={"User-Agent": "SmallBook-Verifier/1.0"})
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200


def test_docker_redis_broker(require_docker_stack):
    """Verifies that the Redis container is healthy and responding to PING."""
    result = subprocess.run(
        ["docker", "exec", "smallbook_redis", "redis-cli", "ping"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
    assert "PONG" in result.stdout


def test_docker_celery_worker(require_docker_stack):
    """Verifies Celery worker container initialized and logged connected status."""
    result = subprocess.run(
        ["docker", "logs", "smallbook_celery", "--tail", "40"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    logs = (result.stdout + result.stderr).lower()
    assert any(keyword in logs for keyword in ["ready.", "celery@", "smallbook_worker", "consumer: ready"])


# ==============================================================================
# CLI STANDALONE RUNNER (python tests/test_docker_stack.py)
# ==============================================================================

def run_standalone():
    print("=" * 65)
    print(" SmallBook Docker Stack Automated Verification Suite")
    print("=" * 65)

    max_retries = 6
    web_ready = False
    for attempt in range(1, max_retries + 1):
        if _is_docker_running():
            web_ready = True
            break
        print(f"Waiting for web container to become ready... (attempt {attempt}/{max_retries})")
        time.sleep(3)

    if not web_ready:
        print("\n[ERROR] Web service is not reachable at http://localhost:8000/health.")
        print("Please check: docker compose logs web")
        sys.exit(1)

    checks = [
        ("Health Endpoint (/health)", lambda: test_docker_health_endpoint(None)),
        ("Landing Page Rendering (/)", lambda: test_docker_landing_page(None)),
        ("Static Asset Delivery (/static/...)", lambda: test_docker_static_assets(None)),
        ("Redis Broker Connectivity", lambda: test_docker_redis_broker(None)),
        ("Celery Worker Process Status", lambda: test_docker_celery_worker(None)),
    ]

    all_passed = True
    for name, check_fn in checks:
        print(f"\n[TEST] Checking {name}...")
        try:
            check_fn()
            print(f"  [OK] {name} passed.")
        except Exception as e:
            print(f"  [FAIL] {name} failed: {e}")
            all_passed = False

    print("\n" + "=" * 65)
    if all_passed:
        print(" [SUCCESS] ALL CHECKS PASSED! The SmallBook Docker stack is running.")
        print(" Browser URL: http://localhost:8000")
        print("=" * 65)
        sys.exit(0)
    else:
        print(" [WARNING] Some checks reported issues. Inspect the logs above.")
        print("=" * 65)
        sys.exit(1)


if __name__ == "__main__":
    run_standalone()
