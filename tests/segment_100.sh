# this should create 5 packets

mkdir -p files/sent files/received
yes "This is a UDP stop-and-wait test file." | head -n 200 > files/sent/test.txt # 500 Bytes
wc -c files/sent/test.txt

# SERVER
python server.py 9000 --segment-size 100

# RECEIVER
python client.py 127.0.0.1 9000 test.txt --segment-size 100

# compare
cmp files/received/test.txt files/sent/test.txt