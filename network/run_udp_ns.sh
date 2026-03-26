sudo ip netns exec ns_server python server.py 9000 --segment-size 100
sudo ip netns exec ns_client python client.py 10.0.0.1 9000 file1.txt --segment-size 100