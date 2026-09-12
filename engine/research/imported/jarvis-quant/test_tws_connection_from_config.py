import yaml
from ib_async import IB  # ib_async is the maintained successor to ib_insync

def main():
    with open("config/broker_ibkr.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    host = cfg["ibkr"]["host"]
    port = cfg["ibkr"]["port_paper"]
    client_id = cfg["ibkr"]["client_id"]

    ib = IB()
    try:
        print(f"Connecting to {host}:{port} with clientId={client_id} ...")
        ib.connect(host, port, clientId=client_id)
        print("CONNECTED OK")
        print("Managed accounts:", ib.managedAccounts())
        print("Positions:", ib.positions())
    except Exception as e:
        print("CONNECTION FAILED")
        print("Error:", e)
    finally:
        if ib.isConnected():
            ib.disconnect()
            print("Disconnected cleanly.")

if __name__ == "__main__":
    main()
