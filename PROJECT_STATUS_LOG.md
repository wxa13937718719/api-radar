# API Radar 项目状态日志

> 归档日期：2026-08-30  
> 项目状态：暂停维护 / 烂尾项目归档（可运行的本地原型，尚未达到生产可用）  
> 项目目录：`D:\AI\API Radar`

## 1. 项目初衷

API Radar 最初计划做成一个运行在 Windows 本地的 AI API Provider 情报、价格比较与推荐系统。目标不是简单罗列模型新闻，而是每天回答三个实际问题：

1. 今天发生了哪些值得关注的模型/API 市场变化？
2. 在用户已有账号、套餐和预算的前提下，哪个模型、哪个渠道最适合当前任务？
3. 用户今天应该采取什么行动，例如测试某个渠道、继续使用低成本模型，还是暂缓购买？

项目设计还包括：公开网页和价格页采集、模型身份规范化、跨 Provider 价格快照、优惠与风险情报、每日推送、随时打开的本地驾驶舱、可选本地模型对话，以及 Windows 登录启动。

## 2. 实现演进概览

项目经历了从“每日新闻/通知摘要”到“AI 模型决策助手”的重构：

- 早期版本重点是定时扫描、HTML 通知和价格变化摘要。
- 后续增加 React/Vite 驾驶舱，首页改为“今天应该用哪个模型”，并加入价格、变化、优惠、风险、来源和资产页面。
- 推荐引擎随后拆成 Canonical Model 能力与 Provider Offer 渠道报价，增加能力画像、价格/速度/稳定性/兼容性、推荐模式和数据置信度。
- 针对错误推荐，隔离了 batch、subscription、agent、local 等交互模式；本地离线推荐只读取本地模型注册表，不再把云端 OpenRouter 当作本地模型。
- 增加 Provider Coverage/Discovery，已知但没有解析器的渠道会保留为“待接入”，不再伪装成已比较价格。
- 增加结构化情报摘要、影响等级、行动建议，以及可选 OpenAI-compatible 本地/云端助手。
- 最近增加 Windows 开机时交流电判断：未接电时跳过启动和弹窗；计划任务的重新注册曾因权限不足失败，需要管理员 PowerShell 手动安装。

## 3. 当前已经实现的功能

### 3.1 后端 API 与本地服务

- FastAPI 应用，默认监听 `127.0.0.1:8000`。
- SQLite + SQLAlchemy 本地持久化，启动时自动建表，并对已有 SQLite 数据库执行增量字段补齐。
- 健康检查、Provider/模型目录、价格板、价格历史/变化、跨平台比较、扫描任务、优惠、来源、结构化情报、推荐、资产、本地模型、偏好和助手聊天 API。
- 扫描任务支持 `provider=all`，单个 Provider 失败不会中止其他 Provider，扫描结果会记录为 success/failed/partial_failure。
- 原始网页/响应只保存在后台证据字段；前台主要读取 summary、impact、action 等整理后的结构化字段。

主要路由（完整实现见 `api_radar/app.py`）：

`/health`、`/providers`、`/provider-registry`、`/coverage`、`/provider-discoveries`、`/models`、`/models/{provider_id}/{provider_model_id}/identity`、`/model-quality`、`/aliases`、`/prices/changes`、`/prices/history`、`/prices/compare/{canonical_model_id}`、`/model-prices`、`/recommendations/{profile}`、`/decision/recommendations/{profile}`、`/decision/today`、`/preferences`、`/assets`、`/local-models`、`/scans`、`/promotions`、`/sources`、`/insights`、`/intelligence/scans`、`/assistant/briefing`、`/assistant/chat`。

### 3.2 Provider 采集

已实现可执行适配器：

- OpenRouter：读取公开模型目录，解析模型、上下文和能力元数据；读取 USD/CNY 汇率；保留原始 USD/token 与标准化 USD/CNY 每百万 Token 价格。
- SiliconFlow：解析公开价格页面中嵌入的 Next.js 数据；目前主要可靠取得明确公布的输入价格，输出价格未公布时保持 `null`。
- GenericWebProviderAdapter：为已发现但尚未完成专用解析器的 Provider 提供显式占位，不生成猜测价格。
- ProviderRegistry：隔离适配器注册和查找。

### 3.3 模型身份、价格与评分

