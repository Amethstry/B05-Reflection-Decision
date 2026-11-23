# B05 团队开发基线

仓库维护通用反思、知识库、离线对照和容器入口。随库数据为民用工单样例，官方评测的业务成果待队内独立验收。

## 工程入口

| 路径 | 用途 |
| --- | --- |
| [dev/src](../dev/src/) | 程序入口、JSON 读写、模型客户端、反思、SQLite 经验库和离线评分 |
| [dev/tests](../dev/tests/) | 接口与知识库测试、模拟 HTTP 网关、工单盲测和提交结构检查 |
| [data/support_tickets](../data/support_tickets/) | 民用工单基准和供离线评分使用的参考标签 |
| [Dockerfile](../dev/Dockerfile) · [run.sh](../dev/run.sh) | 在 `dev/` 构建镜像，由 `run.sh` 调用 `src/main.py` |

## 本地上手

从仓库根目录进入 `dev/`。这些检查使用进程内替身或临时数据库。

```bash
cd dev
python3 -B -m unittest discover -s tests -p 'test_knowledge.py' -v
python3 -B -m unittest discover -s tests -p 'test_runner.py' -v
docker build -t b05-dev:local .
```

如需运行完整的输入输出测试，先通过团队获准的渠道取得官方自测数据，再配置本地的 `data/selftest/` 或 `DATA_ROOT`。运行民用工单实验的参数可用 `python3 -B -m tests.run_blind_trial --help` 查看。真实网关配置由授权环境注入，模拟实验使用 `--simulated-gateway`。

## 协作约定

每项工作从 `main` 拉出短分支，经 Pull Request 评审后合并。提交说明标注所用数据、网关类型和验证结果。官方资料、自测文件、本地凭据、实验数据库与运行日志通过各自获准的渠道管理。
