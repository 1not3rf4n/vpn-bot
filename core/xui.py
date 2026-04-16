import httpx
import uuid
import json
import logging
import time
from urllib.parse import urlparse, quote

logger = logging.getLogger(__name__)

class XUIApi:
    def __init__(self, url, username, password):
        self.url = url.rstrip('/')
        self.username = username
        self.password = password
        self.session = httpx.AsyncClient(verify=False, timeout=15.0)
        self.logged_in = False
        self.server_ip = urlparse(url).hostname

    async def login(self):
        try:
            res = await self.session.post(
                f"{self.url}/login",
                data={"username": self.username, "password": self.password}
            )
            if res.status_code == 200:
                body = res.json()
                if body.get('success'):
                    self.logged_in = True
                    return True
                else:
                    logger.error(f"X-UI Login failed: {body}")
            else:
                logger.error(f"X-UI Login HTTP {res.status_code}")
            return False
        except Exception as e:
            logger.error(f"X-UI Login exception: {e}")
            return False

    async def get_inbound(self, inbound_id: int):
        """Fetch a specific inbound's full config."""
        if not self.logged_in:
            if not await self.login():
                return None
        try:
            res = await self.session.post(f"{self.url}/xui/inbound/list")
            body = res.json()
            if body.get('success'):
                for inb in body.get('obj', []):
                    if inb['id'] == inbound_id:
                        return inb
        except Exception as e:
            logger.error(f"X-UI get_inbound exception: {e}")
        return None

    async def add_client(self, inbound_id: int, email: str, total_gb: float = 0, expire_days: int = 30, limit_ip: int = 1):
        """
        Add a client to a specific inbound.
        Returns the created UUID, or None if failed.
        """
        if not self.logged_in:
            if not await self.login():
                return None
            
        client_uuid = str(uuid.uuid4())
        
        expiry_time = int((time.time() + (expire_days * 86400)) * 1000) if expire_days > 0 else 0
        total_bytes = int(total_gb * 1073741824) if total_gb > 0 else 0
        
        client_data = {
            "id": client_uuid,
            "flow": "",
            "email": email,
            "limitIp": limit_ip,
            "totalGB": total_bytes,
            "expiryTime": expiry_time,
            "enable": True,
            "tgId": "",
            "subId": email
        }
        
        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]})
        }
        
        try:
            res = await self.session.post(
                f"{self.url}/xui/inbound/addClient",
                json=payload
            )
            body = res.json()
            if res.status_code == 200 and body.get('success'):
                logger.info(f"X-UI client created: uuid={client_uuid}, email={email}")
                return client_uuid
            else:
                logger.error(f"X-UI addClient failed: {body}")
                return None
        except Exception as e:
            logger.error(f"X-UI addClient exception: {e}")
            return None

    async def build_direct_link(self, inbound_id: int, client_uuid: str, remark: str):
        """
        Build a direct vless:// or vmess:// link from inbound config.
        """
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            return None
        
        protocol = inbound.get('protocol', 'vless')
        port = inbound.get('port', 443)
        stream = json.loads(inbound['streamSettings']) if isinstance(inbound['streamSettings'], str) else inbound['streamSettings']
        
        network = stream.get('network', 'tcp')
        security = stream.get('security', 'none')
        
        encoded_remark = quote(remark)
        
        if protocol == 'vless':
            params = f"type={network}&security={security}"
            
            if network == 'ws':
                ws = stream.get('wsSettings', {})
                path = quote(ws.get('path', '/'))
                host = ws.get('host', '')
                params += f"&path={path}"
                if host:
                    params += f"&host={host}"
            elif network == 'grpc':
                grpc = stream.get('grpcSettings', {})
                sn = grpc.get('serviceName', '')
                params += f"&serviceName={sn}"
            elif network == 'tcp':
                tcp = stream.get('tcpSettings', {})
                header_type = tcp.get('header', {}).get('type', 'none')
                params += f"&headerType={header_type}"
                
            if security == 'tls':
                tls = stream.get('tlsSettings', {})
                sni = tls.get('serverName', '')
                fp = tls.get('fingerprint', '')
                if sni: params += f"&sni={sni}"
                if fp: params += f"&fp={fp}"
            elif security == 'reality':
                real = stream.get('realitySettings', {})
                pbk = real.get('publicKey', '')
                sid = real.get('shortId', '')
                sni = real.get('serverNames', [''])[0] if real.get('serverNames') else ''
                fp = real.get('fingerprint', '')
                if pbk: params += f"&pbk={pbk}"
                if sid: params += f"&sid={sid}"
                if sni: params += f"&sni={sni}"
                if fp: params += f"&fp={fp}"
            
            # Build: vless://uuid@ip:port?params#remark
            link = f"vless://{client_uuid}@{self.server_ip}:{port}?{params}#{encoded_remark}"
            return link
        
        elif protocol == 'vmess':
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
                "tls": security if security != 'none' else "",
                "sni": ""
            }
            if network == 'ws':
                ws = stream.get('wsSettings', {})
                vmess_obj['path'] = ws.get('path', '/')
                vmess_obj['host'] = ws.get('host', '')
                
            encoded = base64.b64encode(json.dumps(vmess_obj).encode()).decode()
            return f"vmess://{encoded}"
        
        # Fallback
        return f"{protocol}://{client_uuid}@{self.server_ip}:{port}"

    async def reset_client_traffic(self, inbound_id: int, email: str):
        """Reset traffic for a client (by email)."""
        if not self.logged_in:
            if not await self.login():
                return False
        try:
            res = await self.session.post(
                f"{self.url}/xui/inbound/{inbound_id}/resetClientTraffic/{email}"
            )
            body = res.json()
            if body.get('success'):
                logger.info(f"X-UI traffic reset for {email}")
                return True
            logger.error(f"X-UI resetTraffic failed: {body}")
            return False
        except Exception as e:
            logger.error(f"X-UI resetTraffic exception: {e}")
            return False

    async def update_client(self, inbound_id: int, client_uuid: str, email: str,
                            total_gb: float = 0, expire_days: int = 30, limit_ip: int = 1):
        """Update an existing client's settings (volume, expiry, etc)."""
        if not self.logged_in:
            if not await self.login():
                return False

        expiry_time = int((time.time() + (expire_days * 86400)) * 1000) if expire_days > 0 else 0
        total_bytes = int(total_gb * 1073741824) if total_gb > 0 else 0

        client_data = {
            "id": client_uuid,
            "flow": "",
            "email": email,
            "limitIp": limit_ip,
            "totalGB": total_bytes,
            "expiryTime": expiry_time,
            "enable": True,
            "tgId": "",
            "subId": email
        }

        payload = {
            "id": inbound_id,
            "settings": json.dumps({"clients": [client_data]})
        }

        try:
            res = await self.session.post(
                f"{self.url}/xui/inbound/updateClient/{client_uuid}",
                json=payload
            )
            body = res.json()
            if body.get('success'):
                logger.info(f"X-UI client updated: {email}")
                return True
            logger.error(f"X-UI updateClient failed: {body}")
            return False
        except Exception as e:
            logger.error(f"X-UI updateClient exception: {e}")
            return False

    async def close(self):
        await self.session.aclose()
