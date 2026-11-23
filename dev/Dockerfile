# 选手方案镜像（通用模版）
# 构建需联网（拉取 python 基础镜像 + pip 安装依赖）
#
FROM python:3.11-slim

WORKDIR /app/program

# 先装依赖（利用 Docker 层缓存，改代码不用重装）
COPY requirements.txt /app/program/requirements.txt
RUN pip install --no-cache-dir -r /app/program/requirements.txt

# 复制选手代码（测试数据不进镜像，运行时只读挂载到 /input）
COPY . /app/program/solution/

# 保证入口脚本可执行
RUN chmod +x /app/program/solution/run.sh

WORKDIR /app/program/solution

# 数据挂载点
ENV DATA_ROOT=/input

# 入口：run.sh 里调用选手代码，可传参覆盖
ENTRYPOINT ["/app/program/solution/run.sh"]
CMD ["--task", "all"]
