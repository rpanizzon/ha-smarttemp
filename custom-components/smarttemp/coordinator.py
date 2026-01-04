import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, NEW_DEVICE_SIGNAL

_LOGGER = logging.getLogger(__name__)

class SmartTempCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, hub=None):
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.hub = hub
        self.hass = hass
        self.data = {}
        self.discovered_macs = set()

    async def async_process_json(self, mac, payload):
        if mac not in self.data:
            self.data[mac] = {}
        self.data[mac].update(payload)

        if "pair_key" in payload and mac not in self.discovered_macs:
            self.discovered_macs.add(mac)
            async_dispatcher_send(self.hass, NEW_DEVICE_SIGNAL, mac)
        else:
            self.async_set_updated_data(self.data)
            
    def get_field(self, mac, field, default=None):
        """Standard field fetcher."""
        return self.data.get(mac, {}).get(field, default)

    def get_room_temp(self, mac):
        """For non-zoned: dis_room_temp[0] / 10."""
        val = self.get_field(mac, "dis_room_temp")
        if isinstance(val, list) and len(val) > 0:
            return float(val[0]) / 10.0
        return None

    def get_zone_temp(self, mac, idx):
        """For zoned: dis_zone_temp[idx] / 10."""
        val = self.get_field(mac, "dis_zone_temp")
        if isinstance(val, list) and len(val) > idx:
            return float(val[idx]) / 10.0
        return None

    def get_humidity(self, mac):
        """For both: dis_room_humi[0]."""
        val = self.get_field(mac, "dis_room_humi")
        if isinstance(val, list) and len(val) > 0:
            return float(val[0])
        return None

    def get_temp(self, mac, field):
        """Generic scaled fetcher for simple fields (e.g., set_temp)."""
        val = self.get_field(mac, field)
        if isinstance(val, list) and len(val) > 0:
            val = val[0]
        try:
            return float(val) / 10.0 if val is not None else None
        except (TypeError, ValueError):
            return None