import asyncio
import json
import logging
from datetime import datetime, timedelta
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .const import DOMAIN, NEW_DEVICE_SIGNAL, TIME_ADJUST, TIMEOUT_SECONDS, BUFFER_LIMIT, HEARTBEAT_PAYLOAD, SUB_FRAME_PREFIX

_LOGGER = logging.getLogger(__name__)

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
        self.trace_count = 4
        
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
        """Sequential handler with bracket counting and dual-mode resync."""
        address = writer.get_extra_info('peername')
        _LOGGER.info("New connection from %s", address)
        
        current_mac = None
        buffer = b""
        resync_mode = False

        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(4096), timeout=TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    break
                if not data:
                    break
                
                # 1. Resync Logic: Discard until a known header appears
                if resync_mode:
                    sub_idx = data.find(SUB_FRAME_PREFIX)
                    hb_idx = data.find(HEARTBEAT_PAYLOAD)
                    target = sub_idx if sub_idx != -1 else hb_idx
                    if target != -1:
                        _LOGGER.info("Resync successful for %s", address)
                        data = data[target:]
                        buffer = b""
                        resync_mode = False
                    else:
                        continue

                buffer += data

                # 2. Handle SUB Frame (Registration)
                if buffer.startswith(SUB_FRAME_PREFIX) and b"\x0a" in buffer:
                    line_end = buffer.find(b"\x0a")
                    line = buffer[:line_end].decode('ascii').strip()
                    current_mac = line.split()[1]
                    self.active_connections[current_mac] = writer
                    if current_mac not in self.command_queues:
                        self.command_queues[current_mac] = asyncio.Queue()

                    # Send Discovery/Time sync to satisfy controller handshake
                    await self.send_protocol_response(writer, "discovery")
                    _LOGGER.info("MAC %s: Connected.", current_mac)
                    buffer = buffer[line_end+1:]
                    continue

                # 3. Heartbeat Cleanup
                if HEARTBEAT_PAYLOAD in buffer:
                    buffer = buffer.replace(HEARTBEAT_PAYLOAD, b"")
                    _LOGGER.debug("MAC %s: Heartbeat.", current_mac)

                # 4. JSON Bracket Counting Parser
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
                                mac = payload.get("mac", current_mac)
                                
                                # Update Coordinator state
                                if self.coordinator:
                                    await self.coordinator.async_process_json(mac, payload)
                                    # UI refresh trigger
                                    self.coordinator.async_set_updated_data(self.coordinator.data)
                                
                                # Process responses (Queued commands or ACK)
                                await self._respond_to_controller(mac, writer, payload)
                                
                                buffer = buffer[i+1:]
                                json_found = True
                                break 
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                continue
                    
                    if not json_found:
                        if len(buffer) > BUFFER_LIMIT:
                            _LOGGER.warning("MAC %s: Buffer overflow. Entering Resync.", current_mac)
                            buffer = b""
                            resync_mode = True
                        break 

        except Exception as e:
            _LOGGER.exception("Error in handle_client: %s", e)
        finally:
            if current_mac:
                _LOGGER.warning("MAC %s: Connection lost. Marking offline.", current_mac)
                self.active_connections.pop(current_mac, None)
                if self.coordinator:
                    # Mark online status as False for Home Assistant availability
                    if current_mac not in self.coordinator.data:
                        self.coordinator.data[current_mac] = {}
                    self.coordinator.data[current_mac]["online"] = False
                    self.coordinator.async_set_updated_data(self.coordinator.data)
            
            writer.close()
            try:
                await writer.wait_closed()
            except:
                pass

    async def _respond_to_controller(self, mac, writer, payload):
        """Standardized response: Send queued command if available, otherwise send ACK."""
        # Handle time requests separately
        if payload.get("cmd") == "time":
            await self.send_protocol_response(writer, "handshake")
            return

        # Try to send a command from the queue
        queue = self.command_queues.get(mac)
        if queue and not queue.empty():
            try:
                cmd_dict = queue.get_nowait()
                cmd_dict["MsgID"] = datetime.now().strftime("%Y%m%d%H%M%S")
                resp = json.dumps(cmd_dict, separators=(',', ':')).encode('ascii')
                writer.write(resp)
                await writer.drain()
                _LOGGER.debug("MAC %s: Sent queued command: %s", mac, cmd_dict)
                return
            except Exception:
                pass

        # Fallback to standard ACK to keep connection alive
        try:
            ack = json.dumps({"result": "ok"}, separators=(',', ':')).encode('ascii')
            writer.write(ack)
            await writer.drain()
        except Exception as e:
            _LOGGER.error("MAC %s: ACK failed: %s", mac, e)
            
    async def send_protocol_response(self, writer, resp_type):
        """Send standardized JSON response for SUB and cmd:time."""
        now = datetime.now()
        ts_msgid = now.strftime("%Y%m%d%H%M%S")
        ts_local = now.strftime("%Y%m%d%H%M")

        if resp_type == "discovery":
            payload = {
                "pair_key": "", "zone_no": "", 
                "temp_max": "", "temp_min": "", 
                "dis_room_temp": "", "dis_room_humi": "", "dis_zone_temp": "", 
                "equip_mode": "", "fan_mode": "", "fan_speed": "",
                "local_time": ts_local,
                "MsgID": ts_msgid
            }
        else:
            # Shifted timestamp for handshake if needed per TIME_ADJUST
            adj_now = now + timedelta(hours=TIME_ADJUST)
            payload = {
                "local_time": ts_local,
                "MsgID": adj_now.strftime("%Y%m%d%H%M%S")
            }
            
        try:
            resp = json.dumps(payload, separators=(',', ':')).encode('ascii')
            writer.write(resp)
            await writer.drain()
            _LOGGER.debug("Sent %s response", resp_type)
        except Exception as e:
            _LOGGER.error("Failed to send %s: %s", resp_type, e)

    async def send_smarttemp_command(self, mac, cmd_dict):
        """Add a command to the queue to be dispatched on the next controller response."""
        if mac not in self.command_queues:
            self.command_queues[mac] = asyncio.Queue()
        
        await self.command_queues[mac].put(cmd_dict)
        _LOGGER.debug("MAC %s: Command queued: %s", mac, cmd_dict)
    
    async def send_raw_command(self, mac, raw_json_string):
        """Wraps a naked command string into valid JSON and queues it."""
        try:
            if not raw_json_string.startswith("{"):
                raw_json_string = "{" + raw_json_string + "}"
            
            cmd_dict = json.loads(raw_json_string)
            await self.send_smarttemp_command(mac, cmd_dict)
        except json.JSONDecodeError as e:
            _LOGGER.error("MAC %s: Invalid JSON injection: %s", mac, e)