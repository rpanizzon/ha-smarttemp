import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, NEW_DEVICE_SIGNAL

_LOGGER = logging.getLogger(__name__)

class SmartTempCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SmartTemp data."""

    def __init__(self, hass, hub=None):
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.hub = hub
        self.hass = hass
        self.data = {}
        self.discovered_entities = set()

    async def async_process_json(self, mac, payload):
        """Process incoming JSON and signal entity discovery."""
        if mac not in self.data:
            self.data[mac] = {}
        
        self.data[mac].update(payload)

        # Trigger discovery when we receive the full configuration (pair_key)
        if "pair_key" in payload:
            zone_count = self.get_field(mac, "zone_no", 0)
            
            if zone_count > 0:
                # Case: Zoned Device
                # We skip Zone 0 and only create the named zones (1, 2...)
                _LOGGER.info("MAC %s is Zoned. Signaling %s zones.", mac, zone_count)
                for i in range(1, zone_count + 1):
                    self._check_and_signal(mac, i)
            else:
                # Case: Non-Zoned Device
                # We signal Zone 0 to represent the main system control
                _LOGGER.info("MAC %s is Non-Zoned. Signaling System (Zone 0).", mac)
                self._check_and_signal(mac, 0)
        
        self.async_set_updated_data(self.data)

    def _check_and_signal(self, mac, zone_idx):
        """Signal MAC + Zone Index to platforms."""
        entity_key = f"{mac}_{zone_idx}"
        if entity_key not in self.discovered_entities:
            self.discovered_entities.add(entity_key)
            # Sends (mac, zone_idx) to climate.py
            async_dispatcher_send(self.hass, NEW_DEVICE_SIGNAL, (mac, zone_idx))

    def get_field(self, mac, field, default=None):
        """
        Pure data fetcher. 
        Supports root fields: 'temp_min'
        Supports nested fields: 'sys_set:heatset' or 'zone1:heatset'
        """
        device_data = self.data.get(mac, {})
        
        if ":" in field:
            parent, child = field.split(":", 1)
            val = device_data.get(parent, {}).get(child, default)
        else:
            val = device_data.get(field, default)

        # Handle hardware tendency to return single values inside lists
        # Example: dis_room_humi: [70, 0, 0, 0]
        if isinstance(val, list) and len(val) > 0:
            return val[0]
            
        return val if val is not None else default

    def get_room_temp(self, mac, zone_idx):
        """
        Single source for all temperature lookups.
        Zone 0 -> dis_room_temp[0]
        Zone 1+ -> dis_zone_temp[zone_idx]
        """
        device_data = self.data.get(mac, {})
        
        if zone_idx == 0:
            # Use 'System' room temp list
            val = device_data.get("dis_room_temp")[0]
        else:
            # Use the 'Zone' temp list
            val = device_data.get("dis_zone_temp")[zone_idx-1]
        return val if val else 0

    def get_room_humidity(self, mac, zone_idx):
        """Although a list, there is only 1 humidity element. Zones 2 onward get same as zone 1."""
        val = self.data.get(mac, {}).get("dis_room_humi")
        return val[0] if val else 0
    
    async def check_and_shutdown_system(self, mac):
        """Monitor zones and turn off the main unit if all zones are 0."""
        device_data = self.data.get(mac, {})
        zone_statuses = device_data.get("dis_zone_onoff", [])

        # If all zones in the list are 0 (Off), shut down the main unit
        if all(status == 0 for status in zone_statuses):
            _LOGGER.info("All zones for %s are off. Shutting down system mode.", mac)
            await self.hub.send_smarttemp_command(mac, {"equip_mode": 0})