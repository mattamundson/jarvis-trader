"""Test WhatsApp notification — sends a test message to verify Twilio setup."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(".env")

from notifications.whatsapp import WhatsAppNotifier


async def main():
    notifier = WhatsAppNotifier()

    if not notifier.enabled:
        print("FAIL: WhatsApp notifier is NOT enabled.")
        print(
            "Check that TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_TO are set in .env"
        )
        return False

    print("WhatsApp notifier enabled. Sending test message...")
    result = await notifier.test()
    print(f"Result: {result}")

    if result:
        print("SUCCESS: WhatsApp test message sent!")
    else:
        print("FAIL: WhatsApp message failed to send. Check Twilio credentials and sandbox setup.")

    return result


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
