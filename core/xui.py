import httpx
import uuid
import json
import logging
import time
import re
import asyncio
from urllib.parse import urlparse, urljoin, quote

logger = logging.getLogger(__name__)

__version__ = "2.1.0-panel-inbound"

API_LEGACY = "legacy"          # /xui/inbound/*
API_3XUI_PANEL = "3xui_panel"  # /panel/inbound/*  (common on reverse-proxied 3x-ui)
API_3XUI = "3xui"              # /panel/api/inbounds/* or /panel/api/clients/*


def _sanitize_email(email: str) -> str:
    email = re.sub(r"[^a-zA-Z0-9_.@-]", "_", email)
    return email[:64] if len(email) > 64 else email


def _parse_json_response(res: httpx.Response) -> dict:
    text = (res.text or "").strip()
    if not text:
        return {
            "success": False,
            "msg": f"empty response (HTTP {res.status_code})",
            "status": res.status_code,
        }
    try:
        return res.json()
    except Exception:
        return {
            "success": False,
            "msg": f"non-JSON HTTP {res.status_code}: {text[:200]}",
            "status": res.status_code,
        }


class XUIApi:
    def __init__(self, url, username, password):
        url_clean = url.rstrip("/")
        for path_to_strip in (
            "/panel/api/inbounds",
            "/panel/api/inbound",
            "/panel/inbounds",
            "/panel/inbound",
            "/panel",
            "/inbounds",
            "/xui",
        ):
            if url_clean.endswith(path_to_strip):
                url_clean = url_clean[: -len(path_to_strip)]
        self.url = url_clean.rstrip("/")
        self.username = username
        self.password = password
        self.session = httpx.AsyncClient(
            verify=False,
            timeout=25.0,
            follow_redirects=False,
            headers={
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        self.logged_in = False
        self.api_mode = None
        self.server_ip = urlparse(self.url).hostname
        self._last_error = ""
        self.csrf_token = None

    @property
    def last_error(self) -> str:
        return self._last_error

    def _abs_url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.url}{path}"

    def _resolve_redirect(self, current_url: str, location: str) -> str:
        if not location:
            return current_url
        if location.startswith("http://") or location.startswith("https://"):
            return location
        parsed = urlparse(current_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if location.startswith("/"):
            return base + location
        return urljoin(current_url.rstrip("/") + "/", location)

    async def _get_csrf_token(self) -> str | None:
        try:
            res = await self.session.get(self._abs_url("/csrf-token"), headers={"X-Requested-With": "XMLHttpRequest"})
            body = _parse_json_response(res)
            if res.status_code == 200 and body.get("success"):
                self.csrf_token = body.get("obj")
                return self.csrf_token
        except Exception as e:
            logger.debug(f"Failed to fetch CSRF token: {e}")
        return None

    async def _post(self, path: str, max_redirects: int = 3, **kwargs) -> httpx.Response:
        """POST with manual redirect — keeps method and body (fixes 301 → empty JSON)."""
        if self.csrf_token:
            headers = kwargs.setdefault("headers", {})
            headers["X-CSRF-Token"] = self.csrf_token
        url = self._abs_url(path)
        res = await self.session.post(url, **kwargs)
        redirects = 0
        while res.status_code in (301, 302, 307, 308) and redirects < max_redirects:
            loc = res.headers.get("location")
            if not loc:
                break
            url = self._resolve_redirect(url, loc)
            logger.debug(f"POST redirect -> {url}")
            res = await self.session.post(url, **kwargs)
            redirects += 1
        return res

    async def _get(self, path: str, max_redirects: int = 3, **kwargs) -> httpx.Response:
        url = self._abs_url(path)
        res = await self.session.get(url, **kwargs)
        redirects = 0
        while res.status_code in (301, 302, 307, 308) and redirects < max_redirects:
            loc = res.headers.get("location")
            if not loc:
                break
            url = self._resolve_redirect(url, loc)
            res = await self.session.get(url, **kwargs)
            redirects += 1
        return res

    async def login(self):
        try:
            await self._get_csrf_token()
            res = await self._post("/login", data={"username": self.username, "password": self.password})
            body = _parse_json_response(res)
            if res.status_code == 200 and body.get("success"):
                self.logged_in = True
                await self._get_csrf_token()
                await self._detect_api_mode()
                logger.info(f"X-UI login OK mode={self.api_mode} base={self.url}")
                return True
            self._last_error = body.get("msg") or f"HTTP {res.status_code}"
            logger.error(f"X-UI Login failed: {body}")
            return False
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"X-UI Login exception: {e}")
            return False

    async def _detect_api_mode(self):
        probes = [
            (API_3XUI_PANEL, "/panel/inbound/list", "POST"),
            (API_3XUI, "/panel/api/inbounds/list", "GET"),
            (API_3XUI, "/panel/api/inbounds/list", "POST"),
            (API_LEGACY, "/xui/inbound/list", "POST"),
        ]
        for mode, path, method in probes:
            try:
                res = await self._get(path) if method == "GET" else await self._post(path)
                body = _parse_json_response(res)
                if res.status_code == 200 and body.get("success"):
                    self.api_mode = mode
                    logger.info(f"X-UI API mode detected: {mode} via {path} ({method})")
                    return
                if res.status_code == 200 and isinstance(body.get("obj"), list):
                    self.api_mode = mode
                    return
            except Exception as e:
                logger.debug(f"probe {path} ({method}): {e}")
        self.api_mode = API_3XUI_PANEL

    async def list_inbounds(self) -> list:
        if not self.logged_in and not await self.login():
            return []

        paths_by_mode = {
            API_3XUI_PANEL: [("/panel/inbound/list", "POST")],
            API_3XUI: [("/panel/api/inbounds/list", "GET"), ("/panel/api/inbounds/list", "POST")],
            API_LEGACY: [("/xui/inbound/list", "POST")],
        }
        paths = paths_by_mode.get(self.api_mode, [])
        paths += [p for m, ps in paths_by_mode.items() for p in ps if p not in paths]

        for path, method in paths:
            try:
                res = await self._get(path) if method == "GET" else await self._post(path)
                body = _parse_json_response(res)
                if body.get("success"):
                    obj = body.get("obj") or body.get("data") or []
                    if isinstance(obj, list):
                        if "/panel/inbound" in path:
                            self.api_mode = API_3XUI_PANEL
                        elif "/panel/api/" in path:
                            self.api_mode = API_3XUI
                        elif "/xui/" in path:
                            self.api_mode = API_LEGACY
                        return obj
            except Exception as e:
                logger.debug(f"list_inbounds {path} ({method}): {e}")
        return []

    async def get_inbound(self, inbound_id: int):
        if not self.logged_in and not await self.login():
            return None
        for inb in await self.list_inbounds():
            if int(inb.get("id", -1)) == int(inbound_id):
                return inb
        for path in (
            f"/panel/api/inbounds/get/{inbound_id}",
            f"/panel/inbound/get/{inbound_id}",
        ):
            try:
                res = await self._get(path)
                body = _parse_json_response(res)
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
        except Exception:
            pass
        return ""

    def get_client_stats_by_email(self, email: str) -> dict:
        """Get client stats (traffic used/total) by email from cached inbounds list."""
        for inb in self._inbounds_cache:
            for cs in inb.get("clientStats", []):
                if cs.get("email") == email:
                    return cs
        return {}

    async def get_all_client_stats(self) -> list[dict]:
        """Get all client stats from the panel for usage tracking."""
        inbounds = await self.list_inbounds()
        stats = []
        for ib in inbounds:
            for cs in ib.get("clientStats", []):
                stats.append(cs)
        return stats

    async def add_client(
        self, inbound_id: int, email: str, total_gb: float = 0, expire_days: int = 30, limit_ip: int = 1
    ):
        if not self.logged_in and not await self.login():
            return None

        email = _sanitize_email(email)
        inbound = await self.get_inbound(inbound_id)
        inbounds_list = await self.list_inbounds()
        if not inbound:
            ids = [i.get("id") for i in inbounds_list]
            if ids and int(inbound_id) not in [int(i) for i in ids if i is not None]:
                self._last_error = f"inbound {inbound_id} not found. Available: {ids}"
                logger.error(self._last_error)
                return None
            logger.warning(f"inbound {inbound_id} not in list (available {ids}), trying addClient anyway")
            inbound = inbounds_list[0] if inbounds_list else {"id": inbound_id, "protocol": "vless"}

        client_uuid = str(uuid.uuid4())
        expiry_time = int((time.time() + (expire_days * 86400)) * 1000) if expire_days > 0 else 0
        total_bytes = int(total_gb * 1073741824) if total_gb > 0 else 0
        flow = self._inbound_needs_flow(inbound) if inbound else ""
        # Email is subscription ID for later requests
        sub_id = email

        strategies = [
            self._add_client_panel_inbound,
            self._add_client_3xui_api_form,
            self._add_client_modern,
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
                await asyncio.sleep(1.2)

        logger.error(f"X-UI addClient all failed: {self._last_error}")
        return None

    def _client_payload(self, client_uuid, email, total_bytes, expiry_time, limit_ip, flow, sub_id):
        return {
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

    async def _add_client_panel_inbound(
        self, inbound_id, email, client_uuid, total_bytes, expiry_time, limit_ip, flow, sub_id
    ):
        """POST /panel/inbound/addClient — matches sayradical / reverse-proxy panels."""
        client_data = self._client_payload(
            client_uuid, email, total_bytes, expiry_time, limit_ip, flow, sub_id
        )
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]}),
        }
        try:
            res = await self._post("/panel/inbound/addClient", data=payload)
            body = _parse_json_response(res)
            if res.status_code == 200 and (body.get("success") or (not (res.text or "").strip())):
                self.api_mode = API_3XUI_PANEL
                logger.info(f"X-UI client created (/panel/inbound/addClient): {email}")
                return client_uuid
            self._last_error = f"[panel/inbound] HTTP {res.status_code}: {body.get('msg') or body}"
        except Exception as e:
            self._last_error = f"[panel/inbound] {e}"
        return None

    async def _add_client_3xui_api_form(
        self, inbound_id, email, client_uuid, total_bytes, expiry_time, limit_ip, flow, sub_id
    ):
        client_data = self._client_payload(
            client_uuid, email, total_bytes, expiry_time, limit_ip, flow, sub_id
        )
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]}),
        }
        try:
            res = await self._post("/panel/api/inbounds/addClient", data=payload)
            body = _parse_json_response(res)
            if res.status_code == 200 and body.get("success"):
                self.api_mode = API_3XUI
                logger.info(f"X-UI client created (/panel/api/inbounds/addClient): {email}")
                return client_uuid
            self._last_error = f"[api/inbounds] HTTP {res.status_code}: {body.get('msg') or body}"
        except Exception as e:
            self._last_error = f"[api/inbounds] {e}"
        return None

    async def _add_client_modern(
        self, inbound_id, email, client_uuid, total_bytes, expiry_time, limit_ip, flow, sub_id
    ):
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
            res = await self._post("/panel/api/clients/add", json=payload)
            body = _parse_json_response(res)
            if res.status_code == 200 and body.get("success"):
                self.api_mode = API_3XUI
                logger.info(f"X-UI client created (/panel/api/clients/add): {email}")
                return client_uuid
            self._last_error = f"[clients/add] HTTP {res.status_code}: {body.get('msg') or body}"
        except Exception as e:
            self._last_error = f"[clients/add] {e}"
        return None

    async def _add_client_legacy(
        self, inbound_id, email, client_uuid, total_bytes, expiry_time, limit_ip, flow, sub_id
    ):
        client_data = self._client_payload(
            client_uuid, email, total_bytes, expiry_time, limit_ip, flow, sub_id
        )
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]}),
        }
        try:
            res = await self._post("/xui/inbound/addClient", data=payload)
            body = _parse_json_response(res)
            if res.status_code == 200 and body.get("success"):
                self.api_mode = API_LEGACY
                logger.info(f"X-UI client created (/xui/inbound/addClient): {email}")
                return client_uuid
            self._last_error = f"[xui] HTTP {res.status_code}: {body.get('msg') or body}"
        except Exception as e:
            self._last_error = f"[xui] {e}"
        return None

    async def get_client_links(self, email: str) -> list[str]:
        if not self.logged_in and not await self.login():
            return []
        email = _sanitize_email(email)
        paths = [
            f"/panel/api/clients/links/{quote(email, safe='')}",
            f"/panel/inbound/getClientLinks/{quote(email, safe='')}",
        ]
        for path in paths:
            try:
                res = await self._get(path)
                body = _parse_json_response(res)
                if body.get("success"):
                    obj = body.get("obj") or body.get("data") or []
                    if isinstance(obj, list):
                        return [str(x).strip() for x in obj if x]
                    if isinstance(obj, str) and obj.strip():
                        return [obj.strip()]
            except Exception as e:
                logger.debug(f"get_client_links {path}: {e}")
        return []

    async def get_client_subscription_id(self, inbound_id: int, email: str) -> str | None:
        """Get subscription ID (subId) for a client from the panel."""
        if not self.logged_in and not await self.login():
            return None

        email = _sanitize_email(email)
        try:
            # Refresh inbound data to get latest client info
            inbound = await self.get_inbound(inbound_id)
            if not inbound:
                logger.warning(f"Could not get inbound {inbound_id}")
                return None

            # Look through clientStats to find matching email
            for client_stat in inbound.get("clientStats", []):
                if client_stat.get("email") == email:
                    sub_id = client_stat.get("subId")
                    if sub_id:
                        logger.info(f"Found subscription ID for {email}: {sub_id}")
                        return str(sub_id)

            logger.warning(f"Client stats not found for email {email} in inbound {inbound_id}")
        except Exception as e:
            logger.warning(f"Error getting client subscription ID: {e}")

        return None

    async def build_direct_link(self, inbound_id: int, client_uuid: str, remark: str):
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return None

        protocol = inbound.get("protocol", "vless")
        port = inbound.get("port", 443)
        stream = (
            json.loads(inbound["streamSettings"])
            if isinstance(inbound.get("streamSettings"), str)
            else (inbound.get("streamSettings") or {})
        )

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
                params += f"&serviceName={grpc.get('serviceName', '')}"
            elif network == "tcp":
                tcp = stream.get("tcpSettings", {})
                header_type = tcp.get("header", {}).get("type", "none")
                params += f"&headerType={header_type}"

            if security == "tls":
                tls = stream.get("tlsSettings", {})
                if tls.get("serverName"):
                    params += f"&sni={tls['serverName']}"
                if tls.get("fingerprint"):
                    params += f"&fp={tls['fingerprint']}"
            elif security == "reality":
                real = stream.get("realitySettings", {})
                flow = self._inbound_needs_flow(inbound)
                if flow:
                    params += f"&flow={flow}"
                if real.get("publicKey"):
                    params += f"&pbk={real['publicKey']}"
                if real.get("shortId"):
                    params += f"&sid={real['shortId']}"
                sni = real.get("serverNames", [""])[0] if real.get("serverNames") else ""
                if sni:
                    params += f"&sni={sni}"
                if real.get("fingerprint"):
                    params += f"&fp={real['fingerprint']}"

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
            f"/panel/inbound/{inbound_id}/resetClientTraffic/{email}",
            f"/panel/api/inbounds/{inbound_id}/resetClientTraffic/{email}",
            f"/xui/inbound/{inbound_id}/resetClientTraffic/{email}",
            f"/panel/api/clients/resetTraffic/{quote(email, safe='')}",
        ]
        for path in paths:
            try:
                res = await self._post(path)
                body = _parse_json_response(res)
                if body.get("success"):
                    return True
            except Exception:
                continue
        return False

    async def update_client(
        self, inbound_id: int, client_uuid: str, email: str,
        total_gb: float = 0, expire_days: int = 30, limit_ip: int = 1,
        reset_first: bool = False,
    ):
        if not self.logged_in and not await self.login():
            return False

        email = _sanitize_email(email)

        if reset_first:
            await self.reset_client_traffic(inbound_id, email)

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
            res = await self._post(f"/panel/api/clients/update/{quote(email, safe='')}", json=payload)
            body = _parse_json_response(res)
            if body.get("success"):
                return True
        except Exception:
            pass

        form_payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [self._client_payload(
                client_uuid, email, total_bytes, expiry_time, limit_ip, "", email
            )]}),
        }
        for path in (
            f"/panel/inbound/updateClient/{client_uuid}",
            f"/panel/api/inbounds/updateClient/{client_uuid}",
            f"/xui/inbound/updateClient/{client_uuid}",
        ):
            try:
                res = await self._post(path, data=form_payload)
                body = _parse_json_response(res)
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
        url = self.url
        if ":8000" in url or ":8001" in url:
            url = url.replace(":8000", ":2096").replace(":8001", ":2096")
        # Preserve any path component in the configured base URL (some panels host at a subpath/token)
        parsed = urlparse(url.rstrip("/"))
        base_path = parsed.path.rstrip("/") if parsed.path else ""
        base = f"{parsed.scheme}://{parsed.netloc}{base_path}"
        # Ensure sub_id is safely quoted for inclusion in URL path
        if sub_id is None:
            return f"{base}{path}"
        return f"{base}{path}{quote(str(sub_id), safe='')}"

    async def close(self):
        await self.session.aclose()
