import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from .const import DOMAIN, SUB_FRAME_PREFIX, HEARTBEAT_PAYLOAD

_LOGGER = logging.getLogger(__name__)

class SmartTempHub:
    def __init__(self, hass, port):
        self.hass = hass
        self.port = port
        self.coordinator = None
        self.active_connections = {}  # MAC -> writer
        self.last_seen = {}           # MAC -> timestamp
        self._server = None

    async def start_server(self):
        """Start the TCP server and the timeout monitor."""
        self._server = await asyncio.start_server(self.handle_client, '0.0.0.0', self.port)
        _LOGGER.info(f"SmartTemp Server listening on port {self.port}")
        
        # Start background task to monitor device health
        self.hass.async_create_task(self._check_timeouts())

    async def stop_server(self, event=None):
        """Stop the TCP server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            _LOGGER.info("SmartTemp Server stopped")

    async def _check_timeouts(self):
        """Mark devices as unavailable if they stop talking for >65s."""
        while True:
            await asyncio.sleep(15)
            now = time.time()
            stale_macs = [mac for mac, last in self.last_seen.items() if now - last > 65]
            
            for mac in stale_macs:
                _LOGGER.warning(f"Device {mac} timed out. Removing connection.")
                self.active_connections.pop(mac, None)
                self.last_seen.pop(mac, None)
                if self.coordinator:
                    self.coordinator.async_update_listeners()

    async def handle_client(self, reader, writer):
        """Handle individual TCP connections from AC controllers."""
        address = writer.get_extra_info('peername')
        _LOGGER.debug(f"New connection from {address}")
        
        buffer = ""
        current_mac = None 

        try:
            while True:
                data = await reader.read(4096)
                if not data: break
                
                raw_chunk = data.decode('utf-8', errors='ignore')
                buffer += raw_chunk

                # Trace non-JSON frames (SUB, heartbeats, etc)
                if not buffer.strip().startswith("{"):
                    _LOGGER.debug(f"[RAW TRACE] {address}: {raw_chunk.strip()}")

                # 1. Handle Registration (SUB)
                if buffer.startswith(SUB_FRAME_PREFIX):
                    lines = buffer.split('\n', 1)
                    if len(lines) > 1:
                        current_mac = lines[0].replace(SUB_FRAME_PREFIX, "").strip()
                        current_mac = "".join(current_mac.split()) # Remove any \r or \n
                        self.active_connections[current_mac] = writer
                        self.last_seen[current_mac] = time.time()
                        buffer = lines[1]
                        _LOGGER.info(f"Device registered: {current_mac}")
                    continue

                # 2. Process JSON with Bracket Counting
                while "{" in buffer:
                    start_index = buffer.find("{")
                    bracket_count = 0
                    for i in range(start_index, len(buffer)):
                        if buffer[i] == "{": bracket_count += 1
                        elif buffer[i] == "}": bracket_count -= 1
                        
                        if bracket_count == 0:
                            json_str = buffer[start_index:i+1]
                            try:
                                payload = json.loads(json_str)
                                msg_mac = payload.get("mac") or current_mac
                                if msg_mac:
                                    self.last_seen[msg_mac] = time.time()

                                # --- DEFINITIVE TIME/WEATHER HANDSHAKE ---
                                cmd = payload.get("cmd")
                                
                                if cmd == "time":
                                    # The log shows the response is Local Time 
                                    # and MsgID is Local Time + 1 hour.
                                    now = datetime.now()
                                    future = now + timedelta(hours=1)
                                    
                                    time_resp = {
                                        "local_time": now.strftime("%Y%m%d%H%M"),
                                        "MsgID": future.strftime("%Y%m%d%H%M%S")
                                    }
                                    
                                    # Cloud sends no spaces and NO newline
                                    resp_raw = json.dumps(time_resp, separators=(',', ':'))
                                    writer.write(resp_raw.encode('ascii'))
                                    await writer.drain()
                                    _LOGGER.debug(f"Handshake: Sent time to {msg_mac}")

                                elif cmd == "weather":
                                    # Cloud responds with simple result:ok
                                    weather_resp = json.dumps({"result": "ok"}, separators=(',', ':'))
                                    writer.write(weather_resp.encode('ascii'))
                                    await writer.drain()
                                    _LOGGER.debug(f"Handshake: Sent weather ACK to {msg_mac}")

                                # Acknowledge standard telemetry (equip_mode/coolset etc)
                                elif payload.get("end") == 1 or "equip_mode" in payload:
                                    ack = json.dumps({"result": "ok"}, separators=(',', ':'))
                                    writer.write(ack.encode('ascii'))
                                    await writer.drain()
                                # ------------------------------------------

                                if self.coordinator:
                                    self.coordinator.async_set_updated_data(payload)
                                    
                            except json.JSONDecodeError:
                                _LOGGER.error("JSON fragment invalid, waiting for more data...")
                            
                            buffer = buffer[i+1:].lstrip()
                            break
                    else:
                        break # Incomplete JSON
                    
            _LOGGER.error(f"Error with {address}: {e}")
        finally:
            if current_mac:
                self.active_connections.pop(current_mac, None)
            writer.close()
            await writer.wait_closed()

    async def send_command(self, mac, payload):
        """Physical send over the socket."""
        writer = self.active_connections.get(mac)
        if not writer: return
        try:
            cmd = json.dumps(payload) + "\n"
            writer.write(cmd.encode())
            await writer.drain()
        except Exception as e:
            _LOGGER.error(f"Send failed to {mac}: {e}")

    async def send_smarttemp_command(self, mac, payload):
        """Two-phase command (Intent + Commit)."""
        # Phase 1: Intent
        intent = payload.copy()
        intent.update({"mac": mac, "MsgID": time.strftime("%Y%m%d%H%M%S")})
        await self.send_command(mac, intent)
        
        await asyncio.sleep(0.1)
        
        # Phase 2: Commit
        commit = payload.copy()
        commit.update({"mac": mac, "time": int(time.time()), "end": 1})
        await self.send_command(mac, commit)