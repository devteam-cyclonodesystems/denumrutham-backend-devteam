import urllib.request
import json
import urllib.error

def request(url, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
        data = json.dumps(data).encode('utf-8')
    try:
        with urllib.request.urlopen(req, data=data) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')
    except Exception as e:
        return 0, str(e)

print("\n--- RATE LIMIT ---")
for i in range(12):
    code, body = request("http://127.0.0.1:8000/api/v1/auth/devotee/register", method="POST", data={"phone_number": "1234567890", "password": "abc"})
    if code == 429:
         print(f"RATE LIMIT Triggered on Request {i+1}: [{code}] {body}")
         break

