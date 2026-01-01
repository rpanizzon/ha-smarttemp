import logging
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import DOMAIN, TEMP_SCALE_FACTOR

_LOGGER = logging.getLogger(__name__)

class SmartTempCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SmartTemp data."""

    def __init__(self, hass, hub):
        """Initialize the coordinator."""
        self.hub = hub
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # No update_interval because data is pushed via TCP
        )

    def async_set_updated_data(self, data):
        """Allow the Hub to push new JSON telemetry into the coordinator."""
        mac = data.get("mac")
        if not mac:
            return

        # Initialize storage for this specific device if it doesn't exist
        if self.data is None:
            self.data = {}
        
        # Merge new data into existing state for this MAC
        if mac not in self.data:
            self.data[mac] = {}
            
        self.data[mac].update(data)
        
        # Notify all entities (Climate, Sensors) that data has changed
        self.async_update_listeners()

    def get_field(self, mac, field, default=None):
        """Helper to get a field for a specific device."""
        device_data = self.data.get(mac, {})
        return device_data.get(field, default)

    def get_temp(self, mac, field):
        """Helper to get scaled temperature (integer / 10)."""
        val = self.get_field(mac, field)
        if val is not None:
            return val / TEMP_SCALE_FACTOR [cite: 153]
        return None