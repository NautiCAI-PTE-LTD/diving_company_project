import fitz
import sys
doc = fitz.open(sys.argv[1])
for i in range(min(int(sys.argv[2]) if len(sys.argv) > 2 else 8, doc.page_count)):
    t = doc[i].get_text()
    sys.stdout.buffer.write(f"=== PAGE {i+1} ===\n".encode())
    sys.stdout.buffer.write(t.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n\n")
