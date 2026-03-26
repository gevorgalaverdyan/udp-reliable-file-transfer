sudo ip netns add ns_server
sudo ip netns add ns_client

sudo ip netns list

# Create a veth pair: veth_srv and veth_cli are linked
# like a channel to trade data
sudo ip link add veth_srv type veth peer name veth_cli

# ------- Move each end into a namespace -------

# Move veth_srv into ns_server
sudo  ip link set veth_srv netns ns_server

# Move veth_cli into ns_client
sudo ip link set veth_cli netns ns_client

# Verify: neither veth_srv nor veth_cli should appear on the host anymore
sudo ip link show type veth

# ------- Configure the IP addresses inside each namespace -------
# Configure ns_server side
sudo ip netns exec ns_server ip addr add 10.0.0.1/24 dev veth_srv
sudo ip netns exec ns_server ip link set veth_srv up
sudo ip netns exec ns_server ip link set lo up

# Configure ns_client
sudo ip netns exec ns_client ip addr add 10.0.0.2/24 dev veth_cli
sudo ip netns exec ns_client ip link set veth_cli up
sudo ip netns exec ns_client ip link set lo up

# Ping check
# ping client from server
sudo ip netns exec ns_server ping -c 3 10.0.0.2
# ping server from client
sudo ip netns exec ns_client ping -c 3 10.0.0.1