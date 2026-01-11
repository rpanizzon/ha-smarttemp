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
        
        # Ensure the device is marked online whenever data arrives
        self.data[mac]["online"] = True
        
       # 1. Deep merge nested objects like 'sys_set' or 'zone1'
        for key, value in payload.items():
            if isinstance(value, dict) and key in self.data[mac] and isinstance(self.data[mac][key], dict):
                # Only update the specific sub-keys provided (e.g., just heatset)
                self.data[mac][key].update(value)
            else:
                # Top-level keys like 'equip_mode' or 'pair_key'
                self.data[mac][key] = value

        # Trigger discovery and state checks on 'pair_key'
        if "pair_key" in payload:
            zone_count = self.get_field(mac, "zone_no", 0)
            
            if zone_count > 0:
                # 1. Possible discovery: Check/Create entities for each zone
                for i in range(1, zone_count + 1):
                    self._check_and_signal(mac, i)
                
                # 2. Logic: Check if system should turn off (Zoned only)
                await self._check_system_off_logic(mac, payload)
            else:
                # Case: Non-Zoned Device - Check for dicovery
                self._check_and_signal(mac, 0)
        
        self.async_set_updated_data(self.data)

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
    
    async def _check_system_off_logic(self, mac, data):
        """Monitor the pair_key JSON and shut down if all zones are off."""
        # Current hardware state
        equip_mode = data.get("equip_mode")
        zone_count = data.get("zone_no", 0)

        # Only proceed if the system is currently running (not 0)
        if equip_mode != 0:
            all_off = True
            for i in range(1, zone_count + 1):
                # Accessing nested zone data: data['zone1']['onoff']
                zone_data = data.get(f"zone{i}", {})
                if zone_data.get("onoff") == 1:
                    all_off = False
                    break
            
            if all_off:
                _LOGGER.info("All zones reported OFF in JSON. Sending equip_mode: 0")
                # Trigger the hardware shutdown
                self.hass.async_create_task(
                    self.hub.send_smarttemp_command(mac, {"equip_mode": 0})
                )