import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .hub import SmartTempHub
from .coordinator import SmartTempCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# List of platforms to support
PLATFORMS = ["climate", "sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartTemp from a config entry."""

    # 1. Initialize core objects
    port = entry.data.get("port", 2223)
    hub = SmartTempHub(hass, port=port)
    coordinator = SmartTempCoordinator(hass, hub)
    hub.coordinator = coordinator

    # 2. Register the service IMMEDIATELY
    # This ensures the action is available even if the server is still starting
    async def handle_inject_command(call):
        """Service to send raw JSON to a specific MAC address."""
        mac = call.data.get("mac")
        cmd = call.data.get("cmd")
        await hub.send_raw_command(mac, cmd)

    hass.services.async_register(
        DOMAIN, 
        "inject_raw_command", 
        handle_inject_command
    )

    # 3. Store the objects
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "hub": hub,
        "coordinator": coordinator,
    }

    # 4. Start the server
    try:
        await hub.start_server()
    except Exception as err:
        _LOGGER.exception("Failed to start SmartTemp hub: %s", err)
        return False

    # 5. Forward platforms LAST
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(lambda: hass.async_create_task(hub.stop_server()))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    stored = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and stored:
        hub = stored.get("hub")
        try:
            if hub:
                await hub.stop_server()
        except Exception:
            _LOGGER.exception("Error stopping SmartTemp hub for %s", entry.entry_id)
        # Remove stored data
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
