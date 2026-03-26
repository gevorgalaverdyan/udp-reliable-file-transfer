# symmetric delay, 100ms each way
sudo ip netns exec ns_server tc qdisc add dev veth_srv root netem delay 100ms
sudo ip netns exec ns_client tc qdisc add dev veth_cli root netem delay 100ms

/usr/bin/time -f "%e seconds" sudo ip netns exec ns_client python client.py 10.0.0.1 9000 file1.txt --segment-size 100

# ------- STOP DELAY
sudo ip netns exec ns_server tc qdisc del dev veth_srv root
sudo ip netns exec ns_client tc qdisc del dev veth_cli root

# ------- VERIFICATION
sudo ip netns exec ns_server tc qdisc show dev veth_srv
sudo ip netns exec ns_client tc qdisc show dev veth_cli