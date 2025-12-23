# Cellular Modem Diagnostic & Configuration Tool

A comprehensive terminal-based application for configuring, diagnosing, and troubleshooting cellular modems on Raspberry Pi. Built specifically for working with the AT command ecosystem while providing human-readable translations of technical data.

## Features

### 🔍 Diagnostic Capabilities
- **Full System Diagnostic**: Comprehensive health check of modem, SIM, and network
- **Quick Status Check**: Fast overview of current modem state
- **Signal Quality Analysis**: RSSI and BER with human-readable quality assessments
- **Network Registration Status**: CS, PS, and EPS registration with detailed explanations
- **Device Information**: Manufacturer, model, firmware, IMEI
- **SIM Card Analysis**: Status, ICCID, IMSI verification

### 🌐 Network Tools
- **Network Scanner**: Discover all available cellular networks in range
- **FPLMN Management**: Clear forbidden network list to resolve registration issues
- **APN Configuration**: Easy setup and modification of APN settings
- **Force Registration**: Manual network selection and registration

### 📊 Data Connection Tools
- **PDP Context Management**: View, activate, and deactivate data contexts
- **Connection Verification**: Comprehensive data connection health checks
- **IP Address Assignment**: Monitor IP address allocation
- **Troubleshooting Guides**: Built-in tips for common issues

### 🛠️ Advanced Features
- **Auto-detection**: Automatically find and test all serial ports to locate your modem
- **Smart Port Recommendation**: Suggests the most likely correct port based on common patterns
- **Multi-baud Rate Testing**: Tests multiple baud rates automatically
- **Manual AT Commands**: Send any AT command with parsed responses
- **Export Reports**: Generate detailed diagnostic reports
- **Human-Readable Output**: Technical AT responses translated to plain language
- **Color-Coded Status**: Visual indicators for quick problem identification

## Installation

### Prerequisites
- Raspberry Pi (any model with USB port)
- Cellular modem connected via USB or UART
- Python 3.7 or higher
- Root/sudo access for serial port communication

### Setup Steps

1. **Clone or download the application files**
```bash
cd ~
# If you have the files, navigate to their location
```

2. **Install Python dependencies**
```bash
pip3 install -r requirements.txt
```

Or install manually:
```bash
pip3 install rich pyserial
```

3. **Make the script executable**
```bash
chmod +x modem_diagnostics.py
```

4. **Identify your modem's serial port**
```bash
ls /dev/tty*
```

Common modem ports:
- `/dev/ttyUSB0`, `/dev/ttyUSB1`, `/dev/ttyUSB2` (USB modems)
- `/dev/ttyAMA0`, `/dev/ttyS0` (UART modems)
- `/dev/ttyACM0` (some USB modems)

5. **Add user to dialout group (if needed)**
```bash
sudo usermod -a -G dialout $USER
```
Then log out and back in for changes to take effect.

## Usage

### Starting the Application

```bash
python3 modem_diagnostics.py
```

Or with sudo if serial port access requires it:
```bash
sudo python3 modem_diagnostics.py
```

### Initial Connection

When the application starts, you'll see two connection options:

**Option 1: Auto-detect modem (recommended)**
- The tool automatically scans all serial ports
- Tests each port with common baud rates
- Identifies working modem connections
- Shows device information for each port
- Recommends the best port based on common patterns
- You simply select from working ports (or auto-selects if only one found)

**Option 2: Manual configuration**
- Shows list of available serial ports for reference
- You manually enter port path (e.g., `/dev/ttyUSB2`)
- You manually enter baud rate (e.g., `115200`)

The auto-detection process:
1. Scans for all serial ports (`/dev/ttyUSB*`, `/dev/ttyACM*`, `/dev/ttyAMA*`, `/dev/ttyS*`)
2. Displays a table of found ports with type and description
3. Tests each port with multiple baud rates (115200, 9600, 460800, 57600, 19200)
4. Shows real-time progress as it tests each port
5. Identifies which ports respond to AT commands
6. Recommends port based on common modem patterns (e.g., USB2 for multi-port modems)
7. Connects automatically if only one working port found
8. Lets you choose if multiple working ports found

**Example auto-detection output:**
```
🔍 Auto-detecting cellular modem...

Found 3 serial port(s):

┌───┬─────────────────┬──────────────────────┬────────────────────────┐
│ # │ Port            │ Type                 │ Description            │
├───┼─────────────────┼──────────────────────┼────────────────────────┤
│ 1 │ /dev/ttyUSB0    │ USB Serial           │ Quectel EG25           │
│ 2 │ /dev/ttyUSB1    │ USB Serial           │ Quectel EG25           │
│ 3 │ /dev/ttyUSB2    │ USB Serial           │ Quectel EG25           │
└───┴─────────────────┴──────────────────────┴────────────────────────┘

Testing ports for AT command response...

✓ /dev/ttyUSB2 @ 115200 baud - WORKING!

✓ Found 1 working modem port(s)!

Automatically selecting:
  Port: /dev/ttyUSB2
  Baud Rate: 115200

✓ Connection established successfully!
```

