import sys

def main():
    print("This code runs when the file is executed directly.")

    if len(sys.argv) > 1:
        print(f"Arguments passed: {sys.argv[1:]}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
