#!/bin/sh

# How many users do you want?
USER_COUNT=${USER_COUNT:-5}
# The base name for users (will become user1, user2, ...)
BASE_USER=${BASE_USER:-user}
# The base password
PASS_PREFIX=${PASS_PREFIX:-pass}
# Data limit per user (in GB)
QUOTA_GB=${QUOTA_GB:-10}
# File to store usage (will be lost on restart on free plan)
LIMITER_FILE=${LIMITER_FILE:-/tmp/gost_limiter.db}

cat > /etc/gost.yaml <<EOF
services:
- name: socks5
  addr: ":1080"
  handler:
    type: socks5
    auth:
      users:
EOF

i=1
while [ $i -le $USER_COUNT ]; do
    echo "        - username: ${BASE_USER}${i}" >> /etc/gost.yaml
    echo "          password: ${PASS_PREFIX}${i}" >> /etc/gost.yaml
    i=$((i+1))
done

cat >> /etc/gost.yaml <<EOF
    limiter: mylimiter
  listener:
    type: tcp

limiters:
- name: mylimiter
  file:
    path: $LIMITER_FILE
  limits:
EOF

i=1
bytes_per_gb=1073741824
while [ $i -le $USER_COUNT ]; do
    bytes=$((QUOTA_GB * bytes_per_gb))
    echo "    - 'client=="${BASE_USER}${i}"'" >> /etc/gost.yaml
    echo "      traffic: $bytes" >> /etc/gost.yaml
    i=$((i+1))
done

echo "=== Starting Gost with these accounts ==="
cat /etc/gost.yaml | grep -E "username|password|traffic"
exec gost -C /etc/gost.yaml