- Provider 原始模型名与 Canonical Model 分离；不明确的别名不会自动合并。
- `ModelQualityProfile` 保存 coding、reasoning、writing、chinese、long_context、vision、agent_tool_use、instruction_following 等能力证据、来源和 confidence。
- `ProviderOffer` 保存渠道级价格、限额、速度、稳定性、兼容性、套餐、交互模式和渠道风险，低价渠道不会提高模型本身能力分。
- 推荐采用两阶段逻辑：先按任务筛选/比较模型能力，再在候选模型中比较 Provider Offer。
- 支持 `best_quality`（最强）、`balanced`（均衡）、`budget`（省钱）、`free`（免费）、`my_assets`（我的资源）五种模式。
- 支持 `coding`、`writing`、`long_context`、`reasoning`、`vision`、`daily_chat`、`local_offline` 任务画像。
- 评分维度为能力 40%、价格 30%、速度 15%、稳定性/可用性 15%；证据不足时显示“数据不足/Low Confidence”，不制造高精度分数。
- 典型成本同时计算输入和输出 Token，并按任务使用不同输入/输出比例。
- 免费与付费结果分离；输出价格未知的输入免费模型不认定为完全免费。
- batch 不进入实时聊天推荐；subscription 不默认当普通 API；agent 需要工具调用/兼容性信号；local 只来自已加载的本地注册模型。

### 3.4 Provider Coverage 与 Discovery

- 启动时会登记已知候选 Provider，并显示结构化支持、可比较数量和未覆盖候选。
- 用户资产对应的 Provider 可提升调查优先级。
- 已知候选包括 Packy、ModelFlare、SubRouter、Vercel AI、七牛云、AIHubMix、CherryIn、ocoolAI、PoYo、APIMODELS。
- 覆盖不足时推荐文案使用“当前已验证渠道中”，不宣称“全网最佳/最低价”。
- 当前没有为上述大多数候选完成真实价格/API 解析器；它们保留为 `discovered / needs_parser`。

### 3.5 情报、每日建议与助手

- 固定官方来源采集、网页正文清洗、内容哈希和前后快照比较。
- 结构化 `IntelligenceInsight` 包含摘要、影响等级（critical/high/medium/low）、行动建议和生成方式。
- 只有检测到真实变化、优惠、免费额度、价格、限速、故障、风险等事件才适合进入首页；普通网页导航文本会被清洗。
- 每日报告包含“今天建议”行动段落，并可引用官方来源链接和采集时间。
- 助手默认可用确定性规则；配置 `API_RADAR_LLM_ENABLED=true` 后，可调用 Ollama、LM Studio、vLLM 或兼容的 OpenAI API 改写简报和回答追问。
- 当前 `.env` 配置为 `http://127.0.0.1:1234/v1`、模型 `qwen/qwen3.5-9b`、禁用思考模式；LLM 失败会回退规则结果。
- 对话只会根据明确措辞调整本地偏好（如低成本、质量、长上下文、工具调用），不会改写事实或模型身份。

### 3.6 React 驾驶舱

首页/导航已经包含：

- 决策中心：今日行动、任务类型 TOP 推荐、AI Value、价格排行、变化、风险、结构化情报、助手对话。
- 价格行情：当前 `model_price` 价格板，输入/输出、上下文、来源和更新时间。
- 模型变化：新增、涨价、降价及相邻快照差异。
- 优惠与来源：优惠、来源类型、采集时间和手动情报采集按钮。
- 我的资产：Provider、Key 状态、余额、套餐、可用模型等；表单不接受/保存明文 API Key。
- 可视化上区分“已有账号”“数据不足”“身份待确认”等状态。

### 3.7 Windows 启动与脚本

- `open_radar.ps1` 可隐藏启动 API（8000）和 Dashboard（5173），并使用 Edge App 窗口打开页面。
- `install_launcher.ps1` 创建桌面快捷方式并注册 `Ctrl+Alt+R` 热键。
- `install_background.ps1` 注册 Windows 登录触发的隐藏计划任务。
- 启动脚本现已先检查交流电：`PowerLineStatus=Offline` 时直接退出，不启动服务、不弹窗口；无法检测或无电池设备默认放行。
- `-IgnorePowerCheck` 可用于手动调试。

## 4. 文件清单与职责

### 4.1 根目录文件

