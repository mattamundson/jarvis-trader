import asyncio
from fastapi.testclient import TestClient
from main import app, data_manager

async def test():
    await data_manager.startup()
    client = TestClient(app)
    response = client.get("/paper/mgc-signal")
    print(f"Status Code: {response.status_code}")
    print("Response JSON:")
    print(response.json())
    await data_manager.shutdown()

if __name__ == "__main__":
    asyncio.run(test())
