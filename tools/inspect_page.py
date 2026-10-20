"""Offline segédszkript: a mentett keresőoldalból (_search_page.html) kigyűjti a
kérésépítéshez szükséges JS-részleteket. Hálózatot nem használ."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATTERNS = sys.argv[1:] or [
    "jogszabaly-hely-holder", r"\.ajax\(", "contentType", "traditional",
    "<script src=", "HatarozatDownload", "AnonimHatarozatFileDownload",
]

text = (HERE / "_search_page.html").read_text(encoding="utf-8")
text = re.sub(r"\r+\n", "\n", text)
text = re.sub(r"\n\s*\n", "\n", text)
out = []
for pat in PATTERNS:
    hits = list(re.finditer(pat, text))
    out.append(f"##### {pat}: {len(hits)} találat")
    for m in hits[:4]:
        out.append(f"--- @{m.start()}")
        out.append(text[max(0, m.start() - 400): m.start() + 700])
(HERE / "_js_scan.txt").write_text("\n".join(out), encoding="utf-8")
print("kész:", HERE / "_js_scan.txt")
