#!/usr/bin/env bash
set -euo pipefail
cat > /etc/default/grub.d/99-userver-clock.cfg <<'EOF'
GRUB_CMDLINE_LINUX="$GRUB_CMDLINE_LINUX no-kvmclock clocksource=tsc tsc=reliable tsc_early_khz=4691100 nox2apic rcupdate.rcu_normal=1"
EOF
update-grub
