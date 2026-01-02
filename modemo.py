#!/usr/bin/env python3
"""
Cellular Modem Diagnostic & Configuration Tool
A comprehensive cross-platform terminal application for managing cellular modems

Supports:
- Windows (COM ports)
- Linux/Raspberry Pi (USB, ACM, UART serial ports)
- Auto-detection with optimized two-phase baud rate testing
- Multiple modem vendors (Quectel, Sierra Wireless, u-blox, Telit, SimCom, etc.)
"""

import serial
import time
import re
import json
import glob
import subprocess
import platform
import os
import threading
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.prompt import Prompt, Confirm
from rich.tree import Tree
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'

# Port blacklist - can be set via environment variable
# Example: export MODEMO_SKIP_PORTS="/dev/ttyUSB1,/dev/ttyUSB0"
SKIP_PORTS = set(os.environ.get('MODEMO_SKIP_PORTS', '').split(',')) if os.environ.get('MODEMO_SKIP_PORTS') else set()

# Debug mode - set MODEMO_DEBUG=1 for verbose output
DEBUG_MODE = os.environ.get('MODEMO_DEBUG', '').lower() in ('1', 'true', 'yes')


class ModemManagerHelper:
    """Helper to detect and manage ModemManager interference on Linux"""

    @staticmethod
    def is_running() -> bool:
        """Check if ModemManager is running"""
        if not IS_LINUX:
            return False

        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'ModemManager'],
                capture_output=True,
                text=True,
                timeout=2
            )
            return result.returncode == 0 and 'active' in result.stdout
        except Exception:
            return False

    @staticmethod
    def is_blocking_port(port: str) -> bool:
        """Check if ModemManager is using a specific port"""
        if not IS_LINUX:
            return False

        try:
            # Check using lsof
            result = subprocess.run(
                ['lsof', port],
                capture_output=True,
                text=True,
                timeout=2
            )
            return 'ModemManager' in result.stdout
        except Exception:
            return False

    @staticmethod
    def get_managed_ports() -> List[str]:
        """Get list of ports managed by ModemManager"""
        ports = []
        if not IS_LINUX:
            return ports

        try:
            # Use mmcli to list modems
            result = subprocess.run(
                ['mmcli', '-L'],
                capture_output=True,
                text=True,
                timeout=2
            )
            # Parse output for device paths
            for line in result.stdout.split('\n'):
                if 'device' in line.lower():
                    match = re.search(r'/dev/tty\w+', line)
                    if match:
                        ports.append(match.group(0))
        except Exception:
            pass

        return ports

    @staticmethod
    def stop_temporarily() -> bool:
        """Temporarily stop ModemManager (requires sudo)"""
        if not IS_LINUX:
            return False

        try:
            result = subprocess.run(
                ['systemctl', 'stop', 'ModemManager'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def restart() -> bool:
        """Restart ModemManager"""
        if not IS_LINUX:
            return False

        try:
            result = subprocess.run(
                ['systemctl', 'start', 'ModemManager'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False


@dataclass
class ATResponse:
    """Store AT command response with metadata"""
    command: str
    raw_response: str
    parsed_data: Dict
    timestamp: datetime
    success: bool
    error: Optional[str] = None


class ModemConnection:
    """Handle serial communication with cellular modem"""

    def __init__(self, port: str = "/dev/ttyUSB2", baudrate: int = 115200, timeout: int = 5):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.connection: Optional[serial.Serial] = None
        self.rtscts = None  # Will be auto-detected

    def connect(self, quick_test: bool = False) -> bool:
        """Establish serial connection to modem

        Args:
            quick_test: If True, use minimal retries and faster timeouts for detection
        """
        # For quick testing, only try one rtscts setting and minimal retries
        rtscts_settings = [False] if quick_test else [False, True]
        max_attempts = 1 if quick_test else 3
        init_sleep = 0.1 if quick_test else 0.5
        test_sleep = 0.2 if quick_test else 0.5

        for rtscts_setting in rtscts_settings:
            try:
                self.connection = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                    write_timeout=self.timeout,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    rtscts=rtscts_setting,
                    xonxoff=False,
                    dsrdtr=False,
                    exclusive=False  # Allow shared access to prevent blocking on Linux
                )
                time.sleep(init_sleep)

                # Clear any pending data
                self.connection.reset_input_buffer()
                self.connection.reset_output_buffer()
                if not quick_test:
                    time.sleep(0.2)

                # Test with AT command - try multiple times for broken pipe issues
                for attempt in range(max_attempts):
                    try:
                        self.connection.write(b'AT\r\n')
                        self.connection.flush()
                        time.sleep(test_sleep)
                        response = self.connection.read(self.connection.in_waiting or 100).decode('utf-8',
                                                                                                  errors='ignore')

                        if 'OK' in response or 'AT' in response:
                            # Connection works with this flow control setting
                            self.rtscts = rtscts_setting
                            # Clear buffers again for clean slate
                            self.connection.reset_input_buffer()
                            self.connection.reset_output_buffer()
                            return True

                    except (BrokenPipeError, OSError) as e:
                        if attempt < max_attempts - 1 and not quick_test:
                            time.sleep(0.3)
                            continue
                        else:
                            if not quick_test:
                                raise
                            break

                # No response, try next setting
                self.connection.close()

            except Exception as e:
                if self.connection and self.connection.is_open:
                    self.connection.close()
                # Only show error if not quick test and this was the last attempt
                if rtscts_setting == rtscts_settings[-1] and not quick_test:
                    console.print(f"[red]Connection Error: {e}[/red]")
                continue

        return False

    def disconnect(self):
        """Close serial connection"""
        if self.connection and self.connection.is_open:
            self.connection.close()

    def send_at_command(self, command: str, wait_time: float = 1.0) -> ATResponse:
        """Send AT command and return parsed response"""
        if not self.connection or not self.connection.is_open:
            return ATResponse(
                command=command,
                raw_response="",
                parsed_data={},
                timestamp=datetime.now(),
                success=False,
                error="No connection"
            )

        try:
            # Ensure command ends with \r\n
            if not command.endswith('\r\n'):
                command = command + '\r\n'

            # Clear buffers
            self.connection.reset_input_buffer()

            # Send command
            self.connection.write(command.encode('utf-8'))
            time.sleep(wait_time)

            # Read response
            response = ""
            while self.connection.in_waiting:
                response += self.connection.read(self.connection.in_waiting).decode('utf-8', errors='ignore')
                time.sleep(0.1)

            # Parse response
            success = "OK" in response and "ERROR" not in response
            error = "ERROR" if "ERROR" in response else None

            return ATResponse(
                command=command.strip(),
                raw_response=response,
                parsed_data=self._parse_response(command.strip(), response),
                timestamp=datetime.now(),
                success=success,
                error=error
            )

        except Exception as e:
            return ATResponse(
                command=command,
                raw_response="",
                parsed_data={},
                timestamp=datetime.now(),
                success=False,
                error=str(e)
            )

    def _parse_response(self, command: str, response: str) -> Dict:
        """Parse AT command response into structured data"""
        parsed = {"raw": response}

        # Remove echo and OK/ERROR
        lines = [line.strip() for line in response.split('\n') if line.strip()]
        lines = [line for line in lines if line not in [command, 'OK', 'ERROR', '']]

        if not lines:
            return parsed

        # Parse based on command type
        if '+COPS' in command:
            parsed.update(self._parse_cops(lines))
        elif '+CREG' in command or '+CGREG' in command or '+CEREG' in command:
            parsed.update(self._parse_registration(lines))
        elif '+CSQ' in command:
            parsed.update(self._parse_csq(lines))
        elif '+CGDCONT' in command:
            parsed.update(self._parse_cgdcont(lines))
        elif '+CPIN' in command:
            parsed.update(self._parse_cpin(lines))
        elif '+CIMI' in command:
            parsed['imsi'] = lines[0] if lines else ''
        elif '+CCID' in command or '+ICCID' in command or '+QCCID' in command:
            parsed['iccid'] = re.sub(r'[^0-9]', '', lines[0]) if lines else ''
        elif '+CGMI' in command:
            parsed['manufacturer'] = lines[0] if lines else ''
        elif '+CGMM' in command:
            parsed['model'] = lines[0] if lines else ''
        elif '+CGMR' in command:
            parsed['firmware'] = lines[0] if lines else ''
        elif '+CGSN' in command:
            parsed['imei'] = lines[0] if lines else ''
        elif 'I' == command or 'ATI' in command:
            parsed['info'] = '\n'.join(lines)
        # Quectel-specific commands
        elif '+QENG' in command:
            parsed.update(self._parse_qeng(lines))
        elif '+QNWINFO' in command:
            parsed.update(self._parse_qnwinfo(lines))
        elif '+QSPN' in command:
            parsed.update(self._parse_qspn(lines))

        return parsed

    def _parse_qeng(self, lines: List[str]) -> Dict:
        """Parse Quectel +QENG serving cell information"""
        result = {}
        for line in lines:
            if '+QENG:' in line:
                parts = line.replace('+QENG:', '').strip().split(',')
                if len(parts) > 0:
                    result['servingcell_type'] = parts[0].strip('"')
                    if parts[0].strip('"') == 'servingcell':
                        # LTE serving cell info
                        if len(parts) >= 15:
                            result['state'] = parts[1].strip('"')
                            result['mode'] = parts[2].strip('"')
                            result['mcc'] = parts[4].strip('"')
                            result['mnc'] = parts[5].strip('"')
                            result['cellid'] = parts[6].strip('"')
                            result['pcid'] = parts[7]
                            result['earfcn'] = parts[8]
                            result['freq_band'] = parts[9]
                            result['ul_bandwidth'] = parts[10]
                            result['dl_bandwidth'] = parts[11]
                            result['tac'] = parts[12].strip('"')
                            result['rsrp'] = f"{parts[13]} dBm"
                            result['rsrq'] = f"{parts[14]} dB"
                            result['rssi'] = f"{parts[15]} dBm" if len(parts) > 15 else ''
                            result['sinr'] = f"{parts[16]} dB" if len(parts) > 16 else ''
        return result

    def _parse_qnwinfo(self, lines: List[str]) -> Dict:
        """Parse Quectel +QNWINFO network information"""
        result = {}
        for line in lines:
            if '+QNWINFO:' in line:
                # +QNWINFO: <Act>,<oper>,<band>,<channel>
                match = re.search(r'\+QNWINFO:\s*"([^"]*)",?"([^"]*)",?"([^"]*)",?(\d+)', line)
                if match:
                    result['access_tech'] = match.group(1)
                    result['operator'] = match.group(2)
                    result['band'] = match.group(3)
                    result['channel'] = match.group(4)
        return result

    def _parse_qspn(self, lines: List[str]) -> Dict:
        """Parse Quectel +QSPN service provider name"""
        result = {}
        for line in lines:
            if '+QSPN:' in line:
                match = re.search(r'\+QSPN:\s*"([^"]*)",?"([^"]*)",?"([^"]*)"', line)
                if match:
                    result['fnn'] = match.group(1)  # Full name
                    result['snn'] = match.group(2)  # Short name
                    result['spn'] = match.group(3)  # Service provider name
        return result

    def _parse_cops(self, lines: List[str]) -> Dict:
        """Parse +COPS operator selection response"""
        result = {}
        for line in lines:
            if '+COPS:' in line:
                # +COPS: <mode>[,<format>,<oper>[,<AcT>]]
                match = re.search(r'\+COPS:\s*(\d+)(?:,(\d+),"([^"]*)"(?:,(\d+))?)?', line)
                if match:
                    mode = int(match.group(1))
                    result['mode'] = mode
                    result['mode_text'] = {
                        0: 'Automatic',
                        1: 'Manual',
                        2: 'Deregister',
                        3: 'Set format only',
                        4: 'Manual/Automatic'
                    }.get(mode, f'Unknown ({mode})')

                    if match.group(2):
                        result['format'] = int(match.group(2))
                    if match.group(3):
                        result['operator'] = match.group(3)
                    if match.group(4):
                        act = int(match.group(4))
                        result['access_tech'] = act
                        result['access_tech_text'] = {
                            0: 'GSM',
                            1: 'GSM Compact',
                            2: 'UTRAN',
                            3: 'GSM w/EGPRS',
                            4: 'UTRAN w/HSDPA',
                            5: 'UTRAN w/HSUPA',
                            6: 'UTRAN w/HSDPA and HSUPA',
                            7: 'E-UTRAN',
                            8: 'EC-GSM-IoT',
                            9: 'E-UTRAN (NB-S1 mode)',
                            10: 'E-UTRA connected to 5GCN',
                            11: 'NR connected to 5GCN'
                        }.get(act, f'Unknown ({act})')
        return result

    def _parse_registration(self, lines: List[str]) -> Dict:
        """Parse +CREG/+CGREG/+CEREG network registration response"""
        result = {}
        for line in lines:
            match = re.search(r'\+(CREG|CGREG|CEREG):\s*(\d+)(?:,(\d+))?(?:,"([0-9A-F]+)","([0-9A-F]+)")?(?:,(\d+))?',
                              line)
            if match:
                reg_type = match.group(1).lower()
                n = int(match.group(2))
                stat = int(match.group(3)) if match.group(3) else n

                result[f'{reg_type}_status'] = stat
                result[f'{reg_type}_status_text'] = {
                    0: 'Not registered, not searching',
                    1: 'Registered, home network',
                    2: 'Not registered, searching',
                    3: 'Registration denied',
                    4: 'Unknown',
                    5: 'Registered, roaming'
                }.get(stat, f'Unknown ({stat})')

                if match.group(4):
                    result['lac'] = match.group(4)
                if match.group(5):
                    result['ci'] = match.group(5)
                if match.group(6):
                    act = int(match.group(6))
                    result['act'] = act
                    result['act_text'] = {
                        0: 'GSM',
                        1: 'GSM Compact',
                        2: 'UTRAN',
                        3: 'GSM w/EGPRS',
                        4: 'UTRAN w/HSDPA',
                        5: 'UTRAN w/HSUPA',
                        6: 'UTRAN w/HSDPA and HSUPA',
                        7: 'E-UTRAN',
                        8: 'EC-GSM-IoT',
                        9: 'E-UTRAN (NB-S1 mode)'
                    }.get(act, f'Unknown ({act})')
        return result

    def _parse_csq(self, lines: List[str]) -> Dict:
        """Parse +CSQ signal quality response"""
        result = {}
        for line in lines:
            match = re.search(r'\+CSQ:\s*(\d+),(\d+)', line)
            if match:
                rssi = int(match.group(1))
                ber = int(match.group(2))

                result['rssi_raw'] = rssi
                result['ber_raw'] = ber

                # Convert RSSI to dBm
                if rssi == 0:
                    result['rssi_dbm'] = '<= -113 dBm'
                    result['signal_quality'] = 'Very Poor'
                elif rssi == 1:
                    result['rssi_dbm'] = '-111 dBm'
                    result['signal_quality'] = 'Very Poor'
                elif 2 <= rssi <= 30:
                    dbm = -109 + (rssi - 2) * 2
                    result['rssi_dbm'] = f'{dbm} dBm'
                    if rssi < 10:
                        result['signal_quality'] = 'Poor'
                    elif rssi < 15:
                        result['signal_quality'] = 'Fair'
                    elif rssi < 20:
                        result['signal_quality'] = 'Good'
                    else:
                        result['signal_quality'] = 'Excellent'
                elif rssi == 31:
                    result['rssi_dbm'] = '>= -51 dBm'
                    result['signal_quality'] = 'Excellent'
                else:
                    result['rssi_dbm'] = 'Unknown'
                    result['signal_quality'] = 'Unknown'

                # BER interpretation
                if ber == 99:
                    result['ber_text'] = 'Unknown or not detectable'
                else:
                    result[
                        'ber_text'] = f'{ber} ({["<0.2%", "0.2-0.4%", "0.4-0.8%", "0.8-1.6%", "1.6-3.2%", "3.2-6.4%", "6.4-12.8%", ">12.8%"][min(ber, 7)]})'

        return result

    def _parse_cgdcont(self, lines: List[str]) -> Dict:
        """Parse +CGDCONT PDP context response"""
        result = {'contexts': []}
        for line in lines:
            match = re.search(r'\+CGDCONT:\s*(\d+),"([^"]*)","([^"]*)"(?:,"([^"]*)")?', line)
            if match:
                context = {
                    'cid': int(match.group(1)),
                    'pdp_type': match.group(2),
                    'apn': match.group(3),
                    'pdp_addr': match.group(4) if match.group(4) else ''
                }
                result['contexts'].append(context)
        return result

    def _parse_cpin(self, lines: List[str]) -> Dict:
        """Parse +CPIN SIM status response"""
        result = {}
        for line in lines:
            if '+CPIN:' in line:
                status = line.split(':')[1].strip()
                result['sim_status'] = status
                result['sim_ready'] = status == 'READY'
                result['sim_status_text'] = {
                    'READY': 'SIM is ready',
                    'SIM PIN': 'SIM requires PIN',
                    'SIM PUK': 'SIM requires PUK',
                    'SIM PIN2': 'SIM requires PIN2',
                    'SIM PUK2': 'SIM requires PUK2'
                }.get(status, status)
        return result


class DiagnosticTests:
    """Comprehensive diagnostic test suite"""

    def __init__(self, modem: ModemConnection):
        self.modem = modem
        self.results = []
        self.modem_vendor = None
        self.modem_model = None

    def detect_modem_vendor(self):
        """Detect modem manufacturer and model for vendor-specific optimizations"""
        manu_result = self.modem.send_at_command("AT+CGMI")
        model_result = self.modem.send_at_command("AT+CGMM")

        if 'manufacturer' in manu_result.parsed_data:
            manu = manu_result.parsed_data['manufacturer'].upper()
            if 'QUECTEL' in manu:
                self.modem_vendor = 'Quectel'
            elif 'SIERRA' in manu:
                self.modem_vendor = 'Sierra Wireless'
            elif 'UBLOX' in manu or 'U-BLOX' in manu:
                self.modem_vendor = 'u-blox'
            elif 'TELIT' in manu:
                self.modem_vendor = 'Telit'
            elif 'SIMCOM' in manu:
                self.modem_vendor = 'SimCom'
            else:
                self.modem_vendor = manu_result.parsed_data['manufacturer']

        if 'model' in model_result.parsed_data:
            self.modem_model = model_result.parsed_data['model']

    def run_full_diagnostic(self) -> List[ATResponse]:
        """Run complete diagnostic test suite"""
        self.results = []

        # Detect vendor first
        self.detect_modem_vendor()

        # Standard tests
        tests = [
            ("AT", "Basic communication test"),
            ("ATI", "Modem information"),
            ("AT+CGMI", "Manufacturer identification"),
            ("AT+CGMM", "Model identification"),
            ("AT+CGMR", "Firmware version"),
            ("AT+CGSN", "IMEI"),
            ("AT+CPIN?", "SIM status"),
            ("AT+CCID", "ICCID (SIM serial)"),
            ("AT+CIMI", "IMSI"),
            ("AT+CSQ", "Signal quality"),
            ("AT+CREG?", "Network registration (CS)"),
            ("AT+CGREG?", "GPRS registration (PS)"),
            ("AT+CEREG?", "EPS registration (LTE)"),
            ("AT+COPS?", "Operator selection"),
            ("AT+CGDCONT?", "PDP context"),
        ]

        # Add vendor-specific tests
        if self.modem_vendor == 'Quectel':
            tests.extend(self._get_quectel_tests())
        elif self.modem_vendor == 'Sierra Wireless':
            tests.extend(self._get_sierra_tests())
        elif self.modem_vendor == 'u-blox':
            tests.extend(self._get_ublox_tests())

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[cyan]Running diagnostic tests...", total=len(tests))

            for cmd, description in tests:
                progress.update(task, description=f"[cyan]{description}")
                result = self.modem.send_at_command(cmd)
                self.results.append(result)
                progress.advance(task)
                time.sleep(0.2)

        return self.results

    def _get_quectel_tests(self) -> List[Tuple[str, str]]:
        """Quectel-specific diagnostic commands"""
        return [
            ("AT+QENG=\"servingcell\"", "Serving cell info (Quectel)"),
            ("AT+QNWINFO", "Network information (Quectel)"),
            ("AT+QSPN", "Service provider name (Quectel)"),
            ("AT+QCCID", "ICCID via Quectel command"),
        ]

    def _get_sierra_tests(self) -> List[Tuple[str, str]]:
        """Sierra Wireless-specific diagnostic commands"""
        return [
            ("AT!GSTATUS?", "Status information (Sierra)"),
            ("AT+KCELLMEAS=1", "Cell measurements (Sierra)"),
        ]

    def _get_ublox_tests(self) -> List[Tuple[str, str]]:
        """u-blox-specific diagnostic commands"""
        return [
            ("AT+UCGED?", "Cell information (u-blox)"),
            ("AT+UREG?", "Registration status (u-blox)"),
        ]

    def display_results(self):
        """Display diagnostic results in formatted tables"""
        console.print("\n")
        console.rule("[bold cyan]Diagnostic Test Results", style="cyan")

        # Show vendor info if detected
        if self.modem_vendor:
            console.print(f"\n[bold magenta]Detected Modem:[/bold magenta] {self.modem_vendor}", end="")
            if self.modem_model:
                console.print(f" - {self.modem_model}")
            else:
                console.print()

        console.print()

        # Device Information
        self._display_device_info()
        console.print()

        # SIM Information
        self._display_sim_info()
        console.print()

        # Network Status
        self._display_network_status()
        console.print()

        # Signal Quality
        self._display_signal_quality()
        console.print()

        # PDP Context
        self._display_pdp_context()

        # Vendor-specific information
        if self.modem_vendor == 'Quectel':
            console.print()
            self._display_quectel_advanced()

    def _display_quectel_advanced(self):
        """Display Quectel-specific advanced information"""
        # Check if we have Quectel-specific data
        has_qeng = any('servingcell_type' in r.parsed_data for r in self.results)
        has_qnwinfo = any('access_tech' in r.parsed_data and 'band' in r.parsed_data for r in self.results)

        if not has_qeng and not has_qnwinfo:
            return

        table = Table(title="Advanced Cell Information (Quectel)", box=box.ROUNDED, show_header=True,
                      header_style="bold magenta")
        table.add_column("Parameter", style="cyan", width=20)
        table.add_column("Value", style="white", width=30)
        table.add_column("Details", style="white")

        for result in self.results:
            parsed = result.parsed_data

            # QENG serving cell data
            if 'servingcell_type' in parsed and parsed['servingcell_type'] == 'servingcell':
                table.add_row("Cell ID", parsed.get('cellid', ''), f"PCI: {parsed.get('pcid', '')}")
                table.add_row("Frequency", f"EARFCN: {parsed.get('earfcn', '')}",
                              f"Band: {parsed.get('freq_band', '')}")
                table.add_row("Bandwidth", f"DL: {parsed.get('dl_bandwidth', '')} MHz",
                              f"UL: {parsed.get('ul_bandwidth', '')} MHz")
                table.add_row("TAC", parsed.get('tac', ''), "")

                # LTE signal metrics
                if 'rsrp' in parsed:
                    rsrp_val = int(parsed['rsrp'].split()[0]) if parsed['rsrp'] else -999
                    rsrp_color = "green" if rsrp_val > -100 else "yellow" if rsrp_val > -110 else "red"
                    table.add_row("RSRP", f"[{rsrp_color}]{parsed.get('rsrp', '')}[/{rsrp_color}]",
                                  "Reference Signal Received Power")

                if 'rsrq' in parsed:
                    table.add_row("RSRQ", parsed.get('rsrq', ''), "Reference Signal Received Quality")

                if 'rssi' in parsed:
                    table.add_row("RSSI", parsed.get('rssi', ''), "Received Signal Strength Indicator")

                if 'sinr' in parsed:
                    sinr_val = int(parsed['sinr'].split()[0]) if parsed['sinr'] else -999
                    sinr_color = "green" if sinr_val > 13 else "yellow" if sinr_val > 0 else "red"
                    table.add_row("SINR", f"[{sinr_color}]{parsed.get('sinr', '')}[/{sinr_color}]",
                                  "Signal to Interference plus Noise Ratio")

            # QNWINFO data
            if 'access_tech' in parsed and 'band' in parsed:
                table.add_row("Technology", parsed.get('access_tech', ''), f"Band: {parsed.get('band', '')}")
                table.add_row("Channel", parsed.get('channel', ''), "")

            # QSPN data
            if 'spn' in parsed:
                table.add_row("SPN", parsed.get('spn', ''), f"FNN: {parsed.get('fnn', '')}")

        if table.row_count > 0:
            console.print(table)

    def _display_device_info(self):
        """Display device information table"""
        table = Table(title="Device Information", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan", width=20)
        table.add_column("Value", style="white")

        for result in self.results:
            if 'manufacturer' in result.parsed_data:
                table.add_row("Manufacturer", result.parsed_data['manufacturer'])
            if 'model' in result.parsed_data:
                table.add_row("Model", result.parsed_data['model'])
            if 'firmware' in result.parsed_data:
                table.add_row("Firmware", result.parsed_data['firmware'])
            if 'imei' in result.parsed_data:
                table.add_row("IMEI", result.parsed_data['imei'])

        console.print(table)

    def _display_sim_info(self):
        """Display SIM information table"""
        table = Table(title="SIM Card Information", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan", width=20)
        table.add_column("Value", style="white")
        table.add_column("Status", style="white")

        for result in self.results:
            if 'sim_status' in result.parsed_data:
                status_color = "green" if result.parsed_data.get('sim_ready', False) else "red"
                table.add_row(
                    "SIM Status",
                    result.parsed_data['sim_status'],
                    f"[{status_color}]{result.parsed_data.get('sim_status_text', '')}[/{status_color}]"
                )
            if 'iccid' in result.parsed_data:
                table.add_row("ICCID", result.parsed_data['iccid'], "")
            if 'imsi' in result.parsed_data:
                table.add_row("IMSI", result.parsed_data['imsi'], "")

        console.print(table)

    def _display_network_status(self):
        """Display network registration status"""
        table = Table(title="Network Registration Status", box=box.ROUNDED, show_header=True,
                      header_style="bold magenta")
        table.add_column("Type", style="cyan", width=15)
        table.add_column("Status Code", style="white", width=12)
        table.add_column("Status", style="white", width=30)
        table.add_column("Details", style="white")

        for result in self.results:
            parsed = result.parsed_data

            # CS Registration
            if 'creg_status' in parsed:
                status = parsed['creg_status']
                status_color = "green" if status in [1, 5] else "yellow" if status == 2 else "red"
                details = []
                if 'lac' in parsed:
                    details.append(f"LAC: {parsed['lac']}")
                if 'ci' in parsed:
                    details.append(f"CI: {parsed['ci']}")
                table.add_row(
                    "CS (Voice)",
                    str(status),
                    f"[{status_color}]{parsed.get('creg_status_text', '')}[/{status_color}]",
                    ", ".join(details)
                )

            # PS Registration
            if 'cgreg_status' in parsed:
                status = parsed['cgreg_status']
                status_color = "green" if status in [1, 5] else "yellow" if status == 2 else "red"
                details = []
                if 'lac' in parsed:
                    details.append(f"LAC: {parsed['lac']}")
                if 'ci' in parsed:
                    details.append(f"CI: {parsed['ci']}")
                if 'act_text' in parsed:
                    details.append(f"AcT: {parsed['act_text']}")
                table.add_row(
                    "PS (Data)",
                    str(status),
                    f"[{status_color}]{parsed.get('cgreg_status_text', '')}[/{status_color}]",
                    ", ".join(details)
                )

            # EPS Registration
            if 'cereg_status' in parsed:
                status = parsed['cereg_status']
                status_color = "green" if status in [1, 5] else "yellow" if status == 2 else "red"
                details = []
                if 'lac' in parsed:
                    details.append(f"TAC: {parsed['lac']}")
                if 'ci' in parsed:
                    details.append(f"CI: {parsed['ci']}")
                if 'act_text' in parsed:
                    details.append(f"AcT: {parsed['act_text']}")
                table.add_row(
                    "EPS (LTE)",
                    str(status),
                    f"[{status_color}]{parsed.get('cereg_status_text', '')}[/{status_color}]",
                    ", ".join(details)
                )

            # Operator
            if 'operator' in parsed:
                mode_text = parsed.get('mode_text', '')
                act_text = parsed.get('access_tech_text', '')
                table.add_row(
                    "Operator",
                    "",
                    parsed['operator'],
                    f"{mode_text}, {act_text}" if act_text else mode_text
                )

        console.print(table)

    def _display_signal_quality(self):
        """Display signal quality metrics"""
        table = Table(title="Signal Quality", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Raw Value", style="white", width=12)
        table.add_column("Converted", style="white", width=20)
        table.add_column("Assessment", style="white")

        for result in self.results:
            if 'rssi_raw' in result.parsed_data:
                parsed = result.parsed_data
                rssi_raw = parsed['rssi_raw']
                quality = parsed.get('signal_quality', 'Unknown')

                # Color code based on quality
                quality_color = {
                    'Excellent': 'green',
                    'Good': 'green',
                    'Fair': 'yellow',
                    'Poor': 'red',
                    'Very Poor': 'red'
                }.get(quality, 'white')

                table.add_row(
                    "RSSI",
                    str(rssi_raw),
                    parsed.get('rssi_dbm', ''),
                    f"[{quality_color}]{quality}[/{quality_color}]"
                )

                table.add_row(
                    "BER",
                    str(parsed['ber_raw']),
                    parsed.get('ber_text', ''),
                    ""
                )

        console.print(table)

    def _display_pdp_context(self):
        """Display PDP context configuration"""
        for result in self.results:
            if 'contexts' in result.parsed_data and result.parsed_data['contexts']:
                table = Table(title="PDP Context Configuration", box=box.ROUNDED, show_header=True,
                              header_style="bold magenta")
                table.add_column("CID", style="cyan", width=5)
                table.add_column("PDP Type", style="white", width=10)
                table.add_column("APN", style="white", width=30)
                table.add_column("Address", style="white")

                for ctx in result.parsed_data['contexts']:
                    table.add_row(
                        str(ctx['cid']),
                        ctx['pdp_type'],
                        ctx['apn'],
                        ctx['pdp_addr']
                    )

                console.print(table)


class NetworkTools:
    """Network troubleshooting and configuration tools"""

    def __init__(self, modem: ModemConnection):
        self.modem = modem

    def scan_networks(self):
        """Scan for available networks"""
        console.print("\n[yellow]Scanning for available networks (this may take 30-60 seconds)...[/yellow]")

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[cyan]Scanning...", total=None)
            result = self.modem.send_at_command("AT+COPS=?", wait_time=60)

        if not result.success:
            console.print(f"[red]Scan failed: {result.error or 'Unknown error'}[/red]")
            return

        # Parse network list
        networks = []
        pattern = r'\((\d+),"([^"]*)","([^"]*)","(\d+)",(\d+)\)'
        matches = re.findall(pattern, result.raw_response)

        if not matches:
            console.print("[yellow]No networks found or unable to parse results[/yellow]")
            return

        table = Table(title="Available Networks", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Status", style="cyan", width=15)
        table.add_column("Operator (Long)", style="white", width=30)
        table.add_column("Operator (Short)", style="white", width=20)
        table.add_column("Network Code", style="white", width=15)
        table.add_column("Technology", style="white")

        status_map = {
            '0': 'Unknown',
            '1': '[green]Available[/green]',
            '2': '[blue]Current[/blue]',
            '3': '[red]Forbidden[/red]'
        }

        tech_map = {
            '0': 'GSM',
            '1': 'GSM Compact',
            '2': 'UTRAN',
            '3': 'GSM w/EGPRS',
            '4': 'UTRAN w/HSDPA',
            '5': 'UTRAN w/HSUPA',
            '6': 'UTRAN w/HSUPA+HSDPA',
            '7': 'E-UTRAN (LTE)',
            '8': 'EC-GSM-IoT',
            '9': 'E-UTRAN NB-S1'
        }

        for match in matches:
            stat, long_name, short_name, numeric, tech = match
            table.add_row(
                status_map.get(stat, stat),
                long_name,
                short_name,
                numeric,
                tech_map.get(tech, f"Unknown ({tech})")
            )

        console.print("\n")
        console.print(table)

    def clear_fplmn(self):
        """Clear forbidden network list (FPLMN)"""
        console.print("\n[bold yellow]Clear Forbidden Network List (FPLMN)[/bold yellow]")
        console.print("This will clear the list of networks the modem has been denied access to.\n")

        if not Confirm.ask("Do you want to proceed?"):
            console.print("[yellow]Operation cancelled[/yellow]")
            return

        # Common AT commands to clear FPLMN (varies by modem)
        commands = [
            ("AT+CRSM=214,28539,0,0,12,\"FFFFFFFFFFFFFFFFFFFFFFFF\"", "Clear FPLMN (Method 1)"),
            ("AT+CPOL=", "Clear preferred operator list"),
        ]

        console.print()
        for cmd, description in commands:
            console.print(f"[cyan]Executing: {description}[/cyan]")
            result = self.modem.send_at_command(cmd)

            if result.success:
                console.print(f"[green]✓ {description} successful[/green]")
            else:
                console.print(f"[yellow]⚠ {description} failed (may not be supported)[/yellow]")

            console.print(f"Response: {result.raw_response.strip()}\n")

        console.print("[green]FPLMN clear operation completed[/green]")
        console.print("[yellow]Note: You may need to restart the modem for changes to take effect[/yellow]")

    def view_fplmn(self):
        """View forbidden network list (FPLMN)"""
        console.print("\n[bold cyan]Forbidden Network List (FPLMN)[/bold cyan]\n")
        console.print("This shows networks that the modem has been denied access to.\n")

        # Method 1: Try to read FPLMN from SIM EF_FPLMN file
        console.print("[cyan]Attempting to read FPLMN from SIM...[/cyan]")
        result = self.modem.send_at_command('AT+CRSM=176,28539,0,0,12')

        if result.success and result.raw_response:
            console.print(Panel(result.raw_response, title="[cyan]FPLMN Data (Raw)[/cyan]", box=box.ROUNDED))

            # Try to parse hex data
            # FPLMN is stored as 3-byte BCD entries (MCC+MNC)
            # Format: AA BB CC where AA/BB = MCC, CC = MNC
            console.print("\n[dim]Note: FPLMN is stored in BCD format (3 bytes per entry)[/dim]")
            console.print("[dim]Example: '13 F0 62' = MCC 310, MNC 260 (T-Mobile US)[/dim]")
        else:
            console.print("[yellow]Could not read FPLMN from SIM (may not be supported)[/yellow]")

        console.print()

        # Method 2: Check preferred operator list (CPOL)
        console.print("[cyan]Checking Preferred Operator List (CPOL)...[/cyan]")
        cpol_result = self.modem.send_at_command('AT+CPOL?')

        if cpol_result.success and cpol_result.raw_response:
            console.print(Panel(cpol_result.raw_response, title="[cyan]Preferred Operators[/cyan]", box=box.ROUNDED))
        else:
            console.print("[yellow]Could not read CPOL (may not be supported)[/yellow]")

        console.print()

        # Method 3: Try alternative CPLS command (some modems)
        console.print("[cyan]Checking for alternative FPLMN commands...[/cyan]")
        cpls_result = self.modem.send_at_command('AT+CPLS?')

        if cpls_result.success and 'OK' in cpls_result.raw_response:
            console.print(Panel(cpls_result.raw_response, title="[cyan]PLMN Selection[/cyan]", box=box.ROUNDED))
        else:
            console.print("[yellow]Alternative commands not supported on this modem[/yellow]")

        console.print()
        console.print("[dim]Note: If FPLMN appears empty (FFFFFF...), no networks are currently forbidden.[/dim]")

    def configure_apn(self):
        """Configure APN settings"""
        console.print("\n[bold cyan]Configure APN Settings[/bold cyan]\n")

        # Get current settings
        result = self.modem.send_at_command("AT+CGDCONT?")

        if 'contexts' in result.parsed_data and result.parsed_data['contexts']:
            console.print("[cyan]Current PDP Contexts:[/cyan]")
            for ctx in result.parsed_data['contexts']:
                console.print(f"  CID {ctx['cid']}: {ctx['pdp_type']}, APN: {ctx['apn']}")
            console.print()

        # Get user input
        cid = Prompt.ask("Enter Context ID (CID)", default="1")
        pdp_type = Prompt.ask("Enter PDP Type", choices=["IP", "IPV6", "IPV4V6"], default="IP")
        apn = Prompt.ask("Enter APN name", default="hologram")

        # Set APN
        cmd = f'AT+CGDCONT={cid},"{pdp_type}","{apn}"'
        console.print(f"\n[cyan]Executing: {cmd}[/cyan]")

        result = self.modem.send_at_command(cmd)

        if result.success:
            console.print("[green]✓ APN configuration successful[/green]")
        else:
            console.print(f"[red]✗ APN configuration failed: {result.error}[/red]")

        # Verify
        console.print("\n[cyan]Verifying configuration...[/cyan]")
        verify_result = self.modem.send_at_command("AT+CGDCONT?")

        if 'contexts' in verify_result.parsed_data:
            for ctx in verify_result.parsed_data['contexts']:
                if ctx['cid'] == int(cid):
                    console.print(f"[green]✓ CID {cid}: {ctx['pdp_type']}, APN: {ctx['apn']}[/green]")

    def force_network_registration(self):
        """Force network registration with specific operator"""
        console.print("\n[bold cyan]Force Network Registration[/bold cyan]\n")

        console.print("First, let's scan for available networks...")
        self.scan_networks()

        console.print("\n[yellow]Enter network selection mode:[/yellow]")
        console.print("  0 = Automatic")
        console.print("  1 = Manual")
        console.print("  4 = Manual with fallback to automatic\n")

        mode = Prompt.ask("Select mode", choices=["0", "1", "4"], default="0")

        if mode != "0":
            operator = Prompt.ask("Enter operator numeric code (e.g., 310260 for T-Mobile US)")
            cmd = f'AT+COPS={mode},2,"{operator}"'
        else:
            cmd = "AT+COPS=0"

        console.print(f"\n[cyan]Executing: {cmd}[/cyan]")
        console.print("[yellow]This may take 30-60 seconds...[/yellow]\n")

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[cyan]Registering...", total=None)
            result = self.modem.send_at_command(cmd, wait_time=60)

        if result.success:
            console.print("[green]✓ Registration command successful[/green]")
        else:
            console.print(f"[red]✗ Registration failed: {result.error}[/red]")

        # Check registration status
        console.print("\n[cyan]Checking registration status...[/cyan]")
        time.sleep(2)

        reg_result = self.modem.send_at_command("AT+CREG?")
        if 'creg_status_text' in reg_result.parsed_data:
            console.print(f"Status: {reg_result.parsed_data['creg_status_text']}")


class DataUsageTools:
    """Tools for monitoring and troubleshooting data usage"""

    def __init__(self, modem: ModemConnection):
        self.modem = modem

    def check_pdp_status(self):
        """Check PDP context activation status"""
        console.print("\n[bold cyan]PDP Context Status[/bold cyan]\n")

        # Get context definition
        result = self.modem.send_at_command("AT+CGDCONT?")
        if 'contexts' in result.parsed_data:
            console.print("[cyan]Defined PDP Contexts:[/cyan]")
            for ctx in result.parsed_data['contexts']:
                console.print(f"  CID {ctx['cid']}: {ctx['pdp_type']}, APN: {ctx['apn']}")

        console.print()

        # Get activation status
        act_result = self.modem.send_at_command("AT+CGACT?")
        console.print("[cyan]PDP Context Activation Status:[/cyan]")

        for line in act_result.raw_response.split('\n'):
            if '+CGACT:' in line:
                match = re.search(r'\+CGACT:\s*(\d+),(\d+)', line)
                if match:
                    cid = match.group(1)
                    state = int(match.group(2))
                    state_text = "[green]Active[/green]" if state == 1 else "[red]Inactive[/red]"
                    console.print(f"  CID {cid}: {state_text}")

        console.print()

        # Get IP address if available
        addr_result = self.modem.send_at_command("AT+CGPADDR")
        console.print("[cyan]IP Addresses:[/cyan]")

        for line in addr_result.raw_response.split('\n'):
            if '+CGPADDR:' in line:
                console.print(f"  {line.strip()}")

    def check_data_connection(self):
        """Check if data connection is established"""
        console.print("\n[bold cyan]Data Connection Check[/bold cyan]\n")

        tests = [
            ("AT+CGATT?", "GPRS Attach Status"),
            ("AT+CGACT?", "PDP Context Activation"),
            ("AT+CGPADDR", "IP Address Assignment"),
        ]

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Test", style="cyan", width=30)
        table.add_column("Result", style="white", width=15)
        table.add_column("Details", style="white")

        for cmd, description in tests:
            result = self.modem.send_at_command(cmd)

            if result.success:
                status = "[green]✓ Pass[/green]"
                details = result.raw_response.strip().replace('\r\n', ' ')
            else:
                status = "[red]✗ Fail[/red]"
                details = result.error or "No response"

            table.add_row(description, status, details)

        console.print(table)
        console.print()

        # Additional advice
        console.print("[yellow]Troubleshooting Tips:[/yellow]")
        console.print("  • If GPRS attach fails, check SIM card and network registration")
        console.print("  • If PDP context is inactive, try: AT+CGACT=1,1")
        console.print("  • If no IP address, verify APN configuration")
        console.print("  • Check signal strength with signal quality test")


class ModemDiagnosticTool:
    """Main application class"""

    def __init__(self):
        self.modem: Optional[ModemConnection] = None
        self.connected = False
        self.modemmanager_was_stopped = False  # Track if we stopped ModemManager

    def show_banner(self):
        """Display application banner"""
        banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║        Cellular Modem Diagnostic & Configuration Tool        ║
║                    for Raspberry Pi                          ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
        """
        console.print(Panel(banner, style="bold cyan", box=box.DOUBLE))

    def _restart_modemmanager_if_needed(self):
        """Restart ModemManager if we stopped it"""
        if self.modemmanager_was_stopped and IS_LINUX:
            console.print("\n[cyan]Restarting ModemManager...[/cyan]")
            if ModemManagerHelper.restart():
                console.print("[green]✓ ModemManager restarted[/green]")
            else:
                console.print("[yellow]⚠ Could not restart ModemManager[/yellow]")
                console.print("[dim]  You may need to restart it manually: sudo systemctl start ModemManager[/dim]")
            self.modemmanager_was_stopped = False

    def detect_serial_ports(self) -> List[Dict]:
        """Detect all available serial ports"""
        ports = []

        if IS_WINDOWS:
            # Windows COM port detection
            import serial.tools.list_ports

            for port in serial.tools.list_ports.comports():
                port_info = {
                    'path': port.device,
                    'name': port.device,
                    'type': 'COM Port',
                    'description': port.description or 'No description',
                    'vendor': port.manufacturer or '',
                    'priority': 0  # Will be set based on port number
                }

                # Extract COM port number for prioritization
                try:
                    com_num = int(re.search(r'COM(\d+)', port.device).group(1))
                    port_info['priority'] = -com_num  # Lower COM numbers get higher priority
                except:
                    port_info['priority'] = 999

                ports.append(port_info)

        else:
            # Linux/Unix serial port detection
            # Common serial port patterns for cellular modems
            patterns = [
                '/dev/ttyUSB*',
                '/dev/ttyACM*',
                '/dev/ttyAMA*',
                '/dev/ttyS*'
            ]

            for pattern in patterns:
                for port_path in glob.glob(pattern):
                    port_info = {
                        'path': port_path,
                        'name': port_path.split('/')[-1],
                        'type': 'Unknown',
                        'description': '',
                        'priority': 0
                    }

                    # Try to get additional info from udevadm
                    try:
                        result = subprocess.run(
                            ['udevadm', 'info', '--name=' + port_path, '--query=property'],
                            capture_output=True,
                            text=True,
                            timeout=1  # Reduced timeout
                        )

                        if result.returncode == 0:
                            for line in result.stdout.split('\n'):
                                if 'ID_MODEL=' in line:
                                    port_info['description'] = line.split('=')[1].strip()
                                elif 'ID_USB_INTERFACE_NUM=' in line:
                                    interface_num = line.split('=')[1].strip()
                                    port_info['interface'] = interface_num
                                elif 'ID_VENDOR=' in line:
                                    port_info['vendor'] = line.split('=')[1].strip()

                        # Determine port type and priority
                        if 'ttyUSB' in port_path:
                            port_info['type'] = 'USB Serial'
                            # Extract USB number and prioritize HIGHEST first (USB3 > USB2 > USB1 > USB0)
                            # Modem AT ports are typically on the highest USB interface
                            match = re.search(r'ttyUSB(\d+)', port_path)
                            if match:
                                usb_num = int(match.group(1))
                                # Negative priority, higher USB number = lower (better) priority value
                                port_info['priority'] = -usb_num  # USB3=-3, USB2=-2, USB1=-1, USB0=0
                            else:
                                port_info['priority'] = 0
                        elif 'ttyACM' in port_path:
                            port_info['type'] = 'USB CDC-ACM'
                            port_info['priority'] = 10
                        elif 'ttyAMA' in port_path:
                            port_info['type'] = 'UART (Hardware)'
                            port_info['priority'] = 20
                        elif 'ttyS' in port_path:
                            port_info['type'] = 'Serial Port'
                            port_info['priority'] = 30

                    except Exception:
                        pass

                    ports.append(port_info)

        # Sort by priority (lower = higher priority)
        return sorted(ports, key=lambda x: (x.get('priority', 999), x['path']))

    def test_port_for_modem(self, port: str, baudrate: int = 115200, quick_test: bool = False) -> Tuple[bool, Optional[str]]:
        """Test if a port responds to AT commands with timeout protection

        Args:
            port: Serial port path
            baudrate: Baud rate to test
            quick_test: If True, use faster timeout for initial screening
        """
        if DEBUG_MODE:
            console.print(f"[dim]DEBUG: Starting test for {port} @ {baudrate}[/dim]")

        # Check blacklist first
        if port in SKIP_PORTS:
            if DEBUG_MODE:
                console.print(f"[dim]DEBUG: {port} in skip list[/dim]")
            return False, "Port in skip list (MODEMO_SKIP_PORTS)"

        # Pre-flight checks on Linux to avoid kernel-level blocking
        if IS_LINUX:
            if DEBUG_MODE:
                console.print(f"[dim]DEBUG: Running pre-flight checks for {port}[/dim]")

            # Check if port exists and is accessible
            if not os.path.exists(port):
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} does not exist[/dim]")
                return False, "Port does not exist"

            # Check if we have read/write permissions
            if not os.access(port, os.R_OK | os.W_OK):
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} permission denied[/dim]")
                return False, "Permission denied"

            # Check if port is already locked/in use by checking for lock file
            # This is a common pattern on Linux
            lock_file = f"/var/lock/LCK..{os.path.basename(port)}"
            if os.path.exists(lock_file):
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} has lock file[/dim]")
                return False, "Port locked by another process"

            # CRITICAL: Try to open port in non-blocking mode first to detect kernel-level blocks
            # This is the most aggressive check to prevent hangs
            if DEBUG_MODE:
                console.print(f"[dim]DEBUG: Attempting non-blocking open of {port}[/dim]")
            try:
                import fcntl
                # Try to open with O_NONBLOCK to avoid blocking on open()
                fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)

                # If we got here, port can be opened. Close it immediately
                os.close(fd)
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: Non-blocking open of {port} SUCCESS[/dim]")
            except OSError as e:
                # Port is blocked at kernel level or has issues
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} OSError: {e.errno} {e.strerror}[/dim]")
                return False, f"Port unavailable ({e.errno}: {e.strerror})"
            except Exception as e:
                if DEBUG_MODE:
                    console.print(f"[dim]DEBUG: {port} Exception: {str(e)}[/dim]")
                return False, f"Port test failed: {str(e)}"

        # Use a threading approach with timeout to prevent hangs
        result_container = {'success': False, 'error': 'Timeout'}

        def test_thread():
            try:
                timeout_val = 0.5 if quick_test else 2
                test_modem = ModemConnection(port=port, baudrate=baudrate, timeout=timeout_val)

                # Pass quick_test flag to connect method
                if test_modem.connect(quick_test=quick_test):
                    # Try AT command
                    result = test_modem.send_at_command("AT", wait_time=0.3 if quick_test else 1.0)
                    test_modem.disconnect()

                    if result.success:
                        result_container['success'] = True
                        result_container['error'] = None
                    else:
                        result_container['success'] = False
                        result_container['error'] = "No AT response"
                else:
                    result_container['success'] = False
                    result_container['error'] = "Cannot open port"
            except Exception as e:
                result_container['success'] = False
                result_container['error'] = str(e)

        # Create and start thread
        thread = threading.Thread(target=test_thread, daemon=True)
        thread.start()

        # Wait for thread with timeout (2 seconds for quick test, 5 seconds for normal)
        thread_timeout = 2.5 if quick_test else 6.0
        thread.join(timeout=thread_timeout)

        # If thread is still alive, it timed out
        if thread.is_alive():
            return False, f"Timeout ({thread_timeout}s) - port may be unresponsive"

        return result_container['success'], result_container['error']

    def auto_detect_modem(self) -> Optional[Tuple[str, int]]:
        """Automatically detect cellular modem port with optimized two-phase testing"""
        console.print("\n[bold cyan]🔍 Auto-detecting cellular modem...[/bold cyan]\n")

        # Check for ModemManager interference on Linux
        modemmanager_was_stopped = False
        if IS_LINUX and ModemManagerHelper.is_running():
            console.print("[yellow]⚠ ModemManager is running and may interfere with port detection[/yellow]")

            managed_ports = ModemManagerHelper.get_managed_ports()
            if managed_ports:
                console.print(f"[yellow]  ModemManager is managing: {', '.join(managed_ports)}[/yellow]\n")

            console.print("[dim]ModemManager can block access to modem ports and cause detection to hang.[/dim]")
            console.print("[dim]Options:[/dim]")
            console.print("[dim]  1. Temporarily stop it (will auto-restart when done)[/dim]")
            console.print("[dim]  2. Continue anyway (may be slower or hang on some ports)[/dim]")
            console.print()

            if Confirm.ask("Temporarily stop ModemManager for detection?", default=True):
                console.print("[cyan]Stopping ModemManager...[/cyan]")
                if ModemManagerHelper.stop_temporarily():
                    console.print("[green]✓ ModemManager stopped temporarily[/green]")
                    console.print("[dim]  (Will auto-restart when you exit this program)[/dim]\n")
                    modemmanager_was_stopped = True
                    time.sleep(1)  # Give ports time to release
                else:
                    console.print("[yellow]⚠ Could not stop ModemManager (may need sudo)[/yellow]")
                    console.print("[dim]  Try running: sudo python3 modemo.py[/dim]\n")

        ports = self.detect_serial_ports()

        if not ports:
            console.print("[red]✗ No serial ports found on this system[/red]")
            if modemmanager_was_stopped:
                self.modemmanager_was_stopped = modemmanager_was_stopped
                self._restart_modemmanager_if_needed()
            return None

        # Display found ports
        console.print(f"[cyan]Found {len(ports)} serial port(s):[/cyan]\n")

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("#", style="cyan", width=3)
        table.add_column("Port", style="white", width=15)
        table.add_column("Type", style="white", width=20)
        table.add_column("Description", style="white")

        for idx, port in enumerate(ports, 1):
            desc = port.get('description', '')
            if port.get('vendor'):
                desc = f"{port.get('vendor', '')} {desc}".strip()
            if not desc:
                desc = "No description available"

            table.add_row(
                str(idx),
                port['path'],
                port['type'],
                desc
            )

        console.print(table)
        console.print()

        # Two-phase baud rate testing
        # Phase 1: Try most common baud rate (115200) on all ports first
        # Phase 2: Only try other baud rates if Phase 1 finds nothing
        primary_baudrate = 115200
        fallback_baudrates = [9600, 460800, 57600, 19200]

        working_ports = []

        # Phase 1: Quick scan with most common baud rate
        console.print(f"[cyan]Phase 1: Quick scan @ {primary_baudrate} baud...[/cyan]\n")

        with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
        ) as progress:
            task = progress.add_task("[cyan]Scanning ports...", total=len(ports))

            for port in ports:
                port_path = port['path']
                progress.update(task, description=f"[cyan]Testing {port_path}...")

                is_working, error = self.test_port_for_modem(port_path, primary_baudrate, quick_test=True)

                if is_working:
                    working_ports.append({
                        'port': port_path,
                        'baudrate': primary_baudrate,
                        'info': port
                    })
                    progress.update(task, description=f"[green]✓ {port_path} @ {primary_baudrate} baud - WORKING!")
                    time.sleep(0.3)  # Brief pause to show success message
                elif error and "Timeout" in error:
                    progress.update(task, description=f"[yellow]⏱ {port_path} - Timeout (skipping)")
                    time.sleep(0.2)
                elif error and "Permission" in error:
                    progress.update(task, description=f"[red]🔒 {port_path} - {error}")
                    time.sleep(0.2)

                progress.advance(task)

        console.print()

        # Phase 2: If nothing found, try other baud rates
        if not working_ports:
            console.print("[yellow]⚠ No modems found with standard baud rate[/yellow]")
            console.print(f"[cyan]Phase 2: Testing alternate baud rates...[/cyan]\n")

            with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console
            ) as progress:

                for port in ports:
                    port_path = port['path']
                    task = progress.add_task(f"[cyan]Testing {port_path}...", total=len(fallback_baudrates))

                    for baudrate in fallback_baudrates:
                        progress.update(task, description=f"[cyan]Testing {port_path} @ {baudrate} baud...")

                        is_working, error = self.test_port_for_modem(port_path, baudrate)

                        if is_working:
                            working_ports.append({
                                'port': port_path,
                                'baudrate': baudrate,
                                'info': port
                            })
                            progress.update(task, description=f"[green]✓ {port_path} @ {baudrate} baud - WORKING!")
                            time.sleep(0.3)
                            break

                        progress.advance(task)

                    if not any(p['port'] == port_path for p in working_ports):
                        progress.update(task, description=f"[dim]✗ {port_path} - No response")

            console.print()

        if not working_ports:
            console.print("[yellow]⚠ No working modem ports detected[/yellow]")
            console.print("[dim]This could mean:[/dim]")
            console.print("[dim]  • Modem is not connected or powered[/dim]")
            console.print("[dim]  • Modem uses non-standard baud rate[/dim]")
            console.print("[dim]  • Permission issues (try running with sudo)[/dim]")
            console.print("[dim]  • Modem is in a non-AT command mode[/dim]")
            # Track ModemManager status before returning
            if modemmanager_was_stopped:
                self.modemmanager_was_stopped = True
            return None

        # Display working ports
        console.print(f"[bold green]✓ Found {len(working_ports)} working modem port(s)![/bold green]\n")

        # Track ModemManager status for later cleanup
        if modemmanager_was_stopped:
            self.modemmanager_was_stopped = True

        if len(working_ports) == 1:
            # Only one port works, use it automatically
            selected = working_ports[0]
            console.print(f"[green]Automatically selecting:[/green]")
            console.print(f"  Port: {selected['port']}")
            console.print(f"  Baud Rate: {selected['baudrate']}")
            console.print()
            return (selected['port'], selected['baudrate'])

        # Multiple working ports - let user choose
        table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta", title="Working Modem Ports")
        table.add_column("#", style="cyan", width=3)
        table.add_column("Port", style="white", width=15)
        table.add_column("Baud Rate", style="white", width=12)
        table.add_column("Description", style="white")

        for idx, port_info in enumerate(working_ports, 1):
            desc = port_info['info'].get('description', 'No description')
            if port_info['info'].get('vendor'):
                desc = f"{port_info['info'].get('vendor', '')} {desc}".strip()

            table.add_row(
                str(idx),
                port_info['port'],
                str(port_info['baudrate']),
                desc
            )

        console.print(table)
        console.print()

        # Recommend port based on common patterns
        recommended = None
        for idx, port_info in enumerate(working_ports, 1):
            port_path = port_info['port']
            # USB2 is often the AT command port for multi-port modems
            if 'ttyUSB2' in port_path:
                recommended = idx
                break
            # If no USB2, prefer USB1
            elif 'ttyUSB1' in port_path and recommended is None:
                recommended = idx

        if recommended:
            console.print(f"[yellow]💡 Recommendation: Port #{recommended} (commonly used for AT commands)[/yellow]\n")

        # Let user choose
        choices = [str(i) for i in range(1, len(working_ports) + 1)]
        default_choice = str(recommended) if recommended else "1"

        choice = Prompt.ask(
            "Select port to use",
            choices=choices,
            default=default_choice
        )

        selected = working_ports[int(choice) - 1]
        console.print()
        return (selected['port'], selected['baudrate'])

    def connect_modem(self):
        """Connect to modem with auto-detection or manual configuration"""
        console.print("\n[bold cyan]Modem Connection Setup[/bold cyan]\n")

        # Offer auto-detection
        console.print("Connection options:")
        console.print("  [bold cyan]1[/bold cyan]. Auto-detect modem (recommended)")
        console.print("  [bold cyan]2[/bold cyan]. Manual configuration")
        console.print()

        choice = Prompt.ask("Select option", choices=["1", "2"], default="1")

        if choice == "1":
            # Auto-detection
            result = self.auto_detect_modem()

            if result:
                port, baudrate = result
            else:
                console.print("\n[yellow]Would you like to try manual configuration instead?[/yellow]")
                if Confirm.ask("Configure manually?", default=True):
                    default_port = "COM3" if IS_WINDOWS else "/dev/ttyUSB2"
                    port = Prompt.ask("Enter serial port", default=default_port)
                    baudrate = int(Prompt.ask("Enter baud rate", default="115200"))
                else:
                    return False
        else:
            # Manual configuration
            console.print()

            # Show available ports as reference
            ports = self.detect_serial_ports()
            if ports:
                console.print("[cyan]Available serial ports:[/cyan]")
                for p in ports:
                    console.print(f"  • {p['path']} ({p['type']})")
                console.print()

            # Platform-aware default port
            default_port = "COM3" if IS_WINDOWS else "/dev/ttyUSB2"
            port = Prompt.ask("Enter serial port", default=default_port)
            baudrate = int(Prompt.ask("Enter baud rate", default="115200"))

        # Connect with selected settings
        self.modem = ModemConnection(port=port, baudrate=baudrate)

        console.print(f"\n[cyan]Connecting to {port} at {baudrate} baud...[/cyan]")

        if self.modem.connect():
            # Test connection
            result = self.modem.send_at_command("AT")
            if result.success:
                console.print("[green]✓ Connection established successfully![/green]")

                # Get quick device info
                info = self.modem.send_at_command("ATI")
                if info.success and 'info' in info.parsed_data:
                    console.print(f"[dim]Device: {info.parsed_data['info'].split(chr(10))[0]}[/dim]")

                self.connected = True
                return True
            else:
                console.print("[red]✗ Connection established but modem not responding[/red]")
                self.connected = False
                return False
        else:
            console.print("[red]✗ Failed to establish connection[/red]")
            self.connected = False
            return False

    def main_menu(self):
        """Display and handle main menu"""
        while True:
            console.print("\n")
            console.rule("[bold cyan]Main Menu", style="cyan")
            console.print()

            menu_items = [
                ("1", "Run Full Diagnostic Test", "Complete system diagnostic"),
                ("2", "Quick Status Check", "View current status"),
                ("3", "Network Tools", "Scan, configure, troubleshoot network"),
                ("4", "Data Connection Tools", "Check and troubleshoot data usage"),
                ("5", "Vendor-Specific Tools", "Advanced modem-specific features"),
                ("6", "Manual AT Command", "Send custom AT commands"),
                ("7", "Reconnect Modem", "Change connection settings"),
                ("8", "Export Diagnostic Report", "Save results to file"),
                ("0", "Exit", "Quit application"),
            ]

            for num, title, desc in menu_items:
                console.print(f"  [bold cyan]{num}[/bold cyan]. [white]{title}[/white] - [dim]{desc}[/dim]")

            console.print()
            choice = Prompt.ask("Select option", choices=[item[0] for item in menu_items], default="1")

            if choice == "0":
                break
            elif choice == "1":
                self.run_full_diagnostic()
            elif choice == "2":
                self.quick_status()
            elif choice == "3":
                self.network_tools_menu()
            elif choice == "4":
                self.data_tools_menu()
            elif choice == "5":
                self.vendor_tools_menu()
            elif choice == "6":
                self.manual_at_command()
            elif choice == "7":
                if self.modem:
                    self.modem.disconnect()
                self.connect_modem()
            elif choice == "8":
                self.export_report()

    def run_full_diagnostic(self):
        """Run complete diagnostic test suite"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            return

        diag = DiagnosticTests(self.modem)
        diag.run_full_diagnostic()
        diag.display_results()

        Prompt.ask("\nPress Enter to continue")

    def quick_status(self):
        """Show quick status overview"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            return

        console.print("\n")
        console.rule("[bold cyan]Quick Status Check", style="cyan")

        # Signal quality
        csq = self.modem.send_at_command("AT+CSQ")
        if 'signal_quality' in csq.parsed_data:
            quality = csq.parsed_data['signal_quality']
            color = "green" if quality in ['Excellent', 'Good'] else "yellow" if quality == 'Fair' else "red"
            console.print(
                f"\n[bold]Signal Quality:[/bold] [{color}]{quality}[/{color}] ({csq.parsed_data.get('rssi_dbm', 'Unknown')})")

        # Registration
        creg = self.modem.send_at_command("AT+CREG?")
        if 'creg_status_text' in creg.parsed_data:
            status = creg.parsed_data['creg_status']
            color = "green" if status in [1, 5] else "red"
            console.print(f"[bold]Network Status:[/bold] [{color}]{creg.parsed_data['creg_status_text']}[/{color}]")

        # Operator
        cops = self.modem.send_at_command("AT+COPS?")
        if 'operator' in cops.parsed_data:
            console.print(f"[bold]Operator:[/bold] {cops.parsed_data['operator']}")

        # SIM status
        cpin = self.modem.send_at_command("AT+CPIN?")
        if 'sim_status' in cpin.parsed_data:
            color = "green" if cpin.parsed_data.get('sim_ready', False) else "red"
            console.print(f"[bold]SIM Status:[/bold] [{color}]{cpin.parsed_data['sim_status']}[/{color}]")

        Prompt.ask("\nPress Enter to continue")

    def network_tools_menu(self):
        """Network tools submenu"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        tools = NetworkTools(self.modem)

        while True:
            console.print("\n")
            console.rule("[bold cyan]Network Tools", style="cyan")
            console.print()

            console.print("  [bold cyan]1[/bold cyan]. Scan Available Networks")
            console.print("  [bold cyan]2[/bold cyan]. View Forbidden Network List (FPLMN)")
            console.print("  [bold cyan]3[/bold cyan]. Clear Forbidden Network List (FPLMN)")
            console.print("  [bold cyan]4[/bold cyan]. Configure APN")
            console.print("  [bold cyan]5[/bold cyan]. Force Network Registration")
            console.print("  [bold cyan]0[/bold cyan]. Back to Main Menu")
            console.print()

            choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4", "5"], default="1")

            if choice == "0":
                break
            elif choice == "1":
                tools.scan_networks()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "2":
                tools.view_fplmn()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "3":
                tools.clear_fplmn()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "4":
                tools.configure_apn()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "5":
                tools.force_network_registration()
                Prompt.ask("\nPress Enter to continue")

    def data_tools_menu(self):
        """Data connection tools submenu"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        tools = DataUsageTools(self.modem)

        while True:
            console.print("\n")
            console.rule("[bold cyan]Data Connection Tools", style="cyan")
            console.print()

            console.print("  [bold cyan]1[/bold cyan]. Check PDP Context Status")
            console.print("  [bold cyan]2[/bold cyan]. Check Data Connection")
            console.print("  [bold cyan]3[/bold cyan]. Activate PDP Context")
            console.print("  [bold cyan]4[/bold cyan]. Deactivate PDP Context")
            console.print("  [bold cyan]0[/bold cyan]. Back to Main Menu")
            console.print()

            choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4"], default="1")

            if choice == "0":
                break
            elif choice == "1":
                tools.check_pdp_status()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "2":
                tools.check_data_connection()
                Prompt.ask("\nPress Enter to continue")
            elif choice == "3":
                cid = Prompt.ask("Enter CID to activate", default="1")
                result = self.modem.send_at_command(f"AT+CGACT=1,{cid}")
                if result.success:
                    console.print("[green]✓ PDP context activated[/green]")
                else:
                    console.print(f"[red]✗ Activation failed: {result.error}[/red]")
                Prompt.ask("\nPress Enter to continue")
            elif choice == "4":
                cid = Prompt.ask("Enter CID to deactivate", default="1")
                result = self.modem.send_at_command(f"AT+CGACT=0,{cid}")
                if result.success:
                    console.print("[green]✓ PDP context deactivated[/green]")
                else:
                    console.print(f"[red]✗ Deactivation failed: {result.error}[/red]")
                Prompt.ask("\nPress Enter to continue")

    def manual_at_command(self):
        """Send manual AT commands"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        console.print("\n[bold cyan]Manual AT Command Interface[/bold cyan]")
        console.print("[dim]Enter 'exit' to return to main menu[/dim]\n")

        while True:
            cmd = Prompt.ask("AT Command")

            if cmd.lower() == 'exit':
                break

            if not cmd.upper().startswith('AT'):
                cmd = 'AT' + cmd

            result = self.modem.send_at_command(cmd)

            console.print(f"\n[cyan]Raw Response:[/cyan]")
            console.print(Panel(result.raw_response, box=box.ROUNDED))

            if result.parsed_data and len(result.parsed_data) > 1:
                console.print(f"\n[cyan]Parsed Data:[/cyan]")
                console.print(json.dumps(result.parsed_data, indent=2))

            console.print()

    def vendor_tools_menu(self):
        """Vendor-specific advanced tools"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            time.sleep(2)
            return

        # Detect vendor
        diag = DiagnosticTests(self.modem)
        diag.detect_modem_vendor()

        if not diag.modem_vendor:
            console.print("[yellow]Could not detect modem vendor. Vendor-specific features unavailable.[/yellow]")
            Prompt.ask("\nPress Enter to continue")
            return

        if diag.modem_vendor == 'Quectel':
            self.quectel_tools_menu(diag.modem_model)
        elif diag.modem_vendor == 'Sierra Wireless':
            self.sierra_tools_menu()
        elif diag.modem_vendor == 'u-blox':
            self.ublox_tools_menu()
        else:
            console.print(f"[yellow]No specialized tools available for {diag.modem_vendor}[/yellow]")
            console.print("[dim]Using generic AT commands via Manual AT Command option[/dim]")
            Prompt.ask("\nPress Enter to continue")

    def quectel_tools_menu(self, model: str = None):
        """Quectel-specific tools"""
        while True:
            console.print("\n")
            console.rule("[bold cyan]Quectel Advanced Tools", style="cyan")
            if model:
                console.print(f"[dim]Model: {model}[/dim]")
            console.print()

            console.print("  [bold cyan]1[/bold cyan]. View Advanced Cell Information (AT+QENG)")
            console.print("  [bold cyan]2[/bold cyan]. View Network Info (AT+QNWINFO)")
            console.print("  [bold cyan]3[/bold cyan]. Check Temperature (AT+QTEMP)")
            console.print("  [bold cyan]4[/bold cyan]. View Neighboring Cells (AT+QENG=\"neighbourcell\")")
            console.print("  [bold cyan]5[/bold cyan]. Query SIM Slot (AT+QUIMSLOT?)")
            console.print("  [bold cyan]6[/bold cyan]. GPS Status (AT+QGPS?)")
            console.print("  [bold cyan]7[/bold cyan]. Check eSIM Support (AT+QESIM)")
            console.print("  [bold cyan]0[/bold cyan]. Back to Main Menu")
            console.print()

            choice = Prompt.ask("Select option", choices=["0", "1", "2", "3", "4", "5", "6", "7"], default="1")

            if choice == "0":
                break
            elif choice == "1":
                result = self.modem.send_at_command("AT+QENG=\"servingcell\"")
                self._display_at_result("Advanced Cell Information", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "2":
                result = self.modem.send_at_command("AT+QNWINFO")
                self._display_at_result("Network Information", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "3":
                result = self.modem.send_at_command("AT+QTEMP")
                self._display_at_result("Temperature Reading", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "4":
                console.print("\n[cyan]Scanning neighbor cells (may take 5-10 seconds)...[/cyan]")
                result = self.modem.send_at_command("AT+QENG=\"neighbourcell\"", wait_time=10)
                self._display_at_result("Neighboring Cells", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "5":
                result = self.modem.send_at_command("AT+QUIMSLOT?")
                self._display_at_result("SIM Slot Configuration", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "6":
                result = self.modem.send_at_command("AT+QGPS?")
                self._display_at_result("GPS Status", result)
                Prompt.ask("\nPress Enter to continue")
            elif choice == "7":
                result = self.modem.send_at_command("AT+QESIM=\"eid\"")
                self._display_at_result("eSIM Support (EID)", result)
                Prompt.ask("\nPress Enter to continue")

    def sierra_tools_menu(self):
        """Sierra Wireless-specific tools"""
        console.print("\n[yellow]Sierra Wireless tools - Basic implementation[/yellow]")
        result = self.modem.send_at_command("AT!GSTATUS?")
        self._display_at_result("Sierra Status", result)
        Prompt.ask("\nPress Enter to continue")

    def ublox_tools_menu(self):
        """u-blox-specific tools"""
        console.print("\n[yellow]u-blox tools - Basic implementation[/yellow]")
        result = self.modem.send_at_command("AT+UCGED?")
        self._display_at_result("u-blox Cell Info", result)
        Prompt.ask("\nPress Enter to continue")

    def _display_at_result(self, title: str, result: ATResponse):
        """Display AT command result in formatted panel"""
        console.print(f"\n[bold cyan]{title}[/bold cyan]")

        if not result.success:
            console.print(f"[red]Command failed: {result.error}[/red]")
            return

        # Show parsed data if available
        if result.parsed_data and len(result.parsed_data) > 1:
            table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
            table.add_column("Parameter", style="cyan")
            table.add_column("Value", style="white")

            for key, value in result.parsed_data.items():
                if key != 'raw' and value:
                    # Format key nicely
                    formatted_key = key.replace('_', ' ').title()
                    table.add_row(formatted_key, str(value))

            console.print(table)

        # Always show raw response
        console.print(f"\n[cyan]Raw Response:[/cyan]")
        console.print(Panel(result.raw_response, box=box.ROUNDED))

    def export_report(self):
        """Export diagnostic report to file"""
        if not self.connected:
            console.print("[red]Not connected to modem. Please connect first.[/red]")
            return

        console.print("\n[cyan]Generating diagnostic report...[/cyan]")

        diag = DiagnosticTests(self.modem)
        results = diag.run_full_diagnostic()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Cross-platform path handling
        if IS_WINDOWS:
            # Use current directory or Documents folder on Windows
            output_dir = os.path.join(os.path.expanduser("~"), "Documents", "modemo_reports")
        else:
            # Try to use /mnt/user-data/outputs on Linux, fallback to home directory
            output_dir = "/mnt/user-data/outputs" if os.path.exists("/mnt/user-data/outputs") else os.path.join(
                os.path.expanduser("~"), "modemo_reports")

        # Create directory if it doesn't exist
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            console.print(f"[yellow]⚠ Could not create output directory: {e}[/yellow]")
            output_dir = os.getcwd()  # Fallback to current directory

        filename = os.path.join(output_dir, f"modem_diagnostic_{timestamp}.txt")

        try:
            with open(filename, 'w') as f:
                f.write("=" * 70 + "\n")
                f.write("CELLULAR MODEM DIAGNOSTIC REPORT\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 70 + "\n\n")

                for result in results:
                    f.write(f"\nCommand: {result.command}\n")
                    f.write(f"Timestamp: {result.timestamp}\n")
                    f.write(f"Success: {result.success}\n")
                    if result.error:
                        f.write(f"Error: {result.error}\n")
                    f.write(f"\nRaw Response:\n{result.raw_response}\n")
                    f.write(f"\nParsed Data:\n{json.dumps(result.parsed_data, indent=2)}\n")
                    f.write("-" * 70 + "\n")

            console.print(f"[green]✓ Report saved to: {filename}[/green]")
        except Exception as e:
            console.print(f"[red]✗ Failed to save report: {e}[/red]")

        Prompt.ask("\nPress Enter to continue")

    def run(self):
        """Main application entry point"""
        self.show_banner()

        if not self.connect_modem():
            console.print(
                "\n[yellow]Unable to establish connection. Please check your settings and try again.[/yellow]")
            if not Confirm.ask("\nRetry connection?"):
                return
            if not self.connect_modem():
                return

        try:
            self.main_menu()
        finally:
            if self.modem:
                self.modem.disconnect()
            # Restart ModemManager if we stopped it
            self._restart_modemmanager_if_needed()
            console.print("\n[cyan]Thank you for using Modem Diagnostic Tool![/cyan]\n")


if __name__ == "__main__":
    app = ModemDiagnosticTool()
    app.run()