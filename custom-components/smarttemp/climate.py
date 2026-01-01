import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode, ClimateEntityFeature, FAN_ON, FAN_OFF
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import (
    DOMAIN, MAP_HA_TO_SMARTTEMP, MAP_SMARTTEMP_TO_HA, 
    TEMP_SCALE_FACTOR, ZONE_ON
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Climate entities based on discovered devices."""
    data = hass.data[DOMAIN][entry.entry_id]
    hub = data["hub"]
    coordinator = data["coordinator"]

    # We use a listener to detect when a new MAC address first sends data
    def discover_entities():
        if not coordinator.data:
            return []
        
        entities = []
        for mac, device_data in coordinator.data.items():
            # Check if we've already added this device (simplified for this example)
            # In a production version, you'd track added_macs
            
            # Add Main Unit
            entities.append(SmartTempAC(coordinator, hub, mac))
            
            # Add Zones if applicable (zone_no > 0)
            zone_count = device_data.get("zone_no", 0)
            for i in range(1, zone_count + 1):
                entities.append(SmartTempZone(coordinator, hub, mac, i))
        return entities

    # Initial add
    async_add_entities(discover_entities())

class SmartTempAC(ClimateEntity):
    """Main AC Unit Entity."""

    def __init__(self, coordinator, hub, mac):
        self.coordinator = coordinator
        self.hub = hub
        self._mac = mac
        self._attr_unique_id = f"{mac}_main"
        self._attr_name = f"SmartTemp AC {mac[-4:]}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        )

    @property
    def should_poll(self): return False

    @property
    def available(self):
        return self._mac in self.hub.active_connections

    @property
    def current_temperature(self):
        return self.coordinator.get_temp(self._mac, "dis_sys_temp")

    @property
    def hvac_mode(self):
        mode_int = self.coordinator.get_field(self._mac, "equip_mode")
        return MAP_SMARTTEMP_TO_HA.get(mode_int, HVACMode.OFF)

    @property
    def target_temperature_high(self):
        return self.coordinator.get_temp(self._mac, "coolset")

    @property
    def target_temperature_low(self):
        return self.coordinator.get_temp(self._mac, "heatset")

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        mode_int = MAP_HA_TO_SMARTTEMP.get(hvac_mode, 0)
        await self.hub.send_smarttemp_command(self._mac, {"equip_mode": mode_int})
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        payload = {}
        if "target_temp_high" in kwargs:
            payload["coolset"] = int(kwargs["target_temp_high"] * TEMP_SCALE_FACTOR)
        if "target_temp_low" in kwargs:
            payload["heatset"] = int(kwargs["target_temp_low"] * TEMP_SCALE_FACTOR)
        
        if payload:
            await self.hub.send_smarttemp_command(self._mac, payload)
            await self.coordinator.async_request_refresh()

    async def async_added_to_hass(self):
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))