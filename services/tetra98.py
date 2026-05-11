import httpx


class Tetra98Gateway:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.create_url = "https://tetra98.com/api/create_order"
        self.verify_url = "https://tetra98.com/api/verify"

    async def create_order(
        self,
        *,
        hash_id: str,
        amount: int,
        description: str,
        callback_url: str,
        email: str = "",
        mobile: str = "",
    ):
        payload = {
            "ApiKey": self.api_key,
            "Hash_id": hash_id,
            "Amount": int(amount),
            "Description": description,
            "Email": email,
            "Mobile": mobile,
            "CallbackURL": callback_url,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(self.create_url, json=payload)
            try:
                data = res.json() if res.content else {}
            except Exception:
                data = {"_raw": (res.text or "").strip()}
            return res.status_code, data, (res.text or "").strip()

    async def verify(self, *, authority: str):
        payload = {"authority": authority, "ApiKey": self.api_key}
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(self.verify_url, json=payload)
            try:
                data = res.json() if res.content else {}
            except Exception:
                data = {"_raw": (res.text or "").strip()}
            return res.status_code, data, (res.text or "").strip()

