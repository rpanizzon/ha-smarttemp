import logging
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, TEMP_SCALE_FACTOR, NEW_DEVICE_SIGNAL

_LOGGER = logging.getLogger(__name__)

class SmartTempCoordinator(DataUpdateCoordinator):
    """Class to manage data pushed from the SmartTemp Hub."""

    def __init__(self, hass, hub):
        """Initialize the coordinator."""
        self.hub = hub
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # We don't use an update_interval because the Hub pushes data to us
        )
        self.data = {} # Initialize as dictionary for MAC-based storage

    def async_set_updated_data(self, data):
        """Update data for a specific device and notify HA."""
        mac = data.get("mac")
        if not mac:
            return

        # Check if this is a brand new device we haven't seen since HA started
        is_new = mac not in self.data
        
        # Initialize storage for this specific device if it doesn't exist
        if is_new:
            self.data[mac] = {}
            _LOGGER.info("Coordinator: New device discovered: %s", mac)
            
        # Merge new data into existing state for this MAC
        self.data[mac].update(data)
        
        # 1. Update the base coordinator state (triggers listeners in climate.py)
        # Note: We pass self.data (the whole dict) so entities can pull their specific MAC
        super().async_set_updated_data(self.data)

        # 2. If it's the first time we see this MAC, tell climate platform to create entities
        if is_new:
            _LOGGER.debug("Sending signal to create entities for %s", mac)
            async_dispatcher_send(self.hass, NEW_DEVICE_SIGNAL, mac)

    def get_field(self, mac, field, default=None):
        """Helper to get a field for a specific device."""
        device_data = self.data.get(mac, {})
        return device_data.get(field, default)

    def get_temp(self, mac, field):
        """Helper to get scaled temperature (integer / 10)."""
        val = self.get_field(mac, field)
        if val is not None and isinstance(val, (int, float)):
            return val / TEMP_SCALE_FACTOR
        return None
    
    def get_zone_temp(self, mac, zone_index):
        """Get temperature for a specific zone index (0-based)."""
        temps = self.get_field(mac, "dis_zone_temp", [])
        if temps and len(temps) > zone_index:
            val = temps[zone_index]
            # 0 usually means no sensor or zone inactive
            return val / TEMP_SCALE_FACTOR if val > 0 else None
        return None