### Main Menu Options

```
1. Run Full Diagnostic Test
   - Complete system diagnostic with all tests
   - Device info, SIM status, network registration, signal quality
   - Results displayed in formatted tables

2. Quick Status Check
   - Fast overview of current status
   - Signal quality, network status, operator, SIM state

3. Network Tools
   - Scan available networks
   - Clear FPLMN (forbidden networks list)
   - Configure APN settings
   - Force network registration

4. Data Connection Tools
   - Check PDP context status
   - Verify data connection
   - Activate/deactivate PDP contexts

5. Manual AT Command
   - Send custom AT commands
   - View raw and parsed responses

6. Reconnect Modem
   - Change connection settings
   - Switch to different serial port

7. Export Diagnostic Report
   - Generate detailed report file
   - Save all diagnostic results

0. Exit
```

## Common Use Cases

### Troubleshooting Network Registration Issues

1. Run **Full Diagnostic Test** (Option 1) to see overall status
2. Check signal quality - should be "Fair" or better
3. Look at network registration status codes:
   - `1` = Registered (home) ✓
   - `5` = Registered (roaming) ✓
   - `2` = Searching - wait or try force registration
   - `3` = Denied - clear FPLMN or check SIM
4. If registration denied:
   - Go to **Network Tools** → **Clear FPLMN**
   - Then **Force Network Registration**

### Configuring APN for Data Connection

1. Go to **Network Tools** (Option 3)
2. Select **Configure APN** (Option 3)
3. Enter context ID (usually 1)
4. Enter PDP type (IP for most cases)
5. Enter APN name (e.g., "hologram" for Hologram SIM)
6. Verify configuration

### Checking Data Connection

1. Go to **Data Connection Tools** (Option 4)
2. Select **Check Data Connection** (Option 2)
3. Review:
   - GPRS attach status (should be attached)
   - PDP context activation (should be active)
   - IP address assignment (should have valid IP)

### Finding Zero-Byte Sessions

If experiencing zero-byte data sessions:

1. Check **PDP Context Status** to verify APN configuration
2. Verify **Data Connection** is fully established
3. Check signal quality - poor signal can cause failed sessions
4. Review network registration - ensure registered on correct technology

## Understanding Output

### Signal Quality Indicators

The application translates RSSI values to quality ratings:

| RSSI | dBm Range | Quality | Color |
|------|-----------|---------|-------|
| 0-1 | ≤ -111 dBm | Very Poor | Red |
| 2-9 | -109 to -95 dBm | Poor | Red |
| 10-14 | -93 to -85 dBm | Fair | Yellow |
| 15-19 | -83 to -75 dBm | Good | Green |
| 20-31 | -73 to -51 dBm | Excellent | Green |

### Network Registration Status

| Status | Meaning | Color |
|--------|---------|-------|
| 0 | Not registered, not searching | Red |
| 1 | Registered, home network | Green |
| 2 | Not registered, searching | Yellow |
| 3 | Registration denied | Red |
| 4 | Unknown | Red |
| 5 | Registered, roaming | Green |

### Access Technologies (AcT)

- **GSM**: 2G network
- **UTRAN**: 3G network
- **E-UTRAN**: 4G LTE network
- **EGPRS**: Enhanced 2G (EDGE)

## Troubleshooting

### Connection Issues

**Problem**: Cannot connect to serial port
```
Solution with auto-detection:
1. Run the application
2. Select "Auto-detect modem" (option 1)
3. Tool will automatically find working ports
4. If no ports found, check:
   - Modem is physically connected
   - Modem is powered on
   - Run with sudo: sudo python3 modem_diagnostics.py
   - Add user to dialout group: sudo usermod -a -G dialout $USER

Manual approach:
1. List ports: ls /dev/tty{USB,ACM,AMA}*
2. Try each port manually using option 2
3. Common ports: /dev/ttyUSB2, /dev/ttyUSB1, /dev/ttyUSB0
```

**Problem**: Auto-detection finds no working ports
```
Solution:
1. Verify modem is connected: lsusb | grep -i modem
2. Check dmesg for USB errors: dmesg | tail -20
3. Run with sudo for permission access
4. Try manual configuration with different baud rates
5. Some modems require mode switching first
```

**Problem**: Multiple ports detected, unsure which to use
```
Solution:
The tool automatically recommends the best port!
- For multi-port modems, USB2 is usually AT commands
- Tool tests all ports and shows which ones work
- Green checkmark indicates working port
- Just select the recommended port (highlighted)
```

**Problem**: Modem not responding to AT commands
```
Solution:
1. Verify modem is powered on
2. Check USB cable connection
3. Try different serial port (USB2 vs USB1 vs USB0)
4. Reset modem power
5. Check dmesg for USB enumeration errors
```

