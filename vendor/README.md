# 内置发行包

这些文件是固定版本的公开原始发行包，不是从开发者电脑复制的运行环境。
完整源码下载包已包含Windows x64首次准备所需组件，双击根目录`Balatro Agent.exe`即可使用。

| 归档 | 内容与许可 |
| --- | --- |
| balatrobot-9052d76.zip | BalatroBot 1.5.2固定提交源码，MIT；原始LICENSE保留 |
| lovely-0.9.0.zip | Lovely 0.9.0 Windows注入器，MIT；全文见third_party/lovely-LICENSE.md |
| steamodded-26.829.0.zip | Steamodded 26.829.0完整未修改源码，GPL-3.0；原始LICENSE保留 |
| uv-0.9.21.zip | uv 0.9.21 Windows发行，MIT或Apache-2.0；两份全文见third_party/ |
| runtime-windows-x64.zip | Astral提供的Python 3.13.11原始发行归档，以及锁定的运行／构建wheel；各自完整许可随原归档保留 |

Mod与uv的URL、版本、SHA-256见`config/dependencies.lock.json`，其中offline_runtime绑定`config/runtime.lock.json`的哈希；后者记录Python与wheel的来源、版本、SHA-256和许可文件。程序核验完整归档及成员后在项目内解压，并通过本地Python镜像和wheel目录准备隔离环境。没有游戏本体、存档、个人配置、模型密钥或已有电脑的venv。

维护者更新版本时，先重新取得对应的上游公开发行包、更新锁和许可，再通过`scripts/project.py`检查与打包；禁止用本机`.venv/`、`.tools/`或完整下载缓存替换这些文件。游戏安装、备份和客户端配置继续遵循原有维护检查。
