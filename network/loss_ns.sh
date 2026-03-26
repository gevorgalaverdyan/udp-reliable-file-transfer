sudo ip netns exec ns_server tc qdisc add dev veth_srv root netem loss 10%
sudo ip netns exec ns_client tc qdisc add dev veth_cli root netem loss 10%

# ------- STOP DELAY
sudo ip netns exec ns_server tc qdisc del dev veth_srv root
sudo ip netns exec ns_client tc qdisc del dev veth_cli root

# ------- VERIFICATION
sudo ip netns exec ns_server tc qdisc show dev veth_srv
sudo ip netns exec ns_client tc qdisc show dev veth_cli