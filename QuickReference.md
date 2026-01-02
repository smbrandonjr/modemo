# Quick Reference Guide - Cellular Modem Troubleshooting

## 🚀 Quick Start

```bash
# Install
./install.sh

# Run
python3 modemo.py

# Or with sudo for permissions
sudo python3 modemo.py

# Connection is now EASY!
# 1. Select "Auto-detect modem" (option 1)
# 2. Tool finds your modem automatically
# 3. Select from working ports (or auto-connects)
# 4. Done! 🎉
```

---

## 🔍 Common Issues & Solutions

### Issue: Cannot Connect to Serial Port

**Symptoms**: "Connection Error" or "Permission denied"

**NEW: Use Auto-Detection! 🎯**
```bash
1. Run: python3 modem_diagnostics.py
2. Select: Auto-detect modem (1)
3. Watch: Tool scans and tests all ports
4. Result: Working ports automatically identified!
```

**If auto-detection finds nothing:**
```bash
# Check modem is connected
lsusb | grep -i modem

# Check USB devices
dmesg | tail -20

# Run with sudo for permissions
sudo python3 modem_diagnostics.py

# Add user to dialout group (then logout/login)
sudo usermod -a -G dialout $USER
```

**Manual method (if needed):**
```bash
# List available ports
ls /dev/tty{USB,ACM,AMA}*

# In app, select "Manual configuration" (2)
# Try ports in order:
# /dev/ttyUSB2 (most common for AT commands)
# /dev/ttyUSB1
# /dev/ttyUSB0
```

---

### Issue: Poor Signal Quality

**Symptoms**: Signal shows "Poor" or "Very Poor", RSSI < 10

**Solutions**:
1. **Relocate antenna** - Move to window or outside
2. **Check antenna connection** - Ensure firmly attached
3. **Try different orientation** - Rotate antenna
4. **Check surroundings** - Move away from metal, electronics
5. **Wait and retry** - Signal can fluctuate

**Target**: RSSI ≥ 15 (Good or Excellent)

---

### Issue: Network Registration Failed

**Symptoms**: Status shows "Not registered" or "Registration denied"

**Step-by-step fix**:

```
Main Menu → Network Tools (3)

1. Scan Available Networks (1)
   - Verify your carrier is visible
   - Note if status shows "Forbidden"

2. Clear Forbidden Network List (4)
   - Choose Yes to proceed
   - This removes forbidden network blocks

3. Force Network Registration (2)
   - Try Automatic (0) first
   - If fails, use Manual (1) with carrier code

4. Return to Main Menu
   - Run Quick Status Check (2)
   - Verify registration successful
```

**Common carrier codes (US)**:
- T-Mobile: 310260
- AT&T: 310410
- Verizon: 311480

---

### Issue: No Data Connection

**Symptoms**: Can register but no data, zero-byte sessions

**Step-by-step fix**:

```
Main Menu → APN & Data Connection (4)

1. Check PDP Context Status (2)
   - Verify APN is configured
   - Common APNs:
     • Hologram: "hologram"
     • AT&T: "broadband" or "phone"
     • T-Mobile: "fast.t-mobile.com"

2. Check Data Connection (3)
   - Review all three checks:
     ✓ GPRS Attach
     ✓ PDP Context Active
     ✓ IP Address Assigned

3. If context inactive:
   - Activate PDP Context (4)
   - Enter CID (usually 1)

4. If no IP address or wrong APN:
   - Configure APN (1)
   - Choose carrier preset or enter custom APN
   - Optionally activate immediately
   - Return and recheck data connection
```

---

### Issue: SIM Not Ready

**Symptoms**: SIM Status shows "SIM PIN" or not "READY"

**Solutions**:

```
Main Menu → Advanced Tools (5) → Manual AT Command (2)

1. Check status:
   AT+CPIN?

2. If shows "SIM PIN", unlock with:
   AT+CPIN="1234"
   (Replace 1234 with your PIN)

3. Verify:
   AT+CPIN?
   Should show: +CPIN: READY

4. If shows "SIM PUK":
   Contact your carrier - SIM may be locked
```

