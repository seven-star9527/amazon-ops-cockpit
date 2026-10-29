"""Print one store/child-ASIN evidence packet for a Codex conversation."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from b_ops.inspect import inspect_product


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--sid",required=True)
    parser.add_argument("--asin",required=True)
    parser.add_argument("--domain",choices=["advertising","inventory","listing","keywords"])
    args=parser.parse_args()
    if not re.fullmatch(r"b-[0-9]{8}-[0-9]{6}-[a-z0-9]+",args.run_id):
        raise SystemExit("invalid B-line run ID")
    run=ROOT/"storage"/"runs"/args.run_id
    raw=(run/"board.json").read_bytes()
    manifest=json.loads((run/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("state")!="complete" or hashlib.sha256(raw).hexdigest()!=manifest.get("batch_sha256"):
        raise SystemExit("incomplete or altered batch")
    packet=inspect_product(json.loads(raw),args.sid,args.asin,domain=args.domain)
    print(json.dumps(packet,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
