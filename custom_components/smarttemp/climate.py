import logging
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
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

from .const import DOMAIN, NEW_DEVICE_SIGNAL, TEMP_SCALE_FACTOR, TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SmartTemp entities."""
    _LOGGER.debug("TRACE: climate.py: async_setup_entry started")
    
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    hub = hass.data[DOMAIN][entry.entry_id]["hub"]

    # Temporary Trace catch-up logic
    if coordinator.data:
        _LOGGER.debug("TRACE: climate.py: Catch-up check found %s devices in coordinator", len(coordinator.data))
    else:
        _LOGGER.debug("TRACE: climate.py: Catch-up check found NO data in coordinator yet")
    
    # 1. CATCH-UP: Check what the coordinator already knows
    if coordinator.data:
        _LOGGER.debug("Found existing data for %s devices. Creating initial entities.", len(coordinator.data))
        initial_entities = []
        for mac, device_data in coordinator.data.items():
            zone_count = device_data.get("zone_no", 0)
            if zone_count == 0:
                initial_entities.append(SmartTempZone(coordinator, hub, entry.entry_id, mac, 0))
            else:
                for i in range(1, zone_count + 1):
                    initial_entities.append(SmartTempZone(coordinator, hub, entry.entry_id, mac, i))
        
        if initial_entities:
            async_add_entities(initial_entities)

    # 2. FUTURE: Listen for devices discovered after this moment
    async def async_add_smarttemp_entity(mac, zone_idx):
        _LOGGER.info("New discovery signal for MAC %s: Adding entity", mac)
        async_add_entities([SmartTempZone(coordinator, hub, entry.entry_id, mac, zone_idx)])

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
            ClimateEntityFeature.PRESET_MODE |
            ClimateEntityFeature.TURN_OFF |  
            ClimateEntityFeature.TURN_ON   
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
        return self.target_temperature_high
    
    @property
    def min_temp(self):
        raw = self.coordinator.get_field(self._mac, "temp_min")
        return float(raw) / TEMP_SCALE_FACTOR if raw else 18.0

    @property
    def max_temp(self):
        raw = self.coordinator.get_field(self._mac, "temp_max")
        return float(raw) / TEMP_SCALE_FACTOR if raw else 32.0
    
    @property
    def available(self) -> bool:
        """Read availability directly from the data state."""
        # Look for the 'online' flag we injected in the hub
        return self.coordinator.data.get(self._mac, {}).get("online", False)
    
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        _LOGGER.debug(f"TRACE: Climate {self._mac} set_hvac_mode: {hvac_mode}")
        
        # We pass the new mode to the bundler. 
        # The bundler will pull the current temperatures from 'self' automatically.
        await self._send_bundled_command(hvac_mode=hvac_mode)
    
    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        # You can default to AUTO or the last known state
        await self.async_set_hvac_mode(HVACMode.AUTO)    

    async def async_set_temperature(self, **kwargs):
        """Pack temperature payload using the bundling helper."""
        await self._send_bundled_command(
            temp=kwargs.get(ATTR_TEMPERATURE),
            temp_low=kwargs.get("target_temp_low"),
            temp_high=kwargs.get("target_temp_high")
        )
                  
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
        _LOGGER.debug("TRACE: Setting fan speed to %s (value: %s)", fan_mode, val)
        await self.hub.send_smarttemp_command(self._mac, {"fan_speed": val})

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode (Fan Policy)."""
        # Mapping: Continuous Fan = 1, Auto Fan = 0
        val = 1 if preset_mode == "Continuous Fan" else 0
        await self.hub.send_smarttemp_command(self._mac, {"fan_mode": val})
        
    async def _send_bundled_command(self, hvac_mode=None, temp=None, temp_low=None, temp_high=None):
        """Bundles mode and all setpoints into a single protocol-safe payload."""
        
        # 1. Resolve HVAC Mode and On/Off status
        mapping = {HVACMode.OFF: 0, HVACMode.HEAT: 1, HVACMode.COOL: 3, HVACMode.HEAT_COOL: 4}
        target_hvac = hvac_mode if hvac_mode is not None else self.hvac_mode
        proto_mode = mapping.get(target_hvac, 0) 

        # 2. Resolve Setpoints
        h_val = temp_low if temp_low is not None else self.target_temperature_low
        c_val = temp_high if temp_high is not None else self.target_temperature_high
        
        if temp is not None:
            if target_hvac == HVACMode.HEAT:
                h_val = temp
            elif target_hvac == HVACMode.COOL:
                c_val = temp

        # Ensure heat is always at least 1.0 degree below cool
        if h_val is not None and c_val is not None:
            if h_val > (c_val - 1.0):
                _LOGGER.debug("Deadband conflict: Adjusting setpoints for hardware compliance")
                # If we are adjusting HEAT (or in HEAT mode), push COOL up
                if temp_low is not None or target_hvac == HVACMode.HEAT:
                    c_val = h_val + 1.0
                # If we are adjusting COOL (or in COOL mode), push HEAT down
                else:
                    h_val = c_val - 1.0

        # 3. Convert to scaled integers for hardware
        h_set = int((h_val or 20.0) * TEMP_SCALE_FACTOR)
        c_set = int((c_val or 30.0) * TEMP_SCALE_FACTOR)

        # 4. Construct Payload with equip_mode at the beginning
        payload = {}

        if self._zone_idx == 0:
            payload = {"equip_mode": proto_mode}
            # Non-Zoned / System command uses "sys_set"
            payload["sys_set"] = {
                "heatset": h_set,
                "coolset": c_set
            }
        else:
            # ZONE ENTITY: Only toggles its own damper/onoff status
            # We keep equip_mode OUT of this payload so we don't override other zones
            if proto_mode != 0:
                payload = {"equip_mode": proto_mode}
        
            # Add rest of zone payload
            payload[f"zone{self._zone_idx}"] = {
                "onoff": 1 if proto_mode != 0 else 0, # Use local onoff logic
                "heatset": h_set,
                "coolset": c_set
            }

        # 3. Dispatch to Hub
        await self.hub.send_smarttemp_command(self._mac, payload)

        self.async_write_ha_state() 
