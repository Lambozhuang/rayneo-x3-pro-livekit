#!/usr/bin/env bash
# Adds a one-way delay to what the agent's machine sends to the glasses' LAN, for trying the games under network delay
# at home, where there is no netem box (the lab shapes the link on ylab-netem through the QoE Lab console). Egress only,
# on this machine's own interface, no ifb: what the glasses send is not delayed, so a round trip grows by the delay once,
# and the voice, the attributes and the pictures reach the glasses later. Only packets to the LAN are delayed: the same
# interface carries the agent's requests to OpenAI, which are not the link under test, so they go through a band of the
# prio qdisc that nothing else maps to. Run on the server (lambos-ubuntu), with sudo:
#
#   sudo deploy/delay.sh 250     delay everything sent to the LAN by 250 ms
#   sudo deploy/delay.sh off     take the delay away (the interface gets its default qdisc back)
#   sudo deploy/delay.sh show    what is on the interface now
#
# The interface is the default route's unless given as the second argument, and the LAN is that interface's own /24
# unless given as the third (sudo deploy/delay.sh 250 enx68da73a40b20 192.168.3.0/24).
set -euo pipefail

cmd="${1:?usage: delay.sh <ms>|off|show [interface] [lan/24]}"
dev="${2:-$(ip -o route show default | awk '{print $5; exit}')}"
lan="${3:-$(ip -o -4 addr show dev "$dev" | awk '{print $4; exit}' | sed -E 's#\.[0-9]+/[0-9]+$#.0/24#')}"

case "$cmd" in
  off)
    tc qdisc del dev "$dev" root 2>/dev/null || true
    echo "$dev: no delay"
    ;;
  show)
    tc qdisc show dev "$dev"
    tc filter show dev "$dev" 2>/dev/null || true
    ;;
  *[!0-9]*)
    echo "usage: delay.sh <ms>|off|show [interface] [lan/24]" >&2
    exit 2
    ;;
  *)
    tc qdisc del dev "$dev" root 2>/dev/null || true
    # Four bands: the default priomap uses the first three by TOS, so band 4 holds only what the filter puts there.
    tc qdisc add dev "$dev" root handle 1: prio bands 4 priomap 1 2 2 2 1 2 0 0 1 1 1 1 1 1 1 1
    tc qdisc add dev "$dev" parent 1:4 handle 40: netem delay "${cmd}ms"
    tc filter add dev "$dev" protocol ip parent 1:0 prio 1 u32 match ip dst "$lan" flowid 1:4
    echo "$dev: ${cmd} ms added to everything sent to $lan"
    ;;
esac
