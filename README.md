# 脓毒症智能预警与多模态推演工作站

基于 FastAPI、SQLite、官方 MCP Python SDK、本地 LM Studio 与本地静态 SPA 的科研原型。后端包含七个独立 stdio MCP 子进程，临床观测写入必须经过服务端会话鉴权、指标安全校验和人工复核写入口。

> **安全边界**：本工程为科研与软件验证原型，内置患者及观测均为模拟数据，不构成临床诊疗建议，不可直接用于临床决策。风险评分、干预轨迹和策略指标尚未经过真实临床队列验证。图像识别结果必须由有权限人员对照原图复核；推演轨迹不是患者结局预测，也不提供未校准的生存概率。

## 1. Windows 一键启动

### 环境准备

1. 安装 64 位 **Python 3.12**，安装时勾选“Add Python to PATH”。
2. 将 RAR 解压到本地目录，例如 `D:\sepsis_poc9`。
3. 首次启动需要联网安装 Python 依赖；之后可离线运行。
4. 双击 `run.bat`。脚本会创建 `.venv`、安装依赖、初始化 SQLite，并打开：
   - 工作站：`http://127.0.0.1:8000`
   - API 文档：`http://127.0.0.1:8000/docs`

关闭启动窗口即可停止服务。再次使用时直接双击 `run.bat`，不会重复安装依赖。

### 本地账户

| 角色 | 用户名 | 密码 | 权限 |
|---|---|---|---|
| 临床医生 | `clinician` | `clinician123` | 临床查看、复核、录入、预警处置、推演与简报 |
| 系统工程师 | `engineer` | `engineer123` | 临床只读、系统状态、MCP 工具及只读诊断 |

授权仅依据服务端会话，不使用前端提交的角色字段。正式部署前请修改账户密码与 `SESSION_SECRET`。

## 2. PyCharm 手动运行

1. 用 PyCharm 打开工程根目录，选择 **Python 3.12** 解释器。
2. 在 Terminal 执行：

```bash
python -m pip install -r requirements.txt
python scripts/init_db.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

3. 浏览器打开 `http://127.0.0.1:8000`。

可将 `.env.example` 复制为 `.env` 后修改配置。不创建 `.env` 也能使用默认配置。

## 3. 配置 LM Studio

1. 在 LM Studio 中启动本地 OpenAI 兼容服务，默认地址为 `http://127.0.0.1:1234/v1`。
2. 加载下列模型，模型 ID 应与 `.env` 一致：

```text
文本模型：qwen3-8b
文本降级：qwen2.5-3b-instruct
视觉模型：qwen2.5-vl-7b-instruct
向量模型：nomic-ai/text-embedding-nomic-embed-text-v1.5
```

3. 如本机模型 ID 不同，修改 `.env` 中 `TEXT_MODEL`、`TEXT_FALLBACK_MODEL`、`VISION_MODEL`、`EMBEDDING_MODEL` 后重启。
4. 文本模型只用于交接简报；视觉模型只用于图像字段提取。视觉识别失败时**不会**使用文本模型替代，也不会生成虚构字段。
5. LM Studio 未启动时，病区、观测、预警、复核、确定性推演、审计等基础功能仍可使用；简报会明确标记为“结构化模板”，图像识别会提示失败并保留原图。

`RAG_EMBED_MODE=auto` 时优先使用本地向量模型，不可用时自动降级为确定性哈希向量；可设为 `local` 强制本地向量模型，或设为 `hash` 强制离线哈希向量。

## 4. 主要操作路径

- **病区总览**：查看床位、SOFA、风险评分及待处理预警，点击患者卡片进入工作台。
- **患者工作台**：查看最新生命体征、指标趋势、观测版本与患者预警；医生可录入观测。
- **图像复核**：上传图像 → 提取可见字段 → 对照原图逐项复核 → 确认入库或驳回。识别失败、驳回均不会删除原图。
- **干预推演**：生成三条确定性干预路径及指南证据。新增观测后，历史推演自动标记“输入已更新”。
- **交接简报**：本地文本模型不可用时自动使用结构化模板；医生可修订并保存。
- **设备与数据**：设备未连接时明确显示“未连接”，可通过结构化结果导入专科指标。
- **质控审计**：查看复核任务、过期推演、策略版本和临床操作审计。
- **系统管理**：从右上角用户菜单进入，查看 LM Studio、MCP 进程、注册工具和调用追踪，并执行只读连通性检查。

## 5. 数据与索引维护

运行数据位于 `data/`：

```text
data/sepsis.db                  SQLite 主数据库
data/uploads/original/         原始图像字节，SHA-256 命名
data/uploads/normalized/       标准化 PNG，SHA-256 命名
data/vector/                   向量索引与分块 ID 映射
data/logs/                     主服务及各 MCP 子进程日志
```

重建指南向量索引：

```bash
python scripts/rebuild_faiss_index.py
```

索引始终从 `evidence_chunks` 原文分块重建；`evidence_links` 只保存推演或简报与证据的关联。FAISS 在支持的平台使用 `faiss-cpu`；Windows 官方 pip 源通常没有对应 wheel，因此 Windows 会自动使用 NumPy 精确内积检索后端，保证本地可运行，证据来源与排序逻辑不变。若已通过 Conda 等途径安装 FAISS，工程会优先使用 FAISS。

重置全部本地数据：先停止服务，再删除 `data/sepsis.db*`、`data/vector/*` 和需要清理的上传文件，然后重新执行 `python scripts/init_db.py`。

## 6. 自动化验证

```bash
python -m pytest
```

测试使用独立临时数据库，不修改正式 `data/sepsis.db`，覆盖：登录、MCP 工具注册、证据重建、指标白名单与单位校验、身份伪造、越权写入、重复确认、原图保留、推演过期，以及 MCP 单次超时不重启共享进程。

独立离线评估脚本不连接在线 MCP Host：

```bash
python scripts/offline_eval.py your_labeled_data.csv --threshold 55
```

CSV 必须包含 `label,risk_score` 两列，`label` 为 0/1；输出灵敏度、特异度和假阳性率。

## 7. 工程结构

```text
app/main.py             REST API、图像复核与临床业务流程
app/mcp_host.py         MCP 子进程生命周期、超时、熔断与审计
app/mcp_server.py       七类 MCP 服务及九个白名单工具
app/models.py           SQLite 数据模型
app/security.py         密码哈希、服务端会话与角色控制
app/clinical.py         指标校验、风险评分与确定性推演
app/lm.py               LM Studio 文本、视觉与降级调用
app/rag.py              本地指南检索及原子索引重建
static/                 无运行时 CDN 的 ICU 工作站 SPA
scripts/                初始化、索引重建与独立离线评估
tests/                  自动化正向与负面测试
```

本工程不连接外部云服务，不采集真实患者数据，不在审计中保存图像 Base64 或模型思维链。若用于后续真实环境研究，仍需补充院内身份认证、传输加密、数据脱敏、备份恢复、设备接口验证、模型临床验证及相应合规评审。
