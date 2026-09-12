import yaml
from ib_async import IB, Future  # ib_async is the maintained successor to ib_insync

def main():
    with open("config/broker_ibkr.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    host = cfg["ibkr"]["host"]
    port = cfg["ibkr"]["port_paper"]
    client_id = 22
    expiry = cfg["contracts"]["ES"]["expiry_month"]

    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id)
        contract = Future(symbol='ES', lastTradeDateOrContractMonth=expiry, exchange='CME', currency='USD')
        qualified = ib.qualifyContracts(contract)
        print("Qualified contracts:", qualified)
    except Exception as e:
        print("FAILED")
        print("Error:", e)
    finally:
        if ib.isConnected():
            ib.disconnect()

if __name__ == "__main__":
    main()
