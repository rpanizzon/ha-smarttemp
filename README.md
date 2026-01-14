# SmartTemp Inspire Touch Air Conditioner controller - HA Custom Component
Home Assistant custom component that creates a local alternate server for the Smarttemp Inspire Touch (replaces `smarttempapp.com.au`). 
This was developed by analysing the tcp traffic between the smarttemp controller and the cloud based server `smarttempapp.com.au`.
By redirecting traffic locally, you gain faster response times, remove cloud dependency, and enable advanced automation logic through Home Assitant. In addition, all other Home Assistant features, such as Google Assist is available (i.e "hay google, turn on the bedroom Air Conditioner")
>***Note***, this integration replaces the cloud based server with Home Assistant, making the Smarttemp app unable to access the controller and therefore unusable. Use Home Assistant app instead.

## Features
- **Local TCP Control:** Direct communication with the hardware over your LAN.
- **Per-Zone Climate Entities:** Automatically creates climate entities for each discovered zone upon receiving a configuration payload.
- **Zero Cloud Dependency:** Works entirely offline once set up.
- **Smart Master Shutdown:** Automatically turns off the master unit when the last active zone is closed.

## How it Works (The Logic)
The custom component consits of 4 parts:
- **hub.py:** simulates the as the server `smarttempapp.com.au`. Establishes connection to the controller(s), packages JSON payloads and sends them to the coordinator. Recieves commands from the coordinator to sendto the controller.
- **coordinator.py:** On reception of a valid JSON (if necessary) create the entities, and update the values from the controller for use by climate and sensor. Passes on commands from climate to the hub.
- **climante.py:** Updatees climate based information and returns commands to the coordinator
- **sensor.py:** maintains the room temperature and hubidity sensors for each zone.
To ensure stability with the SmartTemp hardware protocol, the integration uses specific logic gates:
#### Online Gating & Discovery
The integration remains in an "Unavailable" state until a `pair_key` payload is received. This ensures that Home Assistant has the full configuration (zone counts, names, and limits) before creating entities, preventing "ghost" devices or incorrect state representation.
#### Command Injection (The Stack)
Because the controller uses a specific poll-response cycle, commands sent from Home Assistant are queued in the **Hub**. They are injected into the next available 3-second heartbeat window to ensure the hardware never misses a command due to socket collisions.
#### "Last Man Standing" Logic
The **Coordinator** monitors the status of all zones. If an incoming packet indicates a zone has turned off, the Coordinator performs a full memory sweep of all zones. If it confirms that all zones are now closed, it proactively sends a system-wide `equip_mode: 0` command to shut down the master unit.

## Setup & Installation

#### 1. DNS Redirection (Required)
The controller is hardcoded to look for `smarttempapp.com.au`. You must use a local DNS server (AdGuard Home, Pi-hole, or your router) to redirect this domain to your Home Assistant IP address.
### 2. Installation
1. Copy `custom_components/smarttemp` into your HA `/config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for "SmartTemp".
You should see entries appear in the integration. There should be 1 entry per zone/controller.
## Protocol Overview
The controller communicates via raw TCP on port 2223 (or your configured port).
- **Handshake:** The connection begins with a `SUB` frame from the device, identifying its MAC address.
- **Time Sync:** The device regularly requests `cmd: time`. The Hub responds with the current local time to keep the controller clock accurate.
- **Data Structure:** State is shared via nested JSON objects (e.g., `sys_set`, `zone1`). The integration uses a deep-merge strategy to ensure partial updates do not overwrite existing data.l

## Limitations & To-Do
- [x] **Heartbeats:** `__heartbeat__` messages are ignored to reduce log noise.
- [x] **Master Shutdown:** Optimized for immediate response when the last zone closes.
- [ ] **Weather Data:** Currently not implemented.
- [ ] **Advanced Fields:** `autoofftime`, `progen`, and `ovrtime` are currently read-only.