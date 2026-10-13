#!/usr/bin/env python3
"""Read-only checks against a frozen user-derived content contract. No model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def body(text):
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r"#{1,6}\s+(正文|文稿|口播稿|口播文稿|口播脚本)\s*", line)), None)
    if start is None:
        raise ValueError("缺少明确的正文/文稿标题，不能确定计数范围")
    selected = lines[start + 1:]
    end = next((i for i, line in enumerate(selected) if re.match(r"^#{1,6}\s", line)), len(selected))
    return "\n".join(selected[:end]).strip()


def check_outputs(folder, contract):
    if not isinstance(contract, dict) or not isinstance(contract.get("channels"), list) or len(contract["channels"]) != 3:
        raise ValueError("合同需要恰好三个渠道")
    checks = []
    hashes = {}
    def check(name, passed, actual=None):
        checks.append({"name": name, "passed": bool(passed), "actual": actual})
    names = [c["file"] for c in contract["channels"]]
    if len(set(names)) != 3 or any(Path(n).name != n or n in (".", "..") for n in names):
        raise ValueError("渠道文件名需要为三个不同的安全文件名")
    paths = [folder / n for n in ["report.md", "result.json", *names]]
    check("required_files", all(p.is_file() and not p.is_symlink() and p.stat().st_size for p in paths))
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    check("skill_identity", result.get("skill") == "source-to-channel-pack")
    check("channel_files", {c.get("file") for c in result.get("channels", [])} == set(names))
    for channel in contract["channels"]:
        filename = channel["file"]
        text = (folder / filename).read_text(encoding="utf-8")
        content = body(text)
        low, high = channel["cjk_range"]
        if type(low) is not int or type(high) is not int or not 0 <= low <= high:
            raise ValueError("正文长度合同非法")
        count = len(re.findall(r"[\u4e00-\u9fff]", content))
        check(filename + ":body_cjk_range", low <= count <= high, count)
        compact = re.sub(r"\s|[*_]", "", content)
        check(filename + ":required_in_body", all(re.sub(r"\s", "", phrase) in compact for phrase in channel.get("required", [])))
        # These patterns come from the user's contract; the checker never invents facts.
        hits = [pattern for pattern in contract.get("forbidden_patterns", []) if re.search(pattern, text)]
        check(filename + ":forbidden_consumer_content", not hits, hits)
        metadata = next((c for c in result.get("channels", []) if c.get("file") == filename), {})
        check(filename + ":reported_count", metadata.get("body_cjk_count") == count, metadata.get("body_cjk_count"))
        first = next((line.strip() for line in content.splitlines() if line.strip()), "")
        first_sentence = re.split(r"(?<=[。！？])", first)[0]
        check(filename + ":scene_opening_matches", metadata.get("scene_opening") == first_sentence, metadata.get("scene_opening"))
    for path in paths:
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"checks": checks, "passed": all(c["passed"] for c in checks), "manual_required": True,
            "scope": "structure_and_explicit_text_constraints", "output_sha256": hashes,
            "note": "逐句事实蕴含、商品属性和文稿自然度仍需独立审阅；模型自填supported不是证明。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    args = parser.parse_args()
    try:
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        report = check_outputs(args.output, contract)
        report["contract_sha256"] = hashlib.sha256(args.contract.read_bytes()).hexdigest()
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        report = {"passed": False, "manual_required": True, "error": str(error)}
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
