from pathlib import Path

def validate_all():
    sent_path = Path("./files/sent")
    sent_files = sorted([f for f in sent_path.iterdir() if f.is_file()])

    recv_path = Path("./files/received")
    recv_files = sorted([f for f in recv_path.iterdir() if f.is_file()])

    if len(sent_files) != len(recv_files):
        print(f"ERROR: count mismatch. SENT({len(sent_files)}) vs RECV({len(recv_files)})")
        return

    for s_file, r_file in zip(sent_files, recv_files):
        try:
            sent_content = s_file.read_text(encoding='utf-8')
            recv_content = r_file.read_text(encoding='utf-8')
            
            if sent_content != recv_content:
                print(f"ERROR: content mismatch in file: {s_file.name}")
                return
                
        except Exception as e:
            print(f"An error occurred processing {s_file.name}: {e}")
            return
    
    print("Transfer was OK")

def validate_X(filename:  str):
    sent_p = Path(f"./files/sent/{filename}")
    recv_p = Path(f"./files/received/{filename}")

    sent_txt = sent_p.read_text(encoding='utf-8')
    recv_txt = recv_p.read_text(encoding='utf-8')

    if sent_txt != recv_txt:
        print(f"ERROR: content mismatch in file: {sent_p.name}")
        return
    
    print("Transfer was OK")
    
if __name__ == "__main__":
    validate_X("file3.txt")
    validate_all()