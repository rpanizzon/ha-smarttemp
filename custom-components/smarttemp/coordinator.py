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
        """Process incoming JSON with gated availability and logic checks."""
        # 1. Gated Handshake: Initialization via pair_key
        if "pair_key" in payload:
            if mac not in self.data:
                self.data[mac] = {}
            
            self.data[mac]["online"] = True
            
            zone_count = payload.get("zone_no", 0)
            if zone_count > 0:
                for i in range(1, zone_count + 1):
                    self._check_and_signal(mac, i)
            else:
                self._check_and_signal(mac, 0)

        # 2. Block processing if we haven't received a pair_key yet
        if not self.data.get(mac, {}).get("online"):
            return

        # 3. Data Processing and "Off" Event Detection
        any_zone_turned_off = False
        
        for key, value in payload.items():
            # Deep merge logic
            if isinstance(value, dict) and key in self.data[mac] and isinstance(self.data[mac][key], dict):
                self.data[mac][key].update(value)
            else:
                self.data[mac][key] = value

            # Running check: Did this payload contain a zone turning off?
            if key.startswith("zone") and isinstance(value, dict):
                if value.get("onoff") == 0:
                    any_zone_turned_off = True

        # 4. Final state push to HA
        self.async_set_updated_data(self.data)

        # 5. System Off Logic: Triggered by a zone turn-off event or pair_key update
        if any_zone_turned_off:
            # We perform a full memory check to verify the 'Last Man Standing'
            await self._check_system_off_logic(mac)
            
    def _check_and_signal(self, mac, zone_idx):
        """Signal MAC + Zone Index once per entity."""
        entity_key = f"{mac}_{zone_idx}"
        if entity_key not in self.discovered_entities:
            # Only logs once per entity creation
            _LOGGER.info("Creating entity: MAC %s, Zone %s", mac, zone_idx)
            self.discovered_entities.add(entity_key)
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
    
    async def _check_system_off_logic(self, mac):
        """Perform a full system sweep to see if we should shut down the master."""
        device_data = self.data.get(mac, {})
        equip_mode = device_data.get("equip_mode")
        zone_count = device_data.get("zone_no", 0)

        # Only proceed if the master unit is actually running
        if equip_mode is not None and equip_mode != 0:
            still_running = False
            for i in range(1, zone_count + 1):
                zone_key = f"zone{i}"
                if device_data.get(zone_key, {}).get("onoff") == 1:
                    still_running = True
                    break
            
            if not still_running:
                _LOGGER.info("MAC %s: Full check confirmed all zones OFF. Shutting down Master.", mac)
                # Dispatch shutdown command via Hub
                self.hass.async_create_task(
                    self.hub.send_smarttemp_command(mac, {"equip_mode": 0})
                )