| 文件 | 类型 | 作用 |
|---|---|---|
| `README.md` | 文档 | 安装、运行、架构、推荐、助手和 Windows 启动说明 |
| `PROJECT_STATUS_LOG.md` | 本日志 | 本次归档的项目初衷、现状、文件和未完成项 |
| `pyproject.toml` | 配置 | Python 包元数据、运行依赖、开发依赖、pytest/ruff 配置 |
| `.env.example` | 配置模板 | 数据库、日志、LLM 和超时等环境变量示例 |
| `.env` | 本地配置 | 当前本机 LLM 配置；含本地环境信息，不建议上传 GitHub |
| `.gitignore` | Git 配置 | 忽略虚拟环境、缓存、数据库、`.env`、dist 和 egg-info |
| `api_radar.db` | SQLite 数据 | 本机运行时数据库；应视为运行产物，不建议提交仓库 |
| `siliconflow-pricing.html` | HTML 快照 | SiliconFlow 价格页的本地抓取/调试样本 |

### 4.2 `api_radar/` 后端源码

| 文件 | 作用 |
|---|---|
| `__init__.py` | 包声明和版本号 |
| `app.py` | FastAPI 应用、请求模型、全部 HTTP 路由及序列化 |
| `config.py` | Pydantic Settings 环境配置与缓存 |
| `db.py` | SQLAlchemy engine/session、建表和 SQLite 增量字段兼容 |
| `models.py` | Provider、Model、ModelQualityProfile、ProviderOffer、ModelPrice、价格快照、情报、资产、扫描等 ORM 表 |
| `intelligence.py` | 官方来源抓取、正文清洗、哈希变化检测和结构化 insight |
| `notification.py` | 将报告/Markdown 渲染为安全的样式化 HTML 通知 |
| `providers/base.py` | Provider 元数据、标准化模型/价格 DTO 和适配器抽象接口 |
| `providers/registry.py` | Provider 适配器注册表 |
| `providers/openrouter.py` | OpenRouter 目录和价格适配器 |
| `providers/siliconflow.py` | SiliconFlow 价格页适配器 |
| `providers/generic.py` | 未完成 Provider 的占位适配器 |
| `providers/__init__.py` | Provider 包初始化 |
| `services/scanner.py` | 扫描编排、模型/价格写入、Provider 隔离和快照保存 |
| `services/scan_jobs.py` | 后台扫描/情报任务包装器 |
| `services/catalog.py` | Provider 模型目录、身份确认和别名处理 |
| `services/prices.py` | 价格板、历史、变化和跨平台比较查询 |
| `services/recommendations.py` | 候选生成、能力证据、成本、模式过滤、评分和决策中心 |
| `services/discovery.py` | 候选 Provider 种子、资产优先级和覆盖率 |
| `services/validation.py` | 价格单位、模型身份和推荐资格校验 |
| `services/assistant.py` | 事实整理、确定性简报、可选 LLM 简报、对话和偏好更新 |
| `services/__init__.py` | 服务包初始化 |

### 4.3 `dashboard/` 前端

| 文件 | 作用 |
|---|---|
| `index.html` | Vite HTML 入口 |
| `package.json` | React/Vite/TypeScript/Lucide 依赖和 build 命令 |
| `package-lock.json` | npm 依赖锁定 |
| `tsconfig.json` | 严格 TypeScript 编译配置 |
| `vite.config.ts` | Vite 开发服务器、5173 端口和 `/api` 代理 |
| `src/main.tsx` | React 挂载入口 |
| `src/App.tsx` | 页面状态、导航、决策中心、价格/变化/优惠/资产/助手组件 |
| `src/api.ts` | 前端 API 客户端和响应类型定义 |
| `src/styles.css` | 驾驶舱视觉样式、卡片、表格、风险/影响颜色和响应式布局 |
| `src/vite-env.d.ts` | Vite 类型声明 |
| `dist/` | 已生成的前端构建产物；应视为可再生成文件 |
| `tsconfig.tsbuildinfo` | TypeScript 构建缓存 |

### 4.4 `scripts/` 自动化与 Windows 脚本

