import sys

from client.client import Client

def main():
    print("UDP program: \n")

    if len(sys.argv) > 1:
        print(f"Arguments passed: {sys.argv[1:]}")
    

    return 0

def parse_input(args: list[str]):
    required_input = {
        "server_ip": None,
        "port": None,
        "filename": None,
        "max_payload": None,
    }

    if len(required_input!=len(args)):
        print("Not enough parameters")
        return

    for arg in args:
        if not required_input[arg]:
            print(f"Extra input {arg} ignored")
        else:
            required_input[0]

    # return Client()
    
if __name__ == "__main__":
    sys.exit(main())