**Common SIM issues**:
- Not inserted properly → Reseat SIM card
- PIN locked → Unlock with AT+CPIN
- PUK locked → Contact carrier
- Damaged SIM → Try different SIM

---

## 📊 Signal Quality Reference

| RSSI | dBm | Quality | Action Needed |
|------|-----|---------|---------------|
| 0-9 | ≤-95 | Very Poor/Poor | 🔴 Reposition antenna |
| 10-14 | -93 to -85 | Fair | 🟡 Usable, improve if possible |
| 15-19 | -83 to -75 | Good | 🟢 Good for most uses |
| 20-31 | ≤-51 | Excellent | 🟢 Optimal |

---

## 🌐 Network Registration Status

| Code | Meaning | Color | Action |
|------|---------|-------|--------|
| 0 | Not searching | 🔴 | Check SIM and signal |
| 1 | Home network | 🟢 | All good! |
| 2 | Searching | 🟡 | Wait 30-60s |
| 3 | Denied | 🔴 | Clear FPLMN |
| 5 | Roaming | 🟢 | Connected (roaming) |

---

## 🎯 Diagnostic Workflow

### For New Setup

```
1. Run Full Diagnostic Test
   → Review all metrics
   → Identify any red flags

2. Check Signal Quality
   → Must be Fair or better
   → Reposition if needed

3. Verify SIM Status
   → Should be READY
   → Unlock if needed

4. Check Network Registration
   → Should be 1 (home) or 5 (roaming)
   → Force register if needed

5. Configure APN
   → Set correct APN for carrier
   → Verify in PDP context

6. Activate Data Connection
   → Activate PDP context
   → Verify IP address assigned

7. Export Report
   → Save baseline configuration
```

---

### For Troubleshooting

```
1. Quick Status Check
   → Identify what's wrong
   
2. If signal poor:
   → Reposition antenna
   → Re-check signal
   
3. If not registered:
   → Clear FPLMN
   → Force registration
   
4. If no data:
   → Check APN
   → Activate PDP context
   
5. Export Report
   → Document issue and resolution
```

---

## 💡 Pro Tips

### 🎯 NEW: Auto-Detection Makes Life Easy!

**No more guessing ports!**
- Tool scans ALL serial ports automatically
- Tests each port with multiple baud rates
- Shows you exactly which ports work
- Recommends the best port for AT commands
- One-click connection if only one modem found

**What auto-detection shows you:**
- ✅ Port path (e.g., /dev/ttyUSB2)
- ✅ Device type (USB Serial, CDC-ACM, UART)
- ✅ Device description (Quectel, Sierra, etc.)
- ✅ Which baud rate works
- ✅ Real-time testing progress

---

### Finding the Right Serial Port (Manual Method)

Multi-port modems usually expose:
- **Port 0**: AT commands (diagnostic)
- **Port 1**: AT commands (alternate)
- **Port 2**: AT commands (primary) ← **Most common**
- **Port 3**: GPS/NMEA (if present)

**With auto-detection**: Tool tells you which ports work!
**Manual priority**: `/dev/ttyUSB2` → `/dev/ttyUSB1` → `/dev/ttyUSB0`

---

### Improving Signal

1. **External antenna**: Always better than internal
2. **Height matters**: Higher is usually better
3. **Line of sight**: Avoid obstacles to tower
4. **Avoid interference**: Distance from WiFi, electronics
5. **Test locations**: Window > interior > basement

---

### When Registration Takes Forever

Network registration can take time:
- **First time**: 60-90 seconds
- **After FPLMN clear**: 30-60 seconds
- **Roaming**: 90-120 seconds
- **Weak signal**: 2-3 minutes

**Don't panic if "Searching" for a minute!**

---

### Data Connection Checklist

For data to work, ALL must be true:
- ✅ Signal quality Fair or better
- ✅ Network registered (status 1 or 5)
- ✅ SIM status READY
- ✅ Correct APN configured
- ✅ PDP context activated
- ✅ IP address assigned
- ✅ GPRS attached

