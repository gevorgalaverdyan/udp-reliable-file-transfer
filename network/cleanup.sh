sudo ip netns exec ns_server tc qdisc del dev veth_srv root
sudo ip netns exec ns_client tc qdisc del dev veth_cli root

sudo ip netns del ns_server
sudo ip netns del ns_client