import logging
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, NEW_DEVICE_SIGNAL, TEMP_SCALE_FACTOR
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up SmartTemp sensors via discovery signal."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entry_id = entry.entry_id

    # --- CATCH-UP LOGIC ---
    if coordinator.data:
        _LOGGER.debug("TRACE: Sensor platform catch-up. Checking %s devices", len(coordinator.data))
        initial_sensors = []
        for mac, device_data in coordinator.data.items():
            zone_count = device_data.get("zone_no", 0)
            
            # Determine which zones to create sensors for
            indices = [0] if zone_count == 0 else range(1, zone_count + 1)
            
            for idx in indices:
                initial_sensors.extend([
                    SmartTempTemperatureSensor(coordinator, entry_id, mac, idx),
                    SmartTempHumiditySensor(coordinator, entry_id, mac, idx)
                ])
        
        if initial_sensors:
            _LOGGER.debug("TRACE: Adding %s initial sensors", len(initial_sensors))
            async_add_entities(initial_sensors)

    # --- FUTURE DISCOVERY ---
    async def async_add_smarttemp_sensors(mac, zone_idx):
        _LOGGER.debug("TRACE [%s]: Signal RECEIVED in sensor.py for zone %s", mac, zone_idx)
        new_sensors = [
            SmartTempTemperatureSensor(coordinator, entry_id, mac, zone_idx),
            SmartTempHumiditySensor(coordinator, entry_id, mac, zone_idx)
        ]
        async_add_entities(new_sensors)

    entry.async_on_unload(
        async_dispatcher_connect(hass, NEW_DEVICE_SIGNAL, async_add_smarttemp_sensors)
    )

class SmartTempTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Temperature sensor using consolidated coordinator logic."""

    # This signature must match exactly how you call it above
    def __init__(self, coordinator, entry_id, mac, zone_idx):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._mac = mac
        self._zone_idx = zone_idx
        
        # Correctly building unique_id using entry_id and zone
        suffix = "temp" if zone_idx == 0 else f"zone{zone_idx}_temp"
        self._attr_unique_id = f"{entry_id}_{mac}_{suffix}"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)}, 
            name=f"SmartTemp {mac}"
        )
        
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def name(self):
        if self._zone_idx == 0:
            return "SmartTemp Room Temperature"
        name_field = f"zone{self._zone_idx}_name"
        hw_name = self.coordinator.get_field(self._mac, name_field)
        return f"{hw_name} Temperature" if hw_name else f"Zone {self._zone_idx} Temperature"

    @property
    def native_value(self):
        """Request temperature for the specific zone index."""
        raw = self.coordinator.get_room_temp(self._mac, self._zone_idx)
        if raw is not None and raw != -1000:
            return float(raw) / TEMP_SCALE_FACTOR
        return None
    
    @property
    def available(self) -> bool:
        """Read availability directly from the data state."""
        # Look for the 'online' flag we injected in the hub
        return self.coordinator.data.get(self._mac, {}).get("online", False)

class SmartTempHumiditySensor(CoordinatorEntity, SensorEntity):
    """Humidity sensor using consolidated coordinator logic."""

    def __init__(self, coordinator, entry_id, mac, zone_idx):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._mac = mac
        self._zone_idx = zone_idx
        
        suffix = "humidity" if zone_idx == 0 else f"zone{zone_idx}_humidity"
        self._attr_unique_id = f"{entry_id}_{mac}_{suffix}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, mac)}, name=f"SmartTemp {mac}")
        
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def name(self):
        if self._zone_idx == 0:
            return "SmartTemp Humidity"
        name_field = f"zone{self._zone_idx}_name"
        hw_name = self.coordinator.get_field(self._mac, name_field)
        return f"{hw_name} Humidity" if hw_name else f"Zone {self._zone_idx} Humidity"

    @property
    def native_value(self):
        """Uses the consolidated get_room_humidity from coordinator."""
        return self.coordinator.get_room_humidity(self._mac, self._zone_idx)
    
    @property
    def available(self) -> bool:
        """Read availability directly from the data state."""
        # Look for the 'online' flag we injected in the hub
        return self.coordinator.data.get(self._mac, {}).get("online", False)