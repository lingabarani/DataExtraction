import urllib.request
import json
import time
import sys

def audit():
    try:
        req = urllib.request.Request("http://127.0.0.1:8000/api/openapi.json")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error fetching openapi.json: {e}")
        return

    paths = data.get("paths", {})
    print(f"Total OpenAPI Paths Registered: {len(paths)}")
    
    # We will test common GET endpoints and key POST endpoints
    endpoints_to_test = [
        ("GET", "/api/health", None),
        ("GET", "/health/live", None),
        ("GET", "/healthz", None),
        ("GET", "/api/leads?limit=5", None),
        ("GET", "/api/leads/count", None),
        ("GET", "/api/leads/mexico?limit=5", None),
        ("GET", "/api/leads/industries", None),
        ("GET", "/api/leads/stats/overview", None),
        ("GET", "/api/search/companies?query=tech&limit=3", None),
        ("POST", "/api/search/companies", {"query": "Healthcare", "limit": 3}),
        ("POST", "/api/search/people", {"query": "Executive", "limit": 3}),
        ("POST", "/api/ai/parse-search-query", {"query": "Healthcare in Texas", "target_mode": "company"}),
        ("POST", "/api/ai/chat-search", {"query": "Healthcare in Texas", "target_mode": "company", "limit": 5}),
        ("POST", "/api/v1/chat/sessions", {"title": "Audit Test Session"}),
        ("GET", "/api/v1/chat/sessions", None),
        ("GET", "/api/v1/chat/reviews", None),
        ("GET", "/api/v1/chat/reviews/stats", None),
        ("GET", "/api/v1/extract/jobs", None),
        ("GET", "/api/places/search?query=Hospital&limit=3", None),
        ("GET", "/api/dlq", None),
        ("GET", "/api/stats", None),
    ]

    print("\n--- RUNNING SYSTEMATIC ENDPOINT AUDIT ---")
    results = []
    for method, path, payload in endpoints_to_test:
        url = f"http://127.0.0.1:8000{path}"
        t0 = time.time()
        try:
            req_data = json.dumps(payload).encode() if payload else None
            headers = {"Content-Type": "application/json"} if payload else {}
            req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=25.0) as resp:
                elapsed = round((time.time() - t0) * 1000, 2)
                code = resp.status
                body = resp.read().decode()
                try:
                    parsed = json.loads(body)
                    summary = f"JSON (keys: {list(parsed.keys())[:4]}...)" if isinstance(parsed, dict) else f"JSON array (len: {len(parsed)})"
                except:
                    summary = f"Text ({len(body)} chars)"
                status = "PASS" if code in (200, 201) else "WARN"
                print(f"[{status}] {method:5} {path:45} -> HTTP {code} ({elapsed}ms) | {summary}")
                results.append((method, path, code, elapsed, "OK"))
        except urllib.error.HTTPError as he:
            elapsed = round((time.time() - t0) * 1000, 2)
            print(f"[FAIL] {method:5} {path:45} -> HTTP {he.code} ({elapsed}ms) | {he.reason}")
            results.append((method, path, he.code, elapsed, f"HTTPError: {he.reason}"))
        except Exception as exc:
            elapsed = round((time.time() - t0) * 1000, 2)
            print(f"[ERR ] {method:5} {path:45} -> EXCEPTION ({elapsed}ms) | {exc}")
            results.append((method, path, 0, elapsed, str(exc)))

    # Also list all other endpoints from OpenAPI
    print(f"\n--- ALL {len(paths)} REGISTERED OPENAPI PATHS ---")
    for p, methods in sorted(paths.items()):
        for m in methods:
            if m.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                print(f"{m.upper():6} {p}")

if __name__ == "__main__":
    audit()
