#!/bin/sh

# Generate Tinyproxy config with users from environment or default
cat > /etc/tinyproxy/tinyproxy.conf <<EOF
User tinyproxy
Group tinyproxy
Port 8888
Listen 0.0.0.0
Timeout 600
DefaultErrorFile "/usr/share/tinyproxy/default.html"
StatHost "tinyproxy.stats"
LogLevel Info
PidFile "/var/run/tinyproxy/tinyproxy.pid"
MaxClients 100
MinSpareServers 5
MaxSpareServers 20
StartServers 10
MaxRequestsPerChild 0
Allow 127.0.0.1
Allow 0.0.0.0/0
# Basic auth will be added later via the web panel
EOF

# Create empty user file
mkdir -p /etc/tinyproxy
touch /etc/tinyproxy/users.txt

# Start Tinyproxy
tinyproxy -d &
TINY_PID=$!

# Start web panel
cd / && python3 app.py
