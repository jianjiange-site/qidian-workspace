#!/usr/bin/env python3
"""Generate Python gRPC stubs for all service protos under proto/.

Usage:
    python proto/gen-python.py

Generated packages follow the convention:
    proto/<service>/python/dating_proto_qidian_<service>/
    package name: dating-proto-qidian-<service>==0.1.0
"""

import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "qidian"
SERVICES = ["user", "chat", "vision", "post", "payment", "match", "im"]
PROTOC = [sys.executable, "-m", "grpc_tools.protoc"]

IMPORT_RE = re.compile(r"^import ([a-z0-9_]*_pb2) as", re.MULTILINE)
COMMON_IMPORT_RE = re.compile(r"^from common import ([a-z0-9_]*_pb2) as", re.MULTILINE)


def fix_imports(path: str) -> None:
    text = open(path, "r", encoding="utf-8").read()
    new_text = IMPORT_RE.sub(r"from . import \1 as", text)
    new_text = COMMON_IMPORT_RE.sub(r"from . import \1 as", new_text)
    if new_text != text:
        open(path, "w", encoding="utf-8", newline="").write(new_text)


def gen(service: str) -> None:
    pkg = f"dating_proto_{NAME}_{service}"
    svc_dir = os.path.join(ROOT, service)
    out_dir = os.path.join(svc_dir, "python", pkg)

    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    proto_file = os.path.join(svc_dir, f"{service}.proto")
    cmd = PROTOC + [
        "-I", svc_dir,
        "-I", ROOT,
        f"--python_out={out_dir}",
        f"--grpc_python_out={out_dir}",
        proto_file,
    ]
    subprocess.run(cmd, check=True)

    # post.proto imports common/base_response.proto, embed the generated common
    # module into the same package so the service wheel is self-contained.
    if service == "post":
        common_proto = os.path.join(ROOT, "common", "base_response.proto")
        subprocess.run(PROTOC + ["-I", ROOT, f"--python_out={out_dir}", common_proto], check=True)
        # protoc preserves the 'common/' directory; flatten it into the package root.
        nested_common = os.path.join(out_dir, "common", "base_response_pb2.py")
        if os.path.exists(nested_common):
            os.rename(nested_common, os.path.join(out_dir, "base_response_pb2.py"))
            os.rmdir(os.path.join(out_dir, "common"))

    for name in os.listdir(out_dir):
        if name.endswith(("_pb2.py", "_pb2_grpc.py")):
            fix_imports(os.path.join(out_dir, name))

    init_file = os.path.join(out_dir, "__init__.py")
    open(init_file, "w", encoding="utf-8").close()

    print(f"generated {out_dir}")


if __name__ == "__main__":
    for svc in SERVICES:
        gen(svc)
