import asyncio
import json
import logging
from datetime import datetime, timedelta
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, NEW_DEVICE_SIGNAL, TIME_ADJUST, TIMEOUT_SECONDS

_LOGGER = logging.getLogger(__name__)

SUB_FRAME_PREFIX = b"SUB "

class SmartTempHub:
    """The Socket Hub handling raw TCP communication with controllers."""

    def __init__(self, hass, port, coordinator=None):
        self.hass = hass
        self.port = port
        self.coordinator = coordinator
        self.active_connections = {}  # MAC: writer
        self.command_queues = {}     # MAC: asyncio.Queue()
        self.server = None
        self._serve_task = None
        
    async def start_server(self):
        """Start the TCP Server."""
        self.server = await asyncio.start_server(self.handle_client, '0.0.0.0', self.port)
        _LOGGER.info("SmartTemp Server started on port %s", self.port)
        self._serve_task = asyncio.create_task(self.server.serve_forever())

    async def stop_server(self):
        """Stop the TCP Server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self._serve_task:
            self._serve_task.cancel()
            self._serve_task = None

    async def handle_client(self, reader, writer):
        """Sequential handler updated to match actual hardware 'SUB' behavior."""
        address = writer.get_extra_info('peername')
        _LOGGER.info(f"New connection from {address}")
        
        current_mac = None
        buffer = b""

        try:
            # Phase 1: Registration (Wait for SUB,reply with partial pair_key)
            while True:
                data = await asyncio.wait_for(reader.read(2048), timeout=TIMEOUT_SECONDS)
                if not data: break
                buffer += data
                                    
                if buffer.startswith(SUB_FRAME_PREFIX) and b"\x0a" in buffer:
                    line_end = buffer.find(b"\x0a")
                    line = buffer[:line_end].decode('ascii').strip()
                    current_mac = line.split()[1]
                    
                    # Registration (Always overwrite with the latest writer)
                    self.active_connections[current_mac] = writer
                    
                    # Step 1: Issue Discovery immediately on SUB
                    await self.send_protocol_response(writer, "discovery")
                    
                    _LOGGER.info("MAC %s: Received SUB. Discovery Stage 1 issued.", current_mac)
                    buffer = buffer[line_end+1:]
                    break # Transition to the JSON processing loop
                
            # Phase 2: Stitched JSON Processing
            while True:
                # Use a smaller read buffer if the device sends in 1024 chunks
                data = await asyncio.wait_for(reader.read(2048), timeout=TIMEOUT_SECONDS)
                if not data: break
                buffer += data
                
                while b"{" in buffer:
                    start_index = buffer.find(b"{")
                    if start_index > 0:
                        buffer = buffer[start_index:]
                        continue

                    bracket_count = 0
                    json_found = False
                    
                    for i in range(len(buffer)):
                        if buffer[i] == ord("{"):
                            bracket_count += 1
                        elif buffer[i] == ord("}"):
                            bracket_count -= 1
                        
                        # Root level closure check
                        if bracket_count == 0 and i > 0:
                            json_bytes = buffer[:i+1]
                            try:
                                payload = json.loads(json_bytes.decode('utf-8'))
                                await self.process_payload(current_mac, payload, writer)
                                buffer = buffer[i+1:]
                                json_found = True
                                break 
                            except json.JSONDecodeError:
                                _LOGGER.debug(
                                    "TRACE [%s]: Nested/Seam '}' at byte %d. Continuing scan...", 
                                    current_mac, i
                                )
                                continue
                    
                    if not json_found:
                        if len(buffer) > 8192: # 8KB - longer than any valid payload
                            _LOGGER.warning("TRACE [%s]: Buffer overflow. Flushing.", current_mac)
                            buffer = buffer[1:]
                            continue
                        break

        except Exception as err:
            _LOGGER.error(f"TRACE [%s]: Connection lost: %s", current_mac, err)
        finally:
            if current_mac:
                _LOGGER.warning("MAC %s: Connection lost/closed. Cleaning up.", current_mac)
                if current_mac in self.active_connections:
                    del self.active_connections[current_mac]
                
                # RE-INTEGRATE: Notify coordinator of offline status
                if self.coordinator:
                    if current_mac not in self.coordinator.data:
                        self.coordinator.data[current_mac] = {}
                    
                    self.coordinator.data[current_mac]["online"] = False
                    # This push is what tells HA to grey out the entities
                    self.coordinator.async_set_updated_data(self.coordinator.data)

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                # Prevent errors if writer is already broken
                pass
            
    async def process_payload(self, mac, payload, writer):
        """Process incoming JSON and respond with either a stacked command or an ACK."""
        
        # 1. Handle Time Sync (Always priority handshake)
        if payload.get("cmd") == "time":
            await self.send_protocol_response(writer, "handshake")
            return

        # 2. Send response - either from stacked command or standard ACK
        queue = self.command_queues.get(mac)

        if queue and not queue.empty():
            try:
                # Get the next command from the stack
                cmd_dict = queue.get_nowait()
                cmd_dict["MsgID"] = datetime.now().strftime("%Y%m%d%H%M%S")
                
                payload_to_send = json.dumps(cmd_dict, separators=(',', ':')).encode('ascii')
                writer.write(payload_to_send)
                await writer.drain()
                
                _LOGGER.debug("TRACE [%s]: Sent STACKED command instead of ACK: %s", mac, cmd_dict)
                command_sent = True
            except asyncio.QueueEmpty:
                pass
            except Exception as e:
                _LOGGER.error("TRACE [%s]: Error sending stacked command: %s", mac, e)
        else:
        # 3. Fallback to standard ACK
            try:
                ack = json.dumps({"result": "ok"}, separators=(',', ':')).encode('ascii')
                writer.write(ack)
                await writer.drain()
            except Exception as e:
                _LOGGER.error("TRACE [%s]: ACK failed: %s", mac, e)

        # 4. Offload the incoming data to the coordinator
        self.hass.async_create_task(self.coordinator.async_process_json(mac, payload))

    async def send_protocol_response(self, writer, resp_type):
        """Send standardized JSON response for SUB and cmd:time."""
        now = datetime.now()
        if resp_type == "discovery":
            payload = {
                "pair_key": "", "zone_no": "", 
                "temp_max": "", "temp_min": "", 
                "dis_room_temp": "", "dis_room_humi": "", "dis_zone_temp": "", 
                "equip_mode": "", "fan_mode": "", "fan_speed": "",
                "local_time": now.strftime("%Y%m%d%H%M"),
                "MsgID": now.strftime("%Y%m%d%H%M%S")
                }
        # Consistent response format for both handshake and time requests
        else:
            payload = {
                "local_time": now.strftime("%Y%m%d%H%M"),
                "MsgID": (now + timedelta(hours=TIME_ADJUST)).strftime("%Y%m%d%H%M%S")
            }
            
        try:
            resp = json.dumps(payload, separators=(',', ':')).encode('ascii')
            writer.write(resp)
            await writer.drain()
            _LOGGER.debug("Sent %s response", resp_type)
        except Exception as e:
            _LOGGER.error(f"Failed to send {resp_type}: {e}")

    async def send_smarttemp_command(self, mac, cmd_dict):
        """Add a command to the stack instead of sending it immediately."""
        if mac not in self.command_queues:
            self.command_queues[mac] = asyncio.Queue()
        
        # Add to stack
        await self.command_queues[mac].put(cmd_dict)
        _LOGGER.debug("TRACE [%s]: Command added to stack: %s", mac, cmd_dict)
    
    async def send_raw_command(self, mac, raw_json_string):
        """
        Wraps a naked command string into valid JSON with a MsgID.
        Input Example: "cmd":"read","type":"all"
        Output Sent: {"cmd":"read","type":"all","MsgID":"20260108120000"}
        """
        try:
            # Clean up the string if the user sent a 'naked' command
            if not raw_json_string.startswith("{"):
                raw_json_string = "{" + raw_json_string + "}"
            
            cmd_dict = json.loads(raw_json_string)
            
            # RE-USE the main engine to handle the queue logic
            await self.send_smarttemp_command(mac, cmd_dict)
            
            _LOGGER.debug("TRACE [%s]: Successfully stacked raw injection", mac)
        except json.JSONDecodeError as e:
            _LOGGER.error("TRACE [%s]: Invalid JSON injected: %s", mac, e)   
        
        if mac not in self.active_connections:
            _LOGGER.error(f"Injection failed: {mac} not connected")
            return False