### Network Issues

**Problem**: Registration status shows "Searching" (2)
```
Solution:
1. Check signal quality - must be "Fair" or better
2. Wait 30-60 seconds for network scan
3. Try manual network registration
4. Check SIM card is properly inserted
5. Verify SIM is activated and has service
```

**Problem**: Registration denied (3)
```
Solution:
1. Clear FPLMN list (Network Tools → Clear FPLMN)
2. Check if network is supported by carrier
3. Verify SIM provisioning and account status
4. Try different network manually
```

**Problem**: No data connection
```
Solution:
1. Verify APN configuration is correct
2. Check PDP context is activated
3. Ensure network registration on PS domain
4. Verify data plan is active
5. Check signal quality is sufficient
```

### SIM Issues

**Problem**: SIM PIN or SIM PUK status
```
Solution:
1. Use Manual AT Command to unlock:
   AT+CPIN="1234"  (replace with your PIN)
2. Contact carrier if PUK required
3. Verify SIM card is not locked
```

## AT Command Reference

### Essential Commands

| Command | Purpose | Response |
|---------|---------|----------|
| `AT` | Test communication | OK |
| `ATI` | Device information | Model and version info |
| `AT+CPIN?` | Check SIM status | READY or PIN required |
| `AT+CSQ` | Signal quality | RSSI and BER values |
| `AT+CREG?` | Network registration (CS) | Registration status |
| `AT+COPS?` | Current operator | Operator name and mode |
| `AT+CGDCONT?` | PDP contexts | APN configurations |
| `AT+CGACT?` | PDP activation status | Active/inactive state |

### Advanced Commands

| Command | Purpose |
|---------|---------|
| `AT+COPS=?` | Scan available networks (slow) |
| `AT+COPS=0` | Automatic network selection |
| `AT+COPS=1,2,"310260"` | Manual network selection |
| `AT+CGDCONT=1,"IP","hologram"` | Set APN |
| `AT+CGACT=1,1` | Activate PDP context 1 |
| `AT+CGPADDR` | Get IP address |

## Export Reports

Diagnostic reports are saved to:
```
/mnt/user-data/outputs/modem_diagnostic_YYYYMMDD_HHMMSS.txt
```

Reports include:
- Complete command history
- Raw AT responses
- Parsed data structures
- Timestamp for each test
- Error messages if any

## Tips for Best Results

1. **Signal Quality First**: Always check signal quality before troubleshooting other issues. Most problems stem from poor signal.

2. **Wait for Registration**: Network registration can take 30-60 seconds. Be patient after changing settings.

3. **Clear FPLMN Regularly**: If moving between areas or testing different networks, clear the FPLMN list periodically.

4. **Save Diagnostic Reports**: Export reports before making configuration changes for comparison.

5. **Monitor Over Time**: Run quick status checks periodically to catch degrading signal or network issues early.

6. **Check Multiple Registration Types**: LTE devices should check CEREG, not just CREG/CGREG.

## Technical Notes

### Serial Port Settings
- **Baud Rate**: Usually 115200, some modems use 9600 or 460800
- **Data Bits**: 8
- **Parity**: None
- **Stop Bits**: 1
- **Flow Control**: None (default)

### AT Command Formatting
- Commands must end with `\r\n` (handled automatically)
- Responses include echo, data, and OK/ERROR
- Wait times vary by command (network scans take 30-60s)

### Multi-Port Modems
Many USB modems present multiple serial ports:
- Port 0: Usually AT commands (diagnostic)
- Port 1: Sometimes AT commands (modem)
- Port 2: Often AT commands (main)
- Port 3: Sometimes GPS (NMEA)

Try different ports if commands fail.

## Support and References

### Hologram Documentation
- [Introduction to AT Commands](https://hologram.io/docs/reference/at-commands/introduction)
- [AT Command Reference](https://hologram.io/docs/reference/at-commands/reference)
- [Clear FPLMN List](https://hologram.io/docs/reference/at-commands/clear-fplmn)
- [Device Data Troubleshooting](https://hologram.io/docs/guides/troubleshooting/device-data)
- [Network Connection Troubleshooting](https://hologram.io/docs/guides/troubleshooting/network-connection)

### Modem Manufacturer Documentation
Consult your specific modem's AT command manual for:
- Vendor-specific commands
- Extended feature sets
- Power management commands
- GPS/GNSS commands (if applicable)

## License

This tool is provided as-is for use with cellular modems on Raspberry Pi and Linux systems.

## Contributing

To improve this tool:
1. Test with your specific modem model
2. Document any modem-specific quirks
3. Share successful configurations
4. Report bugs with detailed diagnostic output

## Version History

**v1.0** - Initial release
- Full diagnostic suite
- Network tools
- Data connection tools
- Manual AT interface
- Report generation
- Human-readable output translation