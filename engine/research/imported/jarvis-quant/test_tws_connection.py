from ib_async import IB  # ib_async is the maintained successor to ib_insync — same API

def main():
    ib = IB()
    try:
        # IB Gateway paper = 4002 (installed on this machine).
        # TWS paper = 7497 (TWS not yet installed; switch the port once it is).
        print("Trying to connect to IB Gateway paper trading on 127.0.0.1:4002 ...")
        ib.connect('127.0.0.1', 4002, clientId=1)
        print("CONNECTED OK")
        print("Server version:", ib.client.serverVersion())
        print("Managed accounts:", ib.managedAccounts())
    except Exception as e:
        print("CONNECTION FAILED")
        print("Error:", e)
    finally:
        if ib.isConnected():
            ib.disconnect()
            print("Disconnected cleanly.")

if __name__ == "__main__":
    main()
