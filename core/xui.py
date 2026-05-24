import httpx
import uuid
import json
import logging
import time
import re
import asyncio
from urllib.parse import urlparse, quote

logger = logging.getLogger(__name__)

# API route sets: legacy sanaei x-ui vs modern 3x-ui
API_LEGACY = "legacy"
API_3XUI = "3xui"


def _sanitize_email(email: str) -> str:
    """Panel rejects some characters in client email."""
    email = re.sub(r"[^a-zA-Z0-9_.@-]", "_", email)
    return email[:64] if len(email) > 64 else email


def _parse_json_response(res: httpx.Response) -> dict:
    text = (res.text or "").strip()
    if not text:
        return {"success": False, "msg": "empty response", "status": res.status_code}
    try:
        return res.json()
    except Exception:
        return {"success": False, "msg": text[:500], "status": res.status_code}


class XUIApi:
    def __init__(self, url, username, password):
        url_clean = url.rstrip('/')
        for path_to_strip in ['/panel/inbounds', '/panel/inbound', '/panel/api/inbounds', '/panel', '/inbounds', '/xui']:
            if url_clean.endswith(path_to_strip):
                url_clean = url_clean[:-len(path_to_strip)]
        self.url = url_clean.rstrip('/')
        self.username = username
        self.password = password
        self.session = httpx.AsyncClient(
            verify=False,
            timeout=20.0,
            follow_redirects=True,
            headers={
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        self.logged_in = False
        self.api_mode = None
        self.server_ip = urlparse(self.url).hostname
        self._last_error = ""

    @property
    def last_error(self) -> str:
        return self._last_error

    async def login(self):
        try:
            res = await self.session.post(
                f"{self.url}/login",
                data={"username": self.username, "password": self.password},
            )
            body = _parse_json_response(res)
            if res.status_code == 200 and body.get("success"):
                self.logged_in = True
                await self._detect_api_mode()
                logger.info(f"X-UI login OK, api_mode={self.api_mode}, url={self.url}")
                return True
            self._last_error = body.get("msg") or f"HTTP {res.status_code}"
            logger.error(f"X-UI Login failed: {body}")
            return False
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"X-UI Login exception: {e}")
            return False

    async def _detect_api_mode(self):
        """Probe which API paths this panel supports."""
        probes = [
            (API_3XUI, "GET", f"{self.url}/panel/api/inbounds/list"),
            (API_LEGACY, "POST", f"{self.url}/xui/inbound/list"),
            (API_3XUI, "POST", f"{self.url}/panel/api/inbounds/list"),
        ]
        for mode, method, url in probes:
            try:
                if method == "GET":
                    res = await self.session.get(url)
                else:
                    res = await self.session.post(url)
                body = _parse_json_response(res)
                if res.status_code == 200 and (body.get("success") or body.get("obj") is not None):
                    self.api_mode = mode
                    return
            except Exception:
                continue
        self.api_mode = API_LEGACY

    async def _request(self, method: str, path: str, **kwargs) -> tuple[httpx.Response, dict]:
        url = f"{self.url}{path}" if path.startswith("/") else path
        if method == "GET":
            res = await self.session.get(url, **kwargs)
        else:
            res = await self.session.post(url, **kwargs)
        return res, _parse_json_response(res)

    async def list_inbounds(self) -> list:
        if not self.logged_in and not await self.login():
            return []
        paths = []
        if self.api_mode == API_3XUI:
            paths = ["/panel/api/inbounds/list"]
        else:
            paths = ["/xui/inbound/list", "/panel/api/inbounds/list", "/panel/inbound/list"]
        for path in paths:
            try:
                res, body = await self._request("POST" if "xui" in path else "GET", path)
                if not body.get("success"):
                    res, body = await self._request("POST", path)
                if body.get("success"):
                    obj = body.get("obj") or body.get("data") or []
                    if isinstance(obj, list):
                        if not self.api_mode and "/panel/api/" in path:
                            self.api_mode = API_3XUI
                        return obj
            except Exception as e:
                logger.debug(f"list_inbounds {path}: {e}")
        return []

    async def get_inbound(self, inbound_id: int):
        if not self.logged_in and not await self.login():
            return None
        for inb in await self.list_inbounds():
            if int(inb.get("id", -1)) == int(inbound_id):
                return inb
        try:
            res, body = await self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")
            if body.get("success"):
                return body.get("obj") or body.get("data")
        except Exception:
            pass
        return None

    def _inbound_needs_flow(self, inbound: dict) -> str:
        try:
            stream = inbound.get("streamSettings") or {}
            if isinstance(stream, str):
                stream = json.loads(stream)
            if stream.get("security") == "reality":
                return "xtls-rprx-vision"
            sniffing = inbound.get("sniffing") or {}
            if isinstance(sniffing, str):
                sniffing = json.loads(sniffing)
        except Exception:
            pass
        return ""

    async def add_client(
        self, inbound_id: int, email: str, total_gb: float = 0, expire_days: int = 30, limit_ip: int = 1
    ):
        if not self.logged_in and not await self.login():
            return None

        email = _sanitize_email(email)
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            ids = [i.get("id") for i in await self.list_inbounds()]
            self._last_error = f"inbound {inbound_id} not found. Available: {ids}"
            logger.error(self._last_error)
            return None

        client_uuid = str(uuid.uuid4())
        expiry_time = int((time.time() + (expire_days * 86400)) * 1000) if expire_days > 0 else 0
        total_bytes = int(total_gb * 1073741824) if total_gb > 0 else 0
        flow = self._inbound_needs_flow(inbound)
        sub_id = email

        strategies = [
            self._add_client_modern,
            self._add_client_3xui_form,
            self._add_client_legacy,
        ]
        for attempt in range(3):
            for fn in strategies:
                result = await fn(
                    inbound_id, email, client_uuid, total_bytes, expiry_time, limit_ip, flow, sub_id
                )
                if result:
                    return result
            if attempt < 2:
                await asyncio.sleep(1.5)

        logger.error(f"X-UI addClient all strategies failed: {self._last_error}")
        return None

    async def _add_client_modern(
        self, inbound_id, email, client_uuid, total_bytes, expiry_time, limit_ip, flow, sub_id
    ):
        """3x-ui v2+ POST /panel/api/clients/add (JSON)."""
        payload = {
            "client": {
                "id": client_uuid,
                "email": email,
                "limitIp": limit_ip,
                "totalGB": total_bytes,
                "expiryTime": expiry_time,
                "enable": True,
                "tgId": 0,
                "subId": sub_id,
                "flow": flow,
                "comment": "",
                "reset": 0,
            },
            "inboundIds": [int(inbound_id)],
        }
        try:
            res = await self.session.post(
                f"{self.url}/panel/api/clients/add",
                json=payload,
            )
            body = _parse_json_response(res)
            if res.status_code == 200 and body.get("success"):
                self.api_mode = API_3XUI
                logger.info(f"X-UI client created (modern API): {email}")
                return client_uuid
            self._last_error = body.get("msg") or str(body)
            if total_bytes > 0:
                payload["client"]["totalGB"] = int(total_bytes / 1073741824)
                res2 = await self.session.post(f"{self.url}/panel/api/clients/add", json=payload)
                body2 = _parse_json_response(res2)
                if res2.status_code == 200 and body2.get("success"):
                    logger.info(f"X-UI client created (modern API, GB units): {email}")
                    return client_uuid
        except Exception as e:
            self._last_error = str(e)
        return None

    async def _add_client_3xui_form(
        self, inbound_id, email, client_uuid, total_bytes, expiry_time, limit_ip, flow, sub_id
    ):
        client_data = {
            "id": client_uuid,
            "flow": flow,
            "email": email,
            "limitIp": limit_ip,
            "totalGB": total_bytes,
            "expiryTime": expiry_time,
            "enable": True,
            "tgId": "",
            "subId": sub_id,
            "reset": 0,
        }
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]}),
        }
        paths = [
            "/panel/api/inbounds/addClient",
            "/panel/inbound/addClient",
        ]
        for path in paths:
            try:
                res = await self.session.post(f"{self.url}{path}", data=payload)
                body = _parse_json_response(res)
                if res.status_code == 200 and body.get("success"):
                    self.api_mode = API_3XUI
                    logger.info(f"X-UI client created ({path}): {email}")
                    return client_uuid
                self._last_error = body.get("msg") or str(body)
            except Exception as e:
                self._last_error = str(e)
        return None

    async def _add_client_legacy(
        self, inbound_id, email, client_uuid, total_bytes, expiry_time, limit_ip, flow, sub_id
    ):
        client_data = {
            "id": client_uuid,
            "flow": flow,
            "email": email,
            "limitIp": limit_ip,
            "totalGB": total_bytes,
            "expiryTime": expiry_time,
            "enable": True,
            "tgId": "",
            "subId": sub_id,
        }
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]}),
        }
        try:
            res = await self.session.post(f"{self.url}/xui/inbound/addClient", data=payload)
            body = _parse_json_response(res)
            if res.status_code == 200 and body.get("success"):
                self.api_mode = API_LEGACY
                logger.info(f"X-UI client created (legacy): {email}")
                return client_uuid
            self._last_error = body.get("msg") or str(body)
        except Exception as e:
            self._last_error = str(e)
        return None

    async def get_client_links(self, email: str) -> list[str]:
        """Fetch connection links from panel API when available."""
        if not self.logged_in and not await self.login():
            return []
        email = _sanitize_email(email)
        try:
            res, body = await self._request("GET", f"/panel/api/clients/links/{quote(email, safe='')}")
            if body.get("success"):
                obj = body.get("obj") or body.get("data") or []
                if isinstance(obj, list):
                    return [str(x).strip() for x in obj if x]
                if isinstance(obj, str) and obj.strip():
                    return [obj.strip()]
        except Exception as e:
            logger.debug(f"get_client_links: {e}")
        return []

    async def build_direct_link(self, inbound_id: int, client_uuid: str, remark: str):
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return None

        protocol = inbound.get("protocol", "vless")
        port = inbound.get("port", 443)
        stream = json.loads(inbound["streamSettings"]) if isinstance(inbound.get("streamSettings"), str) else (inbound.get("streamSettings") or {})

        network = stream.get("network", "tcp")
        security = stream.get("security", "none")
        encoded_remark = quote(remark)

        if protocol == "vless":
            params = f"type={network}&security={security}"

            if network == "ws":
                ws = stream.get("wsSettings", {})
                path = quote(ws.get("path", "/"))
                host = ws.get("host", "")
                params += f"&path={path}"
                if host:
                    params += f"&host={host}"
            elif network == "grpc":
                grpc = stream.get("grpcSettings", {})
                sn = grpc.get("serviceName", "")
                params += f"&serviceName={sn}"
            elif network == "tcp":
                tcp = stream.get("tcpSettings", {})
                header_type = tcp.get("header", {}).get("type", "none")
                params += f"&headerType={header_type}"

            if security == "tls":
                tls = stream.get("tlsSettings", {})
                sni = tls.get("serverName", "")
                fp = tls.get("fingerprint", "")
                if sni:
                    params += f"&sni={sni}"
                if fp:
                    params += f"&fp={fp}"
            elif security == "reality":
                real = stream.get("realitySettings", {})
                pbk = real.get("publicKey", "")
                sid = real.get("shortId", "")
                sni = real.get("serverNames", [""])[0] if real.get("serverNames") else ""
                fp = real.get("fingerprint", "")
                flow = self._inbound_needs_flow(inbound)
                if flow:
                    params += f"&flow={flow}"
                if pbk:
                    params += f"&pbk={pbk}"
                if sid:
                    params += f"&sid={sid}"
                if sni:
                    params += f"&sni={sni}"
                if fp:
                    params += f"&fp={fp}"

            return f"vless://{client_uuid}@{self.server_ip}:{port}?{params}#{encoded_remark}"

        elif protocol == "vmess":
            import base64

            vmess_obj = {
                "v": "2",
                "ps": remark,
                "add": self.server_ip,
                "port": str(port),
                "id": client_uuid,
                "aid": "0",
                "scy": "auto",
                "net": network,
                "type": "none",
                "host": "",
                "path": "",
                "tls": security if security != "none" else "",
                "sni": "",
            }
            if network == "ws":
                ws = stream.get("wsSettings", {})
                vmess_obj["path"] = ws.get("path", "/")
                vmess_obj["host"] = ws.get("host", "")

            encoded = base64.b64encode(json.dumps(vmess_obj).encode()).decode()
            return f"vmess://{encoded}"

        return f"{protocol}://{client_uuid}@{self.server_ip}:{port}"

    async def reset_client_traffic(self, inbound_id: int, email: str):
        if not self.logged_in and not await self.login():
            return False
        email = _sanitize_email(email)
        paths = [
            f"/panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}",
            f"/xui/inbound/{inbound_id}/resetClientTraffic/{email}",
            f"/panel/api/clients/resetTraffic/{quote(email, safe='')}",
        ]
        for path in paths:
            try:
                res, body = await self._request("POST", path)
                if body.get("success"):
                    return True
            except Exception:
                continue
        return False

    async def update_client(
        self, inbound_id: int, client_uuid: str, email: str,
        total_gb: float = 0, expire_days: int = 30, limit_ip: int = 1,
    ):
        if not self.logged_in and not await self.login():
            return False

        email = _sanitize_email(email)
        expiry_time = int((time.time() + (expire_days * 86400)) * 1000) if expire_days > 0 else 0
        total_bytes = int(total_gb * 1073741824) if total_gb > 0 else 0

        payload = {
            "id": client_uuid,
            "email": email,
            "limitIp": limit_ip,
            "totalGB": total_bytes,
            "expiryTime": expiry_time,
            "enable": True,
            "tgId": 0,
            "subId": email,
        }
        try:
            res, body = await self._request(
                "POST",
                f"/panel/api/clients/update/{quote(email, safe='')}",
                json=payload,
            )
            if body.get("success"):
                return True
        except Exception:
            pass

        client_data = {
            "id": client_uuid,
            "flow": "",
            "email": email,
            "limitIp": limit_ip,
            "totalGB": total_bytes,
            "expiryTime": expiry_time,
            "enable": True,
            "tgId": "",
            "subId": email,
        }
        form_payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]}),
        }
        for path in (
            f"/panel/api/inbounds/updateClient/{client_uuid}",
            f"/xui/inbound/updateClient/{client_uuid}",
        ):
            try:
                res, body = await self._request("POST", path, data=form_payload)
                if body.get("success"):
                    return True
            except Exception:
                continue
        return False

    def build_subscription_url(self, sub_id: str, sub_path: str = "/sub/") -> str:
        path = (sub_path or "/sub/").strip()
        if not path.startswith("/"):
            path = "/" + path
        if not path.endswith("/"):
            path += "/"
        return f"{self.url}{path}{sub_id}"

    async def close(self):
        await self.session.aclose()
