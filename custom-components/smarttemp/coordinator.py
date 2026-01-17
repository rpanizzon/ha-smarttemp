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
        """
        Refined 2-Phase Logic:
        1. If pair_key: Register entities, merge data, and decide between fetching Part 2 or Activating.
        2. If regular JSON: Merge and refresh only if entities already exist.
        """
        _LOGGER.debug("Processing payload for %s: %s", mac, payload)

        if "pair_key" in payload:
            # 1. Registration: Is this a new device?
            # Get zone_count outside the conditional so it is always available
            zone_count = int(payload.get("zone_no", self.data.get(mac, {}).get("zone_no", 0)))
            
            if mac not in self.data:
                _LOGGER.info("MAC %s: New device detected. Initiating entity creation.", mac)
                if zone_count == 0:
                    self._check_and_signal(mac, 0)
                else:
                    for i in range(1, zone_count + 1):
                        self._check_and_signal(mac, i)
                # Initialize with online=False so regular updates are ignored until Activation
                self.data[mac] = {"online": False, "zone_no": zone_count}
            
            # 2. Merge Data 
            self._deep_merge(self.data[mac], payload)    
            
            # 3. Check if it's Part 1 (no setpoints)
            has_setpoints = "sys_set" in payload or "zone1" in payload
            
            if not has_setpoints:
                _LOGGER.info("MAC %s: Part 1 pair_key. Fetching Part 2.", mac)
                if zone_count == 0:
                    await self.hub.send_smarttemp_command(mac, {
                        "pair_key": "", 
                        "sys_set": {"heatset": "", "coolset": ""}
                    })
                else:
                    # Includes zoneX_name to restore zone names 
                    zone_query = {"pair_key": ""}
                    for i in range(1, zone_count + 1):
                        zone_query[f"zone{i}"] = {"onoff": "", "heatset": "", "coolset": ""}
                        zone_query[f"zone{i}_name"] = "" 
                    await self.hub.send_smarttemp_command(mac, zone_query)
            else:
                # 4. Activation: Must be a full or Part 2 pair_key
                if not self.data[mac].get("online"):
                    _LOGGER.info("MAC %s: Full/Part 2 received. Activating.", mac)
                    self.data[mac]["online"] = True
                self.async_set_updated_data(self.data)

        else:
            # Must be a normal JSON command
            # Ensure mac exists in data AND is online before processing
            device_entry = self.data.get(mac)
            if device_entry and device_entry.get("online"):
                _LOGGER.debug("MAC %s: Regular update received.", mac)
                self._deep_merge(self.data[mac], payload)
                self.async_set_updated_data(self.data)
        return
      
    def _deep_merge(self, target, source):
        """Recursively merge dictionary source into target."""
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value

    def _check_and_signal(self, mac, zone_index):
        """Signals HA to create entities via a tracked HA Task."""
        signal_key = f"{mac}_zone{zone_index}"
        if signal_key not in self.discovered_entities:
            _LOGGER.info("MAC %s: Creating HA Task for zone %s discovery", mac, zone_index)
            
            # Inner async function to bridge the gap
            async def trigger_discovery():
                async_dispatcher_send(self.hass, NEW_DEVICE_SIGNAL, mac, zone_index)

            # THE FIX: Create a tracked task on the HA loop
            self.hass.async_create_task(trigger_discovery())
            
            self.discovered_entities.add(signal_key)
                    
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