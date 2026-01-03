import logging
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import (
    DOMAIN,
    MAP_HA_TO_SMARTTEMP,
    MAP_SMARTTEMP_TO_HA,
    NEW_DEVICE_SIGNAL
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    hub = data["hub"]
    known_devices = set()

    def add_new_entities(mac=None):
        async def _async_task():
            new_entities = []
            target_macs = [mac] if mac else [m for m, d in coordinator.data.items() if "pair_key" in d]

            for device_mac in target_macs:
                if device_mac not in known_devices:
                    device_data = coordinator.data.get(device_mac, {})
                    zone_count = device_data.get("zone_no", 0)
                    if isinstance(zone_count, list): zone_count = zone_count[0]

                    if zone_count == 0:
                        _LOGGER.info("Creating Master AC entity for %s", device_mac)
                        new_entities.append(SmartTempZone(coordinator, hub, entry.entry_id, device_mac, 0, is_dummy=True))
                    else:
                        for i in range(zone_count):
                            _LOGGER.info("Creating Zone %d entity for %s", i + 1, device_mac)
                            new_entities.append(SmartTempZone(coordinator, hub, entry.entry_id, device_mac, i))
                    
                    known_devices.add(device_mac)

            if new_entities:
                async_add_entities(new_entities)

        hass.add_job(_async_task())

    entry.async_on_unload(async_dispatcher_connect(hass, NEW_DEVICE_SIGNAL, add_new_entities))
    add_new_entities()

class SmartTempZone(CoordinatorEntity, ClimateEntity):
    def __init__(self, coordinator, hub, entry_id, mac, zone_idx, is_dummy=False):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.hub = hub
        self._mac = mac
        self._zone_idx = zone_idx
        self._zone_num = zone_idx + 1
        self._is_dummy = is_dummy

        self._attr_unique_id = f"{entry_id}_{mac}_zone_{zone_idx}"
        self._attr_name = "SmartTemp AC" if is_dummy else f"Zone {self._zone_num}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, mac)}, name=f"SmartTemp {mac}")
        
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
        self._attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        self._attr_preset_modes = ["Auto Fan", "Continuous Fan"]
        
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.FAN_MODE |
            ClimateEntityFeature.PRESET_MODE
        )

    @property
    def hvac_mode(self):
        return MAP_SMARTTEMP_TO_HA.get(self.coordinator.get_field(self._mac, "equip_mode", 0), HVACMode.OFF)

    @property
    def current_temperature(self):
        """Handle logic for both Dummy (Main) and Zone temperatures."""
        # 1. Try to get the value from the coordinator
        if self._is_dummy:
            # For non-zoned units, this is the 'Main Room Temp'
            temp = self.coordinator.get_temp(self._mac, "dis_room_temp")
        else:
            # For zoned units, this is the index in the 'dis_zonetemp' array
            temp = self.coordinator.get_zone_temp(self._mac, self._zone_idx)

        # 2. DEBUG: If it's still None, log it so we can see the raw data
        if temp is None:
            _LOGGER.debug("Temperature is None for %s (Dummy: %s)", self._mac, self._is_dummy)
        
        return temp

    @property
    def current_humidity(self):
        return self.coordinator.get_humidity(self._mac)

    @property
    def target_temperature(self):
        field = "set_temp" if self._is_dummy else f"zone{self._zone_num}_set"
        return self.coordinator.get_temp(self._mac, field)

    @property
    def fan_mode(self):
        val = self.coordinator.get_field(self._mac, "fan_status", 0)
        mapping = {0: FAN_AUTO, 1: FAN_LOW, 2: FAN_MEDIUM, 3: FAN_HIGH}
        return mapping.get(val, FAN_AUTO)

    @property
    def preset_mode(self):
        policy = self.coordinator.get_field(self._mac, "fan_mode", 0)
        if isinstance(policy, list):
            policy = policy[0] if policy else 0
        return "Continuous Fan" if policy == 1 else "Auto Fan"

    async def async_set_hvac_mode(self, hvac_mode):
        st_mode = MAP_HA_TO_SMARTTEMP.get(hvac_mode, 0)
        await self.hub.send_smarttemp_command(self._mac, {"equip_mode": st_mode})

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp:
            field = "set_temp" if self._is_dummy else f"zone{self._zone_num}_set"
            await self.hub.send_smarttemp_command(self._mac, {field: int(temp * 10)})

    async def async_set_fan_mode(self, fan_mode):
        mapping = {FAN_AUTO: 0, FAN_LOW: 1, FAN_MEDIUM: 2, FAN_HIGH: 3}
        await self.hub.send_smarttemp_command(self._mac, {"fan_status": mapping.get(fan_mode, 0)})

    async def async_set_preset_mode(self, preset_mode):
        val = 1 if preset_mode == "Continuous Fan" else 0
        await self.hub.send_smarttemp_command(self._mac, {"fan_mode": val})

    @property
    def min_temp(self): return 16.0
    @property
    def max_temp(self): return 32.0
    @property
    def target_temperature_step(self): return 0.5