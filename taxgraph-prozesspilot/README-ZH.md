# ProzessPilot：中文安装与使用说明

**这是一个可以本地运行、也可以部署到服务器的 §20 UmwStG Hackathon Web App。** App 用户界面全部使用德语。本仓库包含应用代码、测试、运行配置和文档。

> 使用边界：本版本是 **可运行的软件原型**，但只用于**虚构税务案例**；没有 TaxGraph 实时 API。另有 MCP Phase 1 命令行工具，只读取服务器提供的元数据，不调用工具，也不传输案例数据。当前没有可用于实时发现的密钥，因此尚未确认服务器目录和工具架构；Phase 2 尚未实现。不构成税务意见或可直接投入德国事务所生产环境的 GDPR 合规软件。

## 方法 A：Mac / Linux 一键启动

准备：Python 3.11+（推荐 3.12）和首次安装依赖所需的网络。

```bash
unzip prozesspilot-hackathon.zip
cd taxgraph-prozesspilot
chmod +x start-lokal.sh
./start-lokal.sh
```

脚本会创建 `.venv`，安装 `requirements.txt` 中固定版本的 Python 依赖，启动后浏览器打开：**http://127.0.0.1:8080**。

关闭应用：在终端按 `Ctrl+C`。重新启动只需再次运行 `./start-lokal.sh`；SQLite 数据库持久保存在 `data/prozesspilot.sqlite3`。

如果没有权限使用脚本，可以手动运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.server:app --host 127.0.0.1 --port 8080
```

## 方法 B：Docker（Mac/Linux/Windows 通用）

安装 Docker Desktop / Docker Engine + Compose，然后在项目目录中：

```bash
cp .env.example .env
docker compose up --build -d
```

默认仍为 http://127.0.0.1:8080 ，且 Docker Volume 保存数据。查看运行状态：

```bash
docker compose ps
docker compose logs -f prozesspilot
```

停止：`docker compose down`（**不要**使用 `down -v`，否则会删除数据库 Volume）。

## 方法 C：服务器托管

- 在 `.env` 设置 `APP_ENV=production`，以及至少 16 位、独一无二的 `APP_PASSWORD`；可修改 `APP_USER`。
- 必须使用 HTTPS 反向代理（Caddy / Nginx）或托管商 HTTPS 服务；不要把 Basic Auth 直接暴露在公网 HTTP。
- 自己的 VPS 推荐 Docker Compose 默认绑定 `127.0.0.1:8080`，再配置 HTTPS 反向代理。若托管平台需要暴露容器端口，使用 `BIND_ADDRESS=0.0.0.0`。
- 挂载持久化磁盘 `/data`。本项目没有多租户隔离或专业用户身份验证，只适合作为受控 Hackathon 演示。

## 应用怎么用

1. 选一个 `Musterfall A–D`，或者通过左侧 `+` 新增一个虚构案例。
2. 左侧 `Sachverhalt` 输入事实。只有状态为 `Bestätigt` 且存在 `Nachweisreferenz / Aktenvermerk` 的字段才能被后端作为已确认事实。真实文件不会被上传。
3. 点击 `Prüfung ausführen`。中央 Process Graph 高亮实际路径，右侧显示德语建议。
4. 在 `Prüfpfad & Bericht` 查看历史执行、所有节点和边的判断轨迹、哈希检查、打印报告和导出 JSON 审计包。
5. 在 `Prozessmodell verwalten` 创建 Draft，可编辑所有 Nodes、Edges、Guard、Guidance、Pitfalls，进行结构检查，再发布不可直接修改的新版本。
6. 只有当所有核心检查走通时，才能在 UI 记录人工“Freigabe”或“Ablehnung”；即使录入了人工姓名，这不等于系统验证了其税务师执业身份。

## MCP Phase 1 元数据发现

`scripts/discover_mcp.py` 通过进程环境变量 `MCP_API_KEY` 读取密钥，只发现 MCP 服务声明的元数据；不会执行工具或传输案例事实。CLI 本身不会读取 `.env`。密钥输入、输出处理和后续阶段边界见德语说明：[MCP Phase 1 文档](docs/MCP-PHASE1.md)。

## 数据与安全

- 本地数据库：`data/prozesspilot.sqlite3`；可以使用 `python3 scripts/backup_sqlite.py` 安全备份。
- Docker 数据默认写入 Volume，不会随着容器停止而自动丢失。
- 日志和建议报告保留节点/边的实际决策，适合 Hackathon 展示；**不是**外部公证的不可篡改审计系统。
- 法律条款及基础规则仍需德国 Steuerberater 按具体事实、适用法律版本进行验证。尤其不能将这个 demo 直接用于给真实客户出具税务意见。

详细架构请看 `docs/ARCHITEKTUR.md`（德语），全部 API 可通过启动后 `http://127.0.0.1:8080/api/docs` 查看。
