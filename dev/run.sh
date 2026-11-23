#!/bin/bash
# 选手方案入口（评测服务经 Dockerfile 的 ENTRYPOINT 调用本脚本，并追加参数）。
# 传参因赛道而异，至少含 --task（缺省 all）；部分赛道还传 --test 与 --out-dir /output。
#
# 本脚本是唯一固定入口；代码目录结构、入口文件名均可自行调整，
# 只需保证最终把结果写到 --out-dir（默认 /output）即可。
set -e
echo "=== 选手方案启动 ==="
echo "输入数据目录 DATA_ROOT = $DATA_ROOT"
echo "运行参数: $*"

# 进入代码目录并运行入口（路径/文件名可按需修改）
cd /app/program/solution
exec python3 src/main.py "$@"