| 文件 | 作用 |
|---|---|
| `scan.py` | 初始化数据库并执行 OpenRouter/SiliconFlow/all 扫描 |
| `report.py` | 输出指定 profile 的推荐与 briefing JSON |
| `intelligence_scan.py` | 执行官方情报采集并输出 JSON 结果 |
| `open_radar.ps1` | 隐藏启动 API、前端和 Edge App；含交流电检查 |
| `install_background.ps1` | 安装 Windows 登录计划任务 |
| `install_launcher.ps1` | 安装桌面快捷方式和全局热键 |
| `__pycache__/` | Python 字节码缓存，不应提交 |

### 4.5 `tests/` 测试与样例

| 文件 | 覆盖范围 |
|---|---|
| `test_api.py` | FastAPI 路由、价格历史、身份确认、偏好、资产和决策中心 |
| `test_recommendations_engine.py` | 两阶段推荐、能力分离、模式隔离、免费、batch、subscription、vision、本地模型、成本和覆盖率 |
| `test_openrouter.py` | OpenRouter 价格归一化和扫描持久化 |
| `test_siliconflow.py` | SiliconFlow 价格页解析和输入价格 |
| `test_prices.py` | 汇率变化不误报 Provider 价格变化 |
| `test_intelligence.py` | 正文清洗、快照哈希和真实变化检测 |
| `test_notification.py` | HTML 样式、Markdown 链接和不可信文本转义 |
| `test_provider_contract.py` | Provider 抽象接口约束 |
| `test_schema.py` | 核心 ORM 表创建 |
| `fixtures/openrouter_models.json` | OpenRouter 测试夹具 |
| `__pycache__/` | 测试字节码缓存，不应提交 |

### 4.6 `automation/`

| 文件 | 作用 |
|---|---|
| `automation/openclaw/README.md` | OpenClaw 集成边界说明：调用脚本/API，不直接导入内部模块 |

### 4.7 运行产物与被忽略目录

`.venv/` 是 Python 虚拟环境；`dashboard/node_modules/` 是 npm 安装目录；`.pytest_cache/`、`.ruff_cache/`、各处 `__pycache__/` 是缓存；`data/` 保存 API/Dashboard 日志；`dashboard/dist/` 是构建产物；`api_radar.egg-info/` 是 setuptools 元数据。这些文件对本地运行有用，但不适合直接作为 GitHub 源码提交内容。

当前目录中还存在以下生成/运行文件：

- `api_radar.egg-info/dependency_links.txt`、`PKG-INFO`、`requires.txt`、`SOURCES.txt`、`top_level.txt`：setuptools 安装元数据。
- `dashboard/tsconfig.tsbuildinfo`：TypeScript 增量构建缓存。
- `data/api-radar-api.log`、`data/api-radar-api-error.log`：Uvicorn 标准输出/错误日志。
- `data/api-radar-dashboard.log`、`data/api-radar-dashboard-error.log`：Vite 标准输出/错误日志。
- `dashboard/dist/index.html`、`dashboard/dist/assets/*`：历史前端构建结果，随源码变化后应重新生成。
- 各源码目录下的 `__pycache__/*.pyc`、`tests/__pycache__/*.pyc`、`scripts/__pycache__/*.pyc`：Python 字节码缓存。

## 5. 2026-08-30 本机数据快照

数据库文件 `api_radar.db` 当前约 6.23 MB，最后修改时间为 2026-08-29。表记录数如下（它们是本机历史，不代表新仓库安装后的初始数据）：

| 表 | 记录数 |
|---|---:|
| `providers` | 12 |
| `models` | 351 |
| `provider_models` | 484 |
| `model_price` | 484 |
| `provider_offers` | 422 |
| `price_snapshots` | 3,867 |
| `sources` | 18 |
| `source_snapshots` | 126 |
| `intelligence_insights` | 93 |
| `recommendations` | 474 |
| `scan_runs` | 20 |
| `scan_results` | 20 |
| `promotions` | 0 |
| `user_assets` | 0 |
| `local_model_registry` | 0 |
| `model_quality_profiles` | 0 |
| `provider_discoveries` | 0 |
| `user_preferences` | 1 |

Provider 覆盖现状：12 个登记 Provider 中，OpenRouter 和 SiliconFlow 为 `supported/ready`，可比较 Provider 为 2 个；其余候选主要是 `discovered/needs_parser`。因此当前推荐只能表述为“当前已验证渠道中”，不能代表全网最低价。数据库中的七牛云名称目前还出现过编码异常，属于待修复的数据质量问题。

## 6. 验证记录

本次归档前执行的检查：

