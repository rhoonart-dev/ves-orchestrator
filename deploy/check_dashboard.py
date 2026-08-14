#!/usr/bin/env python3
"""대시보드 HTML 의 인라인 <script> 를 뽑아 `node --check` 로 문법 검사한다.

배포 전 최소 게이트 — 서버가 없으므로 문법이 깨진 index.html 을 올리면
화면이 통째로 백지가 된다. HANDOFF §7 '검증' 의 자동화판.

    python3 deploy/check_dashboard.py dashboard/index.html
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

# src= 로 외부 파일을 부르는 태그는 본문이 없으니 제외한다.
SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", re.S | re.I)


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "dashboard/index.html")
    html = path.read_text(encoding="utf-8")

    blocks = [
        (attrs, body)
        for attrs, body in SCRIPT_RE.findall(html)
        # JSON-LD·템플릿 등 자바스크립트가 아닌 블록은 건너뛴다.
        if "type=" not in attrs.lower() or "javascript" in attrs.lower() or "module" in attrs.lower()
    ]
    if not blocks:
        print(f"{path}: 검사할 인라인 <script> 가 없다", file=sys.stderr)
        return 1

    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, (attrs, body) in enumerate(blocks, 1):
            suffix = ".mjs" if "module" in attrs.lower() else ".js"
            js = Path(tmp) / f"block{i}{suffix}"
            js.write_text(body, encoding="utf-8")
            proc = subprocess.run(
                ["node", "--check", str(js)], capture_output=True, text=True
            )
            if proc.returncode != 0:
                failed += 1
                print(f"✗ {path} script #{i}:\n{proc.stderr.strip()}", file=sys.stderr)

    if failed:
        return 1
    print(f"✓ {path}: 인라인 script {len(blocks)}개 문법 이상 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
