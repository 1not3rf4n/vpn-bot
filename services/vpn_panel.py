# services/vpn_panel.py
import httpx
import logging

class VPNPanelService:
    """
    Mock Service / Integration for Marzban / X-UI
    To be activated later by Admin Settings.
    """
    def __init__(self, api_url=None, api_key=None, panel_type="MARZBAN"):
        self.api_url = api_url
        self.api_key = api_key
        self.panel_type = panel_type
        
    async def create_user(self, username, data_limit=0, expire_days=30):
        """
        Creates user in panel and returns the config link.
        """
        logging.info(f"Creating user {username} on {self.panel_type} (MOCK)")
        # If real, here we call: await client.post(self.api_url + '/api/user', ...)
        return f"vless://mock-uuid-1234@mock.server.com:443?type=tcp#{username}"
        
    async def get_user_status(self, username):
        """
        Fetches current usage and expiration from panel.
        """
        return {"used_traffic": '2 GB', "expire": '25 Days Left', "status": "active"}

vpn_panel = VPNPanelService() # Singleton
