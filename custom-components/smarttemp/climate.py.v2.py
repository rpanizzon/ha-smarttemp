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
                        _LOGGER.info("Detected Non-Zoned Controller: %s", device_mac)
                        new_entities.append(SmartTempClimate(coordinator, hub, entry.entry_id, device_mac, is_zoned=False))
                    else:
                        _LOGGER.info("Detected Zoned Controller (%s zones): %s", zone_count, device_mac)
                        for i in range(zone_count):
                            new_entities.append(SmartTempClimate(coordinator, hub, entry.entry_id, device_mac, is_zoned=True, zone_idx=i))
                    
                    known_devices.add(device_mac)

            if new_entities:
                async_add_entities(new_entities)

        hass.add_job(_async_task())

    entry.async_on_unload(async_dispatcher_connect(hass, NEW_DEVICE_SIGNAL, add_new_entities))
    add_new_entities()

class SmartTempClimate(CoordinatorEntity, ClimateEntity):
    """Unified Climate class for Zoned and Non-Zoned SmartTemp Controllers."""

    def __init__(self, coordinator, hub, entry_id, mac, is_zoned=False, zone_idx=0):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.hub = hub
        self._mac = mac
        self._is_zoned = is_zoned
        self._zone_idx = zone_idx
        self._zone_num = zone_idx + 1

        self._attr_unique_id = f"{entry_id}_{mac}_z{zone_idx}" if is_zoned else f"{entry_id}_{mac}_master"
        
        # Determine Name from Hardware zoneX_name if available
        raw_name = self.coordinator.get_field(self._mac, f"zone{self._zone_num}_name")
        if not is_zoned:
            self._attr_name = "SmartTemp AC"
        else:
            self._attr_name = raw_name if raw_name else f"Zone {self._zone_num}"

        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, mac)}, name=f"SmartTemp {mac}")
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_precision = 0.1
        self._attr_target_temperature_step = 0.5
        
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
        """Handle Off logic based on Controller Type."""
        # Non-Zoned: Power is determined by equip_mode
        # Zoned: Power for this entity is determined by zoneX:onoff
        if self._is_zoned:
            status = self.coordinator.get_field(self._mac, f"zone{self._zone_num}:onoff", 0)
            if status == 0: return HVACMode.OFF
        
        mode = self.coordinator.get_field(self._mac, "equip_mode", 0)
        return MAP_SMARTTEMP_TO_HA.get(mode, HVACMode.OFF)

    @property
    def current_temperature(self):
        """Non-zoned uses dis_room_temp (Array), Zoned uses dis_zone_temp (Array)."""
        if not self._is_zoned:
            # dis_room_temp: [244, 0, 0, 0] -> Index 0
            val = self.coordinator.get_field(self._mac, "dis_room_temp")
            if isinstance(val, list) and len(val) > 0: return float(val[0]) / 10.0
        else:
            # dis_zone_temp: [239, 240] -> Index based on zone
            val = self.coordinator.get_field(self._mac, "dis_zone_temp")
            if isinstance(val, list) and len(val) > self._zone_idx:
                return float(val[self._zone_idx]) / 10.0
        return None

    @property
    def target_temperature(self):
        """Non-zoned uses set_temp, Zoned uses zoneX_set."""
        if not self._is_zoned:
            val = self.coordinator.get_field(self._mac, "set_temp")
        else:
            val = self.coordinator.get_field(self._mac, f"zone{self._zone_num}_set")
        
        if val is not None: return float(val) / 10.0
        return None

    @property
    def current_humidity(self):
        """dis_room_humi: [68, 0, 0, 0] -> Index 0."""
        val = self.coordinator.get_field(self._mac, "dis_room_humi")
        if isinstance(val, list) and len(val) > 0: return val[0]
        return None

    @property
    def hvac_action(self):
        """Report Heat/Cool/Idle status."""
        if self.hvac_mode == HVACMode.OFF: return HVACAction.OFF
        heat = self.coordinator.get_field(self._mac, "heat_status", 0)
        cool = self.coordinator.get_field(self._mac, "cool_status", 0)
        if heat == 1: return HVACAction.HEATING
        if cool == 1: return HVACAction.COOLING
        return HVACAction.IDLE

    @property
    def fan_mode(self):
        val = self.coordinator.get_field(self._mac, "fan_status", 0)
        mapping = {0: FAN_AUTO, 1: FAN_LOW, 2: FAN_MEDIUM, 3: FAN_HIGH}
        return mapping.get(val, FAN_AUTO)

    @property
    def preset_mode(self):
        """Fan Policy (fan_mode)."""
        policy = self.coordinator.get_field(self._mac, "fan_mode", 0)
        return "Continuous Fan" if policy == 1 else "Auto Fan"

    @property
    def extra_state_attributes(self):
        """Capture diagnostic fields from pair-key."""
        data = self.coordinator.data.get(self._mac, {})
        return {
            "system_time": f"{data.get('hour')}:{data.get('min')}",
            "error_code": data.get("err_code"),
            "filter_days": data.get("filter_days"),
            "heat_setpoint": float(data.get("heatset", 0)) / 10.0 if "heatset" in data else None,
            "cool_setpoint": float(data.get("coolset", 0)) / 10.0 if "coolset" in data else None,
        }

    async def async_set_hvac_mode(self, hvac_mode):
        """Set mode or toggle specific zone."""
        if hvac_mode == HVACMode.OFF and self._is_zoned:
            await self.hub.send_smarttemp_command(self._mac, {f"zone{self._zone_num}:onoff": 0})
        elif self._is_zoned:
            # Turn zone on and set system mode
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

    async def async_set_fan_mode(self, fan_mode):
        mapping = {FAN_AUTO: 0, FAN_LOW: 1, FAN_MEDIUM: 2, FAN_HIGH: 3}
        await self.hub.send_smarttemp_command(self._mac, {"fan_status": mapping.get(fan_mode, 0)})

    async def async_set_preset_mode(self, preset_mode):
        val = 1 if preset_mode == "Continuous Fan" else 0
        await self.hub.send_smarttemp_command(self._mac, {"fan_mode": val})

    @property
    def min_temp(self):
        val = self.coordinator.get_field(self._mac, "temp_min", 180)
        return float(val) / 10.0

    @property
    def max_temp(self):
        val = self.coordinator.get_field(self._mac, "temp_max", 320)
        return float(val) / 10.0
    
    async def async_set_hvac_mode(self, hvac_mode):
        """Set mode or toggle specific zone."""
        if hvac_mode == HVACMode.OFF and self._is_zoned:
            await self.hub.send_smarttemp_command(self._mac, {f"zone{self._zone_num}:onoff": 0})
        elif self._is_zoned:
            # Turn zone on and set system mode
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

    async def async_set_fan_mode(self, fan_mode):
        mapping = {FAN_AUTO: 0, FAN_LOW: 1, FAN_MEDIUM: 2, FAN_HIGH: 3}
        await self.hub.send_smarttemp_command(self._mac, {"fan_status": mapping.get(fan_mode, 0)})

    async def async_set_preset_mode(self, preset_mode):
        val = 1 if preset_mode == "Continuous Fan" else 0
        await self.hub.send_smarttemp_command(self._mac, {"fan_mode": val})

