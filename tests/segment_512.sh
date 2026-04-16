# this should create 1 packet

mkdir -p files/sent files/received
yes "This is a UDP stop-and-wait test file." | head -n 200 > files/sent/test.txt # 500 Bytes
wc -c files/sent/test.txt

# SERVER
python server.py 9000

# RECEIVER
python client.py 127.0.0.1 9000 test.txt --segment-size 512

# compare
cmp files/received/test.txt files/sent/test.txt