- Python 测试：`19 passed`（pytest，含 5 条第三方/框架弃用警告）。
- Ruff：`All checks passed!`。
- PowerShell 语法：`open_radar.ps1`、`install_background.ps1` 均通过解析。
- 当前电源状态：`PowerLineStatus=Online`。
- TypeScript：`npm run build` 已通过 `tsc --noEmit`，但 Vite 清理既有 `dashboard/dist/assets` 时因 Windows `EPERM/Permission denied` 失败；这更像被占用/权限问题，未判定为源码编译错误。
- 当前归档时未发现 8000/5173 监听服务；Edge 进程仍可能存在历史窗口。
- 计划任务重新注册曾返回 `Access is denied`，需要管理员 PowerShell 执行安装脚本后才可确认开机任务已更新。

## 7. 已知限制与未完成项

1. Provider 市场覆盖仍很窄：Packy、ModelFlare、SubRouter、AIHubMix、CherryIn、PoYo、APIMODELS 等没有完成可靠解析器，价格保持 unknown。
2. 当前数据库缺少真实用户资产和本地模型注册数据，`my_assets` 与 `local_offline` 在新环境中可能没有结果。
3. 能力画像表当前为空，许多推荐只能显示“数据不足”；公开目录元数据不是完整 benchmark。
4. 推荐质量依赖 Canonical identity 和 Provider Offer 的完整性，模型身份映射仍需人工确认。
5. SiliconFlow 输出价格缺失时只能做部分价格比较；不同计费单位、套餐额度和缓存价格仍需更完整标准化。
6. 情报采集当前以固定官方来源和规则摘要为主，并不是完整的全网搜索/新闻理解系统；社区来源只是线索，不能直接当价格事实。
7. LLM 助手是可选改写/对话层，不负责事实校验、价格计算或模型身份判断；本地小模型效果取决于 LM Studio/Ollama 服务是否运行。
8. 每日通知体系曾有较多实验脚本，当前主路径已经转向 Dashboard；HTML 通知渲染器仍保留，但没有形成完整的可靠 Windows 通知产品。
9. Windows 开机计划任务需要管理员权限重新安装；电源判断是“无法检测时放行”，在极少数完全无法读取电源状态的设备上可能仍会启动。
10. 没有迁移工具、生产级日志轮转、认证、多用户隔离、自动备份和跨机器部署方案。
11. 前端 Vite 构建产物可能被正在运行的 Edge/开发进程锁定；归档或重新构建前应先关闭相关进程。
12. 项目没有当前 Git 提交历史（工作目录中未检测到 `.git`），上传 GitHub 前应重新初始化仓库并检查 `.env`、数据库、日志、缓存和构建产物是否被排除。

## 8. 重新继续开发时的建议顺序

1. 先建立 Git 仓库、清理本机运行产物、保留本日志和 README，设置安全的初始提交。
2. 先补 Provider Discovery/Parser：Packy、ModelFlare、SubRouter、AIHubMix 等优先于继续做 UI。
3. 引入人工确认的能力基准与质量画像，给每个能力值附来源、置信度和更新时间。
4. 为价格单位、套餐额度、免费/付费、batch/API/subscription 建立更严格的数据契约和迁移机制。
5. 用真实用户资产与本地 LM Studio 状态做端到端推荐验收，重点检查“模型 + Provider + 资格”三者是否同时成立。
6. 修复七牛云编码、Vite dist 锁定、计划任务安装权限和日志轮转。
7. 再考虑扩大情报来源、加入真正的定时通知和更完善的 LLM 辅助；不要在事实覆盖不足时追求“全网最佳”文案。

## 9. 归档结论

API Radar 已经完成一个功能较完整的 Windows 本地原型：能够采集两个公开 Provider、保存价格历史、进行身份和资格校验、输出多种模式的模型+渠道推荐、记录覆盖率、生成结构化情报，并通过 React 驾驶舱和可选本地 LLM 提供交互体验。

但它仍然不是可靠的生产级“AI 领域汽车之家/行情软件”：市场覆盖、质量证据、资产数据、定时通知和 Windows 部署都存在明显缺口。当前最准确的定位是“有真实后端和 UI 的研究型决策助手原型”，适合上传 GitHub 作为阶段性/烂尾项目归档，未来从 Provider 覆盖和数据可信度继续恢复开发。
