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
    FAN_HIGH,
    HVACAction
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
                        # Use SmartTempZone with is_dummy=True for master controllers
                        new_entities.append(SmartTempZone(coordinator, hub, entry.entry_id, device_mac, 0, is_dummy=True))
                    else:
                        for i in range(zone_count):
                            new_entities.append(SmartTempZone(coordinator, hub, entry.entry_id, device_mac, i, is_dummy=False))
                    
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
        self._is_zoned = not is_dummy # Added to fix missing attribute

        self._attr_unique_id = f"{entry_id}_{mac}_zone_{zone_idx}"
        
        raw_name = self.coordinator.get_field(self._mac, f"zone{self._zone_num}_name")
        self._attr_name = raw_name if (not is_dummy and raw_name) else "SmartTemp AC"
        
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, mac)}, name=f"SmartTemp {mac}")
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
        self._attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.FAN_MODE |
            ClimateEntityFeature.PRESET_MODE
        )
        self._attr_preset_modes = ["Auto Fan", "Continuous Fan"]

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data.get(self._mac, {})
        attrs = {
            "system_time": f"{data.get('hour')}:{data.get('min')}",
            "filter_days": data.get("filter_days"),
            "error_code": data.get("err_code"),
            "heat_status": "On" if data.get("heat_status") == 1 else "Off",
            "cool_status": "On" if data.get("cool_status") == 1 else "Off",
            "fan_speed_raw": data.get("fan_speed"),
        }

        if self._is_dummy:
            attrs.update({
                "target_heat_setpoint": self.coordinator.get_temp(self._mac, "heatset"),
                "target_cool_setpoint": self.coordinator.get_temp(self._mac, "coolset"),
                "program_enabled": "Manual" if data.get("progen") == 0 else "Program",
            })
        else:
            attrs.update({
                "zone_on_off": "On" if data.get(f"zone{self._zone_num}:onoff") == 1 else "Off",
            })
        return attrs

    @property
    def hvac_mode(self):
        if not self._is_dummy:
            status = self.coordinator.get_field(self._mac, f"zone{self._zone_num}:onoff", 0)
            if status == 0: return HVACMode.OFF
        mode = self.coordinator.get_field(self._mac, "equip_mode", 0)
        return MAP_SMARTTEMP_TO_HA.get(mode, HVACMode.OFF)

    @property
    def hvac_action(self):
        if self.hvac_mode == HVACMode.OFF: return HVACAction.OFF
        if self.coordinator.get_field(self._mac, "heat_status") == 1: return HVACAction.HEATING
        if self.coordinator.get_field(self._mac, "cool_status") == 1: return HVACAction.COOLING
        return HVACAction.IDLE

    @property
    def fan_mode(self):
        val = self.coordinator.get_field(self._mac, "fan_status", 0)
        mapping = {0: FAN_AUTO, 1: FAN_LOW, 2: FAN_MEDIUM, 3: FAN_HIGH}
        return mapping.get(val, FAN_AUTO)

    @property
    def current_temperature(self):
        if self._is_dummy: return self.coordinator.get_room_temp(self._mac)
        return self.coordinator.get_zone_temp(self._mac, self._zone_idx)
    
    @property
    def current_humidity(self):
        """Displays humidity on the climate card using your working coordinator helper."""
        return self.coordinator.get_humidity(self._mac)

    @property
    def target_temperature(self):
        field = "set_temp" if self._is_dummy else f"zone{self._zone_num}_set"
        return self.coordinator.get_temp(self._mac, field)

    @property
    def preset_mode(self):
        """Maps the 'fan_mode' field (0/1) from your doc to a readable preset."""
        policy = self.coordinator.get_field(self._mac, "fan_mode", 0)
        return "Continuous Fan" if policy == 1 else "Auto Fan"

    async def async_set_preset_mode(self, preset_mode: str):
        """Sends the command to toggle between Auto and Continuous fan."""
        val = 1 if preset_mode == "Continuous Fan" else 0
        await self.hub.send_smarttemp_command(self._mac, {"fan_mode": val})
        
    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode == HVACMode.OFF and self._is_zoned:
            await self.hub.send_smarttemp_command(self._mac, {f"zone{self._zone_num}:onoff": 0})
        elif self._is_zoned:
            await self.hub.send_smarttemp_command(self._mac, {
                f"zone{self._zone_num}:onoff": 1,
                "equip_mode": MAP_HA_TO_SMARTTEMP.get(hvac_mode, 0)
            })
        else:
            await self.hub.send_smarttemp_command(self._mac, {"equip_mode": MAP_HA_TO_SMARTTEMP.get(hvac_mode, 0)})

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp:
            field = "set_temp" if not self._is_zoned else f"zone{self._zone_num}_set"
            await self.hub.send_smarttemp_command(self._mac, {field: int(temp * 10)})