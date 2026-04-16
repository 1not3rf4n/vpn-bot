import httpx
from core.config import ZARINPAL_MERCHANT, ZARINPAL_SANDBOX

class Zarinpal:
    def __init__(self):
        self.merchant_id = ZARINPAL_MERCHANT
        self.sandbox = ZARINPAL_SANDBOX
        if self.sandbox:
            self.api_request = "https://sandbox.zarinpal.com/pg/v4/payment/request.json"
            self.api_verify = "https://sandbox.zarinpal.com/pg/v4/payment/verify.json"
            self.api_startpay = "https://sandbox.zarinpal.com/pg/StartPay/"
        else:
            self.api_request = "https://api.zarinpal.com/pg/v4/payment/request.json"
            self.api_verify = "https://api.zarinpal.com/pg/v4/payment/verify.json"
            self.api_startpay = "https://www.zarinpal.com/pg/StartPay/"

    async def request_payment(self, amount, description, callback_url, mobile="", email=""):
        payload = {
            "merchant_id": self.merchant_id,
            "amount": int(amount * 10), # Toman to Rial
            "description": description,
            "callback_url": callback_url,
            "metadata": {"mobile": mobile, "email": email}
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self.api_request, json=payload)
            if response.status_code == 200:
                data = response.json()
                if data.get("data") and data["data"].get("code") == 100:
                    authority = data["data"]["authority"]
                    return True, self.api_startpay + authority, authority
                else:
                    return False, data.get("errors", "Unknown Error"), None
            return False, "HTTP Error", None

    async def verify_payment(self, amount, authority):
        payload = {
            "merchant_id": self.merchant_id,
            "amount": int(amount * 10),
            "authority": authority
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(self.api_verify, json=payload)
            if response.status_code == 200:
                data = response.json()
                if data.get("data") and data["data"].get("code") in [100, 101]:
                    return True, data["data"]["ref_id"]
                else:
                    return False, data.get("errors", "Failed Verification")
            return False, "HTTP Error"