Use "Check Data Connection" to verify all!

---

## 📱 Carrier-Specific APNs

### United States
- **Hologram**: `hologram`
- **AT&T**: `broadband` or `phone`
- **T-Mobile**: `fast.t-mobile.com`
- **Verizon**: `vzwinternet`

### Testing/IoT Carriers
- **Hologram**: `hologram`
- **Soracom**: `soracom.io`
- **Twilio**: `wireless.twilio.com`

---

## 🔧 Manual AT Commands

Quick reference for manual testing:

```bash
# Basic tests
AT              # Test communication
ATI             # Device info
AT+CPIN?        # SIM status
AT+CSQ          # Signal quality

# Network
AT+COPS?        # Current operator
AT+COPS=?       # Scan networks (slow!)
AT+CREG?        # Registration status
AT+CEREG?       # LTE registration

# Data
AT+CGDCONT?     # Show APN config
AT+CGACT?       # PDP activation status
AT+CGPADDR      # Get IP address

# Configuration
AT+CGDCONT=1,"IP","hologram"  # Set APN
AT+CGACT=1,1                   # Activate context 1
AT+COPS=0                      # Auto network select
```

---

## 🆘 Emergency Recovery

If modem is completely unresponsive:

```bash
1. Power cycle modem
   sudo reboot
   
2. Reset USB device
   sudo usb-devices
   # Find modem, note bus/device
   sudo usb_modeswitch -v 0xVVVV -p 0xPPPP -R
   
3. Try factory reset AT command
   AT&F
   AT&W
   
4. Check hardware
   - Reseat SIM card
   - Check antenna connection
   - Verify power supply
```

---

## 📖 Additional Resources

- **Hologram Docs**: https://hologram.io/docs/
- **AT Commands**: https://hologram.io/docs/reference/at-commands/
- **Full README**: See README.md in application folder
- **Export Reports**: Use option 7 to save diagnostics

---

## 🎓 Understanding Raw Values

### RSSI (Received Signal Strength Indicator)
- Raw: 0-31 (and 99 for unknown)
- Converted: -113 to -51 dBm
- Higher number = Better signal

### BER (Bit Error Rate)
- Raw: 0-7 (and 99 for unknown)
- Percentage of corrupted bits
- Lower number = Better quality

### Registration Status
- 0 = Not registered, not trying
- 1 = Connected to home network ✓
- 2 = Not registered, currently searching
- 3 = Registration rejected
- 5 = Connected, roaming ✓

---

## 🧪 Testing & Validating Data Usage

### NEW: Data Transfer Test

Want to validate your cellular provider's billing? Test it!

```
Main Menu → APN & Data Connection (4) → Test Data Transfer (7)

1. Choose test size:
   - 1 KB, 10 KB, 100 KB, 1 MB, or custom

2. Review overhead estimate:
   - Payload: Your actual data
   - TCP/IP Headers: ~40 bytes per packet
   - TLS Handshake: ~3 KB for HTTPS
   - DNS Lookup: ~80 bytes
   - HTTP Headers: ~400 bytes

3. Note TOTAL ESTIMATED usage

4. Confirm to send

5. Wait 1-2 minutes

6. Check Hologram Dashboard:
   https://dashboard.hologram.io
   → Your Device → Data Usage

7. Verify increase matches estimate
```

**What You'll See on Dashboard:**
- Total aggregated data (NOT broken down)
- 1 KB payload = ~4.5 KB total billed
- 10 KB payload = ~14 KB total billed
- 100 KB payload = ~105 KB total billed

**Tips:**
- Disable WiFi or configure routing for cellular
- Dashboard updates take 1-2 minutes
- Actual may vary ±10% due to network conditions
- Uses real data (costs apply)

---

**Remember**: Most issues are either:
1. Poor signal → Reposition antenna
2. Wrong APN → Configure correct APN
3. FPLMN block → Clear forbidden list

Start with Full Diagnostic to identify the issue! 🎯