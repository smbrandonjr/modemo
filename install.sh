#!/bin/bash
# Installation script for Cellular Modem Diagnostic Tool

echo "================================================"
echo "Cellular Modem Diagnostic Tool - Installation"
echo "================================================"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Warning: Running as root. This is okay but not required."
    echo ""
fi

# Check Python version
echo "Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d ' ' -f 2)
    echo "✓ Python 3 found: $PYTHON_VERSION"
else
    echo "✗ Python 3 not found. Please install Python 3.7 or higher."
    exit 1
fi

echo ""

# Install dependencies
echo "Installing Python dependencies..."
if pip3 install -r requirements.txt; then
    echo "✓ Dependencies installed successfully"
else
    echo "✗ Failed to install dependencies"
    echo "  Try manually: pip3 install rich pyserial"
    exit 1
fi

echo ""

# Make script executable
echo "Making script executable..."
chmod +x modem_diagnostics.py
echo "✓ Script is now executable"

echo ""

# Check for dialout group membership
echo "Checking serial port permissions..."
if groups $USER | grep -q dialout; then
    echo "✓ User is in dialout group"
else
    echo "⚠ User is NOT in dialout group"
    echo "  You may need serial port access. Run:"
    echo "  sudo usermod -a -G dialout $USER"
    echo "  Then log out and back in."
fi

echo ""

# List available serial ports
echo "Available serial ports:"
ls -la /dev/tty{USB,ACM,AMA,S}* 2>/dev/null | grep -E "tty(USB|ACM|AMA|S)" || echo "  No common serial ports found"

echo ""

# Check for common modem detection
echo "Checking for USB modems..."
if lsusb | grep -iE "modem|cellular|sierra|huawei|ublox|quectel|telit|simcom"; then
    echo "✓ USB modem detected:"
    lsusb | grep -iE "modem|cellular|sierra|huawei|ublox|quectel|telit|simcom"
else
    echo "  No obvious USB modem detected (this is okay if using UART)"
fi

echo ""
echo "================================================"
echo "Installation Complete!"
echo "================================================"
echo ""
echo "To run the application:"
echo "  python3 modem_diagnostics.py"
echo ""
echo "Or with sudo if needed:"
echo "  sudo python3 modem_diagnostics.py"
echo ""
echo "Common serial ports for cellular modems:"
echo "  - /dev/ttyUSB0, /dev/ttyUSB1, /dev/ttyUSB2"
echo "  - /dev/ttyACM0"
echo "  - /dev/ttyAMA0 (Raspberry Pi UART)"
echo ""
echo "If you encounter 'Permission denied' errors:"
echo "  1. Run: sudo usermod -a -G dialout $USER"
echo "  2. Log out and log back in"
echo "  3. Or run with sudo"
echo ""
echo "For help and documentation, see README.md"
echo ""