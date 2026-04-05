import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, DEFAULT_PORT

class SmartTempConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartTemp."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user adds the integration."""
        errors = {}

        # Prevent multiple instances of the integration if you only want one server
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            # In a real scenario, you might validate if the port is in use here
            return self.async_create_entry(
                title=f"SmartTemp Server (Port {user_input['port']})",
                data=user_input
            )

        # Show the form to the user
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("port", default=DEFAULT_PORT): int,
            }),
            errors=errors,
        )