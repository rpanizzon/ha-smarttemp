import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, NEW_DEVICE_SIGNAL, TEMP_SCALE_FACTOR

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SmartTemp entities via discovery signal."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    hub = hass.data[DOMAIN][entry.entry_id]["hub"]

    def async_add_smarttemp_entity(discovery_info):
        """Callback when coordinator signals (mac, zone_idx)."""
        mac, zone_idx = discovery_info
        
        _LOGGER.info("Adding entity for MAC %s Index %s", mac, zone_idx)
        
        # Create the entity object
        new_entity = SmartTempZone(coordinator, hub, entry.entry_id, mac, zone_idx)
        
        # FIX: Use hass.add_job to ensure async_add_entities runs in the correct loop context
        hass.add_job(async_add_entities, [new_entity])

    # Listen for signals
    entry.async_on_unload(
        async_dispatcher_connect(hass, NEW_DEVICE_SIGNAL, async_add_smarttemp_entity)
    )

class SmartTempZone(CoordinatorEntity, ClimateEntity):
    """Climate entity for a specific Zone (1-N) or System (0)."""

    def __init__(self, coordinator, hub, entry_id, mac, zone_idx):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.hub = hub
        self._mac = mac
        self._zone_idx = zone_idx  # 0=System (Guest), 1+=Actual Zones (Lounge)
        
        # Unique ID based on Mac + Index
        suffix = "system" if zone_idx == 0 else f"zone_{zone_idx}"
        self._attr_unique_id = f"{entry_id}_{mac}_{suffix}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, mac)}, name=f"SmartTemp {mac}")
        
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]
        self._attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE | 
            ClimateEntityFeature.FAN_MODE |
            ClimateEntityFeature.PRESET_MODE
        )
        self._attr_preset_modes = ["Auto Fan", "Continuous Fan"]

    def _get_hardware_temp(self, sub_field):
        """Helper to fetch nested values and apply TEMP_SCALE_FACTOR."""
        parent = "sys_set" if self._zone_idx == 0 else f"zone{self._zone_idx}"
        raw_val = self.coordinator.get_field(self._mac, f"{parent}:{sub_field}")
        
        try:
            if raw_val is not None and raw_val != -1000:
                return float(raw_val) / TEMP_SCALE_FACTOR
        except (TypeError, ValueError):
            pass
        return None

    @property
    def extra_state_attributes(self):
        """Return device-specific state attributes."""
        parent_key = "sys_set" if self._zone_idx == 0 else f"zone{self._zone_idx}"
        return {
            "program_enable": self.coordinator.get_field(self._mac, f"{parent_key}:progen"),
            "override_time": self.coordinator.get_field(self._mac, f"{parent_key}:ovrdtime"),
            "auto_off_time": self.coordinator.get_field(self._mac, f"{parent_key}:autoofftime"),
        }
    
    @property
    def name(self):
        """Return 'SmartTemp System' for Guest or the hardware name for Lounge zones."""
        if self._zone_idx == 0:
            return "SmartTemp System"
        name_field = f"zone{self._zone_idx}_name"
        return self.coordinator.get_field(self._mac, name_field) or f"Zone {self._zone_idx}"

    @property
    def current_temperature(self):
        """Fetch temperature using the coordinator's agnostic helper."""
        # This calls get_room_temp(mac, zone_idx) which handles the routing
        raw = self.coordinator.get_room_temp(self._mac, self._zone_idx)
        
        if raw is not None and raw != -1000:
            return float(raw) / TEMP_SCALE_FACTOR
        return None

    @property
    def current_humidity(self):
        """Fetch humidity using the coordinator's agnostic helper."""
        # Passing zone_idx allows coordinator to pick index 0 or index n-1
        return self.coordinator.get_room_humidity(self._mac, self._zone_idx)

    @property
    def hvac_mode(self):
        """Report mode based on global system state and local zone state."""
        # If this is a zone and it is off, report OFF regardless of system mode
        if self._zone_idx > 0:
            on_off = self.coordinator.get_field(self._mac, f"zone{self._zone_idx}:onoff")
            if on_off == 0:
                return HVACMode.OFF

        # Otherwise, report the global system mode
        mode_val = self.coordinator.get_field(self._mac, "equip_mode")
        mapping = {0: HVACMode.OFF, 1: HVACMode.HEAT, 3: HVACMode.COOL, 4: HVACMode.HEAT_COOL}
        return mapping.get(mode_val, HVACMode.OFF)
    
    @property
    def hvac_modes(self):
        """List of available modes."""
        return [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]

    @property
    def fan_mode(self):
        val = self.coordinator.get_field(self._mac, "fan_speed", 0)
        mapping = {0: FAN_AUTO, 1: FAN_LOW, 2: FAN_MEDIUM, 3: FAN_HIGH}
        return mapping.get(val, FAN_AUTO)
    
    @property
    def preset_mode(self):
        """Maps the 'fan_mode' field (0/1) from your doc to a readable preset."""
        policy = self.coordinator.get_field(self._mac, "fan_mode", 0)
        return "Continuous Fan" if policy == 1 else "Auto Fan"
    
    @property
    def target_temperature_low(self):
        return self._get_hardware_temp("heatset")

    @property
    def target_temperature_high(self):
        return self._get_hardware_temp("coolset")

    @property
    def target_temperature(self):
        """Single slider fallback for HEAT/COOL modes, None for range modes."""
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return None  # This forces the UI to use the High/Low sliders
        if self.hvac_mode == HVACMode.COOL:
            return self.target_temperature_high
        return self.target_temperature_low
    
    @property
    def min_temp(self):
        raw = self.coordinator.get_field(self._mac, "temp_min")
        return float(raw) / TEMP_SCALE_FACTOR if raw else 18.0

    @property
    def max_temp(self):
        raw = self.coordinator.get_field(self._mac, "temp_max")
        return float(raw) / TEMP_SCALE_FACTOR if raw else 32.0

    async def async_set_hvac_mode(self, hvac_mode):
        """Set HVAC mode using a single combined JSON payload."""
        
        # 1. Handle Turning OFF
        if hvac_mode == HVACMode.OFF:
            if self._zone_idx == 0:
                await self.hub.send_smarttemp_command(self._mac, {"equip_mode": 0})
            else:
                parent_key = f"zone{self._zone_idx}"
                await self.hub.send_smarttemp_command(self._mac, {parent_key: {"onoff": 0}})
                # await self.coordinator.check_and_shutdown_system(self._mac)
            return

        # 2. Handle Turning ON / Changing Modes
        mapping = {HVACMode.HEAT: 1, HVACMode.COOL: 3, HVACMode.HEAT_COOL: 4}
        val = mapping.get(hvac_mode)
        
        if val is not None:
            if self._zone_idx == 0:
                # Guest / Non-Zoned: Just the mode
                await self.hub.send_smarttemp_command(self._mac, {"equip_mode": val})
            else:
                # Lounge / Zoned: COMBINED PAYLOAD
                parent_key = f"zone{self._zone_idx}"
                payload = {
                    "equip_mode": val,
                    parent_key: {
                        "onoff": 1,
                        "heatset": int(self.target_temperature_low * TEMP_SCALE_FACTOR),
                        "coolset": int(self.target_temperature_high * TEMP_SCALE_FACTOR),
                        "progen": self.coordinator.get_field(self._mac, f"{parent_key}:progen", 0),
                        "ovrdtime": self.coordinator.get_field(self._mac, f"{parent_key}:ovrdtime", 0),
                        "autoofftime": self.coordinator.get_field(self._mac, f"{parent_key}:autoofftime", -1)
                    }
                }
                _LOGGER.debug("Sending combined ON command for %s: %s", parent_key, payload)
                await self.hub.send_smarttemp_command(self._mac, payload)


    async def async_set_temperature(self, **kwargs):
        """Pack temperature payload using zone-specific keys."""
        temp_low = kwargs.get("target_temp_low") or self.target_temperature_low
        temp_high = kwargs.get("target_temp_high") or self.target_temperature_high
        
        # Handle single slider setpoint
        if temp := kwargs.get(ATTR_TEMPERATURE):
            if self.hvac_mode == HVACMode.HEAT:
                temp_low = temp
            else:
                temp_high = temp

        # Determine if we use 'sys_set' (Guest) or 'zoneX' (Lounge)
        parent_key = "sys_set" if self._zone_idx == 0 else f"zone{self._zone_idx}"
        
        payload = {
            parent_key: {
                "heatset": int(temp_low * TEMP_SCALE_FACTOR),
                "coolset": int(temp_high * TEMP_SCALE_FACTOR),
                "progen": self.coordinator.get_field(self._mac, f"{parent_key}:progen", 0),
                "ovrdtime": self.coordinator.get_field(self._mac, f"{parent_key}:ovrdtime", 0),
                "autoofftime": self.coordinator.get_field(self._mac, f"{parent_key}:autoofftime", -1)
            }
        }
        
        # Explicitly include 'onoff' for Lounge zones to match hardware requirements
        if self._zone_idx > 0:
            payload[parent_key]["onoff"] = 1

        await self.hub.send_smarttemp_command(self._mac, payload)
        
    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        # Mapping HA constants to hardware integers (0:Auto, 1:Low, 2:Med, 3:High)
        mapping = {
            FAN_AUTO: 0,
            FAN_LOW: 1,
            FAN_MEDIUM: 2,
            FAN_HIGH: 3
        }
        val = mapping.get(fan_mode, 0)
        _LOGGER.debug("Setting fan speed to %s (value: %s)", fan_mode, val)
        await self.hub.send_smarttemp_command(self._mac, {"fan_speed": val})

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode (Fan Policy)."""
        # Mapping: Continuous Fan = 1, Auto Fan = 0
        val = 1 if preset_mode == "Continuous Fan" else 0
        await self.hub.send_smarttemp_command(self._mac, {"fan_mode": val})