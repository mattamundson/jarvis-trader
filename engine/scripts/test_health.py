"""Quick health endpoint test."""
import httpx

for path in ["/health", "/health/full"]:
    r = httpx.get(f"http://localhost:8010{path}", timeout=10)
    ct = r.headers.get("content-type", "")
    print(f"{path}: {r.status_code} {ct}")
    if r.status_code == 200:
        data = r.json()
        print("  keys:", list(data.keys()))
        if path == "/health/full":
            subsystems = data.get("subsystems", {})
            print("  subsystems:", list(subsystems.keys()))
    else:
        print(" ", r.text[:300])
