import urllib.request
import json
import time
from packages.infrastructure.db_connector import get_connection, release_connection

def run_test():
    # 1. Fetch a real company from DB
    conn = get_connection()
    company = None
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT org_id, legal_name, primary_domain, industry 
                FROM master_dataextraction.organizations 
                WHERE primary_domain IS NOT NULL AND primary_domain != '' 
                  AND primary_domain NOT LIKE '%example.com%' AND primary_domain NOT LIKE '%.local%'
                LIMIT 1
            """)
            r = cur.fetchone()
            if r:
                company = {
                    "id": str(r[0]),
                    "name": r[1],
                    "domain": r[2],
                    "industry": r[3] or "Healthcare & Life Sciences"
                }
    finally:
        release_connection(conn)

    if not company:
        print("No valid company found in DB!")
        return

    print(f"Testing with Real Entity: {company['name']} (ID: {company['id']}, Domain: {company['domain']})")

    # 2. Test POST /api/leads/company/{id}/crawl
    print("\n--- 1. Testing POST /api/leads/company/{id}/crawl ---")
    crawl_url = f"http://127.0.0.1:8000/api/leads/company/{company['id']}/crawl?domain={company['domain']}"
    t0 = time.time()
    try:
        req = urllib.request.Request(crawl_url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            dur = round((time.time() - t0) * 1000, 2)
            body = json.loads(resp.read().decode())
            print(f"[SUCCESS] HTTP {resp.status} in {dur}ms")
            print(f"Overview: {body.get('overview')[:100] if body.get('overview') else 'None'}...")
    except urllib.error.HTTPError as he:
        print(f"[FAIL] HTTP {he.code}: {he.read().decode()}")
    except Exception as exc:
        print(f"[FAIL] Exception: {exc}")

    # 3. Test POST /api/leads/company/{id}/crawl-all
    print("\n--- 2. Testing POST /api/leads/company/{id}/crawl-all ---")
    crawl_all_url = f"http://127.0.0.1:8000/api/leads/company/{company['id']}/crawl-all?domain={company['domain']}"
    t0 = time.time()
    try:
        req = urllib.request.Request(crawl_all_url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25.0) as resp:
            dur = round((time.time() - t0) * 1000, 2)
            body = json.loads(resp.read().decode())
            print(f"[SUCCESS] HTTP {resp.status} in {dur}ms")
            print(f"Overall crawl sources: {body.get('overall_crawl', {}).get('sources_scraped')}")
    except urllib.error.HTTPError as he:
        print(f"[FAIL] HTTP {he.code}: {he.read().decode()}")
    except Exception as exc:
        print(f"[FAIL] Exception: {exc}")

    # 4. Test Chat with Company Context (Simulating Contextual Chat Drawer)
    print("\n--- 3. Testing Contextual Chat Drawer Backend Flow ---")
    # A: Create session
    sess_url = "http://127.0.0.1:8000/api/v1/chat/sessions"
    sess_payload = {
        "title": f"{company['name']} Intelligence",
        "company_context": {
            "company_id": company["id"],
            "company_name": company["name"],
            "domain": company["domain"],
            "industry": company["industry"],
            "overview": "Leading healthcare and medical distributor",
        }
    }
    t0 = time.time()
    session_id = None
    try:
        req = urllib.request.Request(sess_url, data=json.dumps(sess_payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            s_body = json.loads(resp.read().decode())
            session_id = s_body["id"]
            print(f"[SUCCESS] Session created: {session_id} in {round((time.time() - t0)*1000, 2)}ms")
    except Exception as exc:
        print(f"[FAIL] Session creation failed: {exc}")

    if session_id:
        # B: Send contextual message: "Draft Outreach Email"
        msg_url = f"http://127.0.0.1:8000/api/v1/chat/sessions/{session_id}/messages"
        msg_payload = {
            "content": "Draft a concise, high-converting B2B sales outreach email to the executive leadership of this company highlighting our value proposition.",
            "company_context": sess_payload["company_context"]
        }
        t0 = time.time()
        try:
            req = urllib.request.Request(msg_url, data=json.dumps(msg_payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                dur = round((time.time() - t0) * 1000, 2)
                m_body = json.loads(resp.read().decode())
                print(f"[SUCCESS] Message response received in {dur}ms (HTTP {resp.status}):")
                content = m_body.get("content") or ""
                print(f"Content preview:\n{content[:300]}...")
        except urllib.error.HTTPError as he:
            print(f"[FAIL] Message failed HTTP {he.code}: {he.read().decode()}")
        except Exception as exc:
            print(f"[FAIL] Message failed: {exc}")

if __name__ == "__main__":
    run_test()
