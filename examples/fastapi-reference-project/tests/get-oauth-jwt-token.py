import os
import json
import http.client
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load ENV VARs
load_dotenv()
issuer = os.getenv("AUTH0_DOMAIN")
client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")
audience = os.getenv("API_AUDIENCE")
# Check ENV VARs are available
if not issuer or not client_id or not client_secret or not audience:
    raise RuntimeError("Missing one or more required environment variables")

# Do some work!
conn = http.client.HTTPSConnection(issuer)

payload = json.dumps({
    "client_id": client_id,
    "client_secret": client_secret,
    "audience": audience,
    "grant_type": "client_credentials"
})

headers = { 'content-type': "application/json" }

conn.request("POST", "/oauth/token", payload, headers)

res = conn.getresponse()
raw = res.read()
text = raw.decode("utf-8")

try:
    obj = json.loads(text)
    pretty = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
    print(pretty)
except json.JSONDecodeError:
    # not JSON — fall back to raw text
    print(text)