import httpx
import json
import time

def run_tests():
    # Start the fast api server locally for testing?
    # Actually wait, maybe I will just start it alongside using httpx? Or I should just start the server via run_command and then run this script.
    
    print("Testing /health ...")
    r = httpx.get("http://127.0.0.1:8000/health")
    print(r.status_code, r.text)

    print("\nTesting /health/ready ...")
    r = httpx.get("http://127.0.0.1:8000/health/ready")
    print(r.status_code, r.text)

    print("\nTesting rate limiter on /api/v1/auth/login ...")
    for i in range(12):  # Limit is 10/minute
        r = httpx.post("http://127.0.0.1:8000/api/v1/auth/login", data={"username": "fake", "password": "fake"})
        if r.status_code == 429:
            print("Rate limit hit at request", i+1, r.text)
            break
        else:
            status = r.status_code
    print("Last status before rate limit or end:", status)

    print("\nWait complete.")

if __name__ == "__main__":
    run_tests()
