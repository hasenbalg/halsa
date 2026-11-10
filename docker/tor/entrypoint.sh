#!/bin/sh
# Tor hidden-service sidecar. Persistent state (the v3 private key that
# IS the address) lives in /var/lib/tor; the installer mirrors it to
# ./tor-state next to the compose file for backups.
set -eu

TARGET="${HALSA_ONION_TARGET:-web:8000}"
RC=/tmp/torrc

cat > "$RC" <<EOF
DataDirectory /var/lib/tor
HiddenServiceDir /var/lib/tor/hidden_service
HiddenServicePort 80 ${TARGET}
SocksPort 0
AvoidDiskWrites 1
EOF

# First start: tor refuses a pre-existing but empty hidden service dir.
rmdir /var/lib/tor/hidden_service 2>/dev/null || true

exec tor -f "$RC"
