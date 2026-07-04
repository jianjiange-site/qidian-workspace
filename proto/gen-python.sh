#!/usr/bin/env bash
# 重新生成所有 proto 的 Python gRPC stub。
#
# 依赖: grpcio-tools==1.68.1(与 proto/pom.xml 的 grpc.version 对齐)。
# 没装的话临时装一个 venv 即可:
#   python3 -m venv /tmp/protogen && /tmp/protogen/bin/pip install grpcio-tools==1.68.1
#   PYBIN=/tmp/protogen/bin/python ./gen-python.sh
#
# 生成物已入库(proto/<svc>/python/dating_proto_qidian_<svc>/),改了 .proto 后重跑本脚本并升版本号再发 Nexus。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PYBIN="${PYBIN:-python3}"
NAME="qidian"
SERVICES=(user chat vision post payment match im)

gen() {
  local svc="$1"
  local pkg="dating_proto_${NAME}_${svc}"
  local svc_dir="$HERE/${svc}"
  local out="$svc_dir/python/$pkg"
  rm -rf "$out"; mkdir -p "$out"
  "$PYBIN" -m grpc_tools.protoc -I "$svc_dir" -I "$HERE" \
    --python_out="$out" --grpc_python_out="$out" "$svc_dir/${svc}.proto"
  # post.proto imports common/base_response.proto; embed common into the post package.
  if [ "$svc" = "post" ]; then
    "$PYBIN" -m grpc_tools.protoc -I "$HERE" \
      --python_out="$out" "$HERE/common/base_response.proto"
    mv "$out/common/base_response_pb2.py" "$out/" && rmdir "$out/common"
  fi
  # 包内改成相对导入
  find "$out" -name '*_pb2*.py' -exec sed -i'' -e 's/^import \([a-z0-9_]*_pb2\) as/from . import \1 as/' {} +
  # post 引用的 common/base_response 在包内,也改成相对导入
  find "$out" -name '*_pb2*.py' -exec sed -i'' -e 's/^from common import \([a-z0-9_]*_pb2\) as/from . import \1 as/' {} +
  : > "$out/__init__.py"
  echo "generated $out"
}

for svc in "${SERVICES[@]}"; do
  gen "$svc"
done
