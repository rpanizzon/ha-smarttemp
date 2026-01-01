import logging
import asyncio
from homeassistant.helpers.dispatcher import async_dispatcher_connect
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
    TEMP_SCALE_FACTOR, 
    NEW_DEVICE_SIGNAL
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Climate entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    hub = data["hub"]
    known_devices = set()

    def add_new_entities(mac=None):
        async def _async_registration():
            new_entities = []
            target_macs = [mac] if mac else list(coordinator.data.keys() if coordinator.data else [])

            for device_mac in target_macs:
                if device_mac not in known_devices:
                    _LOGGER.info(f"Creating SmartTemp entities for MAC: {device_mac}")
                    new_entities.append(SmartTempAC(coordinator, hub, device_mac))
                    
                    device_data = coordinator.data.get(device_mac, {})
                    zone_count = device_data.get("zone_no", 0)
                    for i in range(1, zone_count + 1):
                        new_entities.append(SmartTempZone(coordinator, hub, device_mac, i))
                    
                    known_devices.add(device_mac)

            if new_entities:
                # FIX: Home Assistant's async_add_entities is often NOT a coroutine
                # Calling it directly is the standard way.
                async_add_entities(new_entities)

        hass.add_job(_async_registration())
    
    # Listen for the signal from the Coordinator
    entry.async_on_unload(
        async_dispatcher_connect(hass, NEW_DEVICE_SIGNAL, add_new_entities)
    )

    # Initial check for devices already discovered by the Hub
    if coordinator.data:
        add_new_entities()

class SmartTempBase(ClimateEntity):
    """Base class for SmartTemp entities."""
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, hub, mac):
        self.coordinator = coordinator
        self.hub = hub
        self._mac = mac

    @property
    def available(self):
        """Return True if the device is currently connected to the Hub."""
        return self._mac in self.hub.active_connections

    @property
    def should_poll(self):
        return False

    async def async_added_to_hass(self):
        self.async_on_remove(self.coordinator.async_add_listener(self.async_write_ha_state))

class SmartTempAC(SmartTempBase):
    def __init__(self, coordinator, hub, mac):
        super().__init__(coordinator, hub, mac)
        self._attr_unique_id = f"{mac}_main"
        self._attr_name = "Main Controller"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | 
            ClimateEntityFeature.FAN_MODE
        )
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO, HVACMode.DRY]
        self._attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
        # FIX: Initialize the attribute to avoid the AttributeError
        self._attr_fan_mode = FAN_AUTO 

    @property
    def fan_mode(self):
        """Return current fan speed."""
        speed = self.coordinator.get_field(self._mac, "fan_speed", 0)
        # Assuming your protocol: 0=Auto, 1=Low, 2=Med, 3=High
        mapping = {0: FAN_AUTO, 1: FAN_LOW, 2: FAN_MEDIUM, 3: FAN_HIGH}
        return mapping.get(speed, FAN_AUTO)

    @property
    def hvac_mode(self):
        mode = self.coordinator.get_field(self._mac, "equip_mode", 0)
        return MAP_SMARTTEMP_TO_HA.get(mode, HVACMode.OFF)

    @property
    def current_temperature(self):
        return self.coordinator.get_temp(self._mac, "dis_sys_temp")

    @property
    def target_temperature(self):
        mode = self.hvac_mode
        if mode == HVACMode.HEAT:
            return self.coordinator.get_temp(self._mac, "heatset")
        return self.coordinator.get_temp(self._mac, "coolset")

    async def async_set_hvac_mode(self, hvac_mode):
        mode_val = MAP_HA_TO_SMARTTEMP.get(hvac_mode, 0)
        await self.hub.send_smarttemp_command(self._mac, {"equip_mode": mode_val})

    async def async_set_temperature(self, **kwargs):
        temp = int(kwargs.get(ATTR_TEMPERATURE) * TEMP_SCALE_FACTOR)
        field = "heatset" if self.hvac_mode == HVACMode.HEAT else "coolset"
        await self.hub.send_smarttemp_command(self._mac, {field: temp})

class SmartTempZone(SmartTempBase):
    """Representation of an Individual Zone."""

    def __init__(self, coordinator, hub, mac, zone_num):
        super().__init__(coordinator, hub, mac)
        self._zone_num = zone_num
        self._attr_unique_id = f"{mac}_zone_{zone_num}"
        self._attr_name = f"Zone {zone_num}"
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY]
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def hvac_mode(self):
        status = self.coordinator.get_field(self._mac, f"zone{self._zone_num}_status", 0)
        return HVACMode.FAN_ONLY if status == 1 else HVACMode.OFF

    @property
    def current_temperature(self):
        return self.coordinator.get_zone_temp(self._mac, self._zone_num - 1)

    @property
    def target_temperature(self):
        return self.coordinator.get_temp(self._mac, f"zone{self._zone_num}_set")

    async def async_set_hvac_mode(self, hvac_mode):
        """Open/Close zone and manage main unit power."""
        new_status = 1 if hvac_mode != HVACMode.OFF else 0
        
        # Power up Main Unit if turning a zone ON
        if new_status == 1:
            current_main_mode = self.coordinator.get_field(self._mac, "equip_mode")
            if current_main_mode == 0:
                _LOGGER.info("Zone ON: Powering up Main Unit to Auto")
                await self.hub.send_smarttemp_command(self._mac, {"equip_mode": 3}) # Default to Auto

        await self.hub.send_smarttemp_command(self._mac, {f"zone{self._zone_num}_status": new_status})

        # Logic to turn OFF main unit if all zones are off
        if new_status == 0:
            zone_count = self.coordinator.get_field(self._mac, "zone_no", 0)
            all_off = True
            for i in range(1, zone_count + 1):
                if i == self._zone_num: continue
                if self.coordinator.get_field(self._mac, f"zone{i}_status") == 1:
                    all_off = False
                    break
            if all_off:
                _LOGGER.info("All Zones OFF: Powering down Main Unit")
                await self.hub.send_smarttemp_command(self._mac, {"equip_mode": 0})

    async def async_set_temperature(self, **kwargs):
        temp = int(kwargs.get(ATTR_TEMPERATURE) * TEMP_SCALE_FACTOR)
        await self.hub.send_smarttemp_command(self._mac, {f"zone{self._zone_num}_set": temp})