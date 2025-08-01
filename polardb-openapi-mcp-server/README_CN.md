<p align="center"><a href="./README.md">English</a> | 中文<br></p>

# 阿里云 PolarDB OpenAPI MCP 服务器

[![PyPI version](https://badge.fury.io/py/polardb-openapi-mcp-server.svg)](https://badge.fury.io/py/polardb-openapi-mcp-server)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

通过 OpenAPI 提供 PolarDB 服务的 MCP 服务器

## 前置条件
1. 使用 `brew install pipx`（macOS）或等效命令安装 `pipx`
2. Python >=3.12
3. 具有阿里云 PolarDB 服务访问权限的阿里云凭证

## 快速开始

### 使用 [cherry-studio](https://github.com/CherryHQ/cherry-studio) 简单设置 - SSE 模式（推荐）

**简单的 2 步设置：**

#### 步骤 1：安装服务器
```bash
pipx install polardb-openapi-mcp-server
```

#### 步骤 2：启动服务器并配置 Cherry Studio

**启动服务器：**
```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID="your-access-key-id"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your-access-key-secret"
export ALIBABA_CLOUD_REGION="cn-hangzhou"
export RUN_MODE="sse"
export SSE_BIND_HOST="127.0.0.1"
export SSE_BIND_PORT="12345"

run_polardb_openapi_mcp_server
```

**使用此 JSON 配置 Cherry Studio：**
```json
{
  "mcpServers": {
    "polardb-openapi": {
      "type": "sse",
      "url": "http://127.0.0.1:12345/sse"
    }
  }
}
```

将凭证替换为您的实际阿里云访问密钥。服务器将启动，Cherry Studio 将自动连接。

### 替代方案：Claude Desktop 设置

对于 Claude Desktop，您可以使用 stdio 模式：

#### 步骤 1：安装服务器
```bash
pipx install polardb-openapi-mcp-server
```

#### 步骤 2：配置 Claude Desktop
将此内容添加到您的 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "polardb-openapi": {
      "command": "run_polardb_openapi_mcp_server",
      "args": [],
      "env": {
        "ALIBABA_CLOUD_ACCESS_KEY_ID": "your-access-key-id",
        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "your-access-key-secret",
        "ALIBABA_CLOUD_REGION": "cn-hangzhou",
        "RUN_MODE": "stdio"
      }
    }
  }
}
```

将凭证替换为您的实际阿里云访问密钥。

### 使用本地客户端

#### 主要优势

* **安全与隐私**：您的组织可能有政策限制使用基于云的 MCP 客户端，因为它们通常会记录可能包含敏感或专有信息的操作活动。
* **可靠性与易用性**：许多现有的 MCP 客户端配置复杂，由于高流量负载可能经常宕机。我们的本地客户端为管理您的 PolarDB OpenAPI MCP 服务器提供了稳定、直接的替代方案。
* **PolarDB 优化**：我们的客户端包含专门的 PolarDB 领域知识和增强功能，专为 PolarDB 操作设计，这些功能在通用 MCP 客户端中不可用。

#### 设置和使用

使用以下命令启动您的本地 MCP 客户端服务：

```bash
# 如果使用源代码
cd /path/to/polardb_mcp_server/polardb-openapi-mcp-server
python3 fixed_mcp_protocol_web.py /path/to/polardb_mcp_server/polardb-openapi-mcp-server
```

或者如果您已安装包：
```bash
# 设置您的凭证
export ALIBABA_CLOUD_ACCESS_KEY_ID="your-access-key-id"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your-access-key-secret"  
export ALIBABA_CLOUD_REGION="cn-hangzhou"

# 启动本地客户端
python3 -m fixed_mcp_protocol_web
```

然后您可以在浏览器中打开以下 URL 访问 MCP 客户端：
**http://localhost:4657/**

然后您可以通过在"自然语言界面"中输入问题，然后按"询问"按钮来提出任何问题。

#### 本地客户端功能

- **自然语言界面**：用中文或英文提问
- **交互式工具测试**：直接在浏览器中测试所有 PolarDB 操作
- **实时响应**：查看 PolarDB 集群的即时结果
- **调试和开发**：完美适用于测试新功能和调试
- **安全本地执行**：无数据发送到外部服务
- **PolarDB 优化 UI**：专为 PolarDB 操作设计的专用界面

## 功能特性

此 MCP 服务器提供对阿里云 PolarDB 服务的全面访问，包括：

### 核心数据库操作
- **集群管理**：创建、描述、修改和删除 PolarDB 集群
- **数据库操作**：创建数据库、管理账户、配置端点
- **性能监控**：实时集群和节点性能指标
- **安全管理**：访问白名单配置和管理

### 高级功能
- **慢日志分析**：查询和分析慢查询日志并提供智能洞察
- **错误日志调查**：访问和分析数据库错误日志
- **性能优化**：自动化性能分析和建议  
- **云 DBA 集成**：高级数据库管理工具
- **多语言支持**：完整的中文和英文语言支持

### AI 增强功能
- **智能查询调度器**：用于查询意图识别的自然语言处理
- **文本转 SQL**：将自然语言转换为 SQL 查询
- **性能洞察**：AI 驱动的性能分析和建议
- **文档知识库**：使用 AI 辅助导入和搜索文档

### 网络和基础设施
- **VPC 管理**：虚拟私有云配置和管理
- **端点管理**：数据库连接端点配置
- **参数配置**：数据库参数调优和优化
- **资源监控**：全面的资源使用监控

## 可用的 OpenAPI 工具

此服务器提供以下 PolarDB 管理工具：

### 集群管理
* `polardb_create_cluster`：创建新的 PolarDB 集群
* `polardb_describe_regions`：列出阿里云 PolarDB 的所有可用地域
* `polardb_describe_db_clusters`：列出特定地域中的所有 PolarDB 集群及详细信息
* `polardb_describe_db_cluster`：获取特定 PolarDB 集群的详细信息
* `polardb_describe_available_resources`：列出创建 PolarDB 集群的可用资源
* `polardb_modify_db_cluster_description`：修改 PolarDB 集群的描述，包含全面验证
* `polardb_tag_resources`：为 PolarDB 资源（集群、节点等）添加标签

### 数据库和账户管理
* `polardb_create_account`：为 PolarDB 集群创建具有指定权限的数据库账户
* `polardb_describe_accounts`：列出 PolarDB 集群的数据库账户，包括账户类型、状态和数据库权限
* `polardb_describe_databases`：列出特定 PolarDB 集群中的数据库，可选择按数据库名称过滤

### 网络和连接性
* `polardb_create_db_endpoint_address`：为 PolarDB 集群创建新的数据库端点地址
* `polardb_describe_db_cluster_endpoints`：列出特定 PolarDB 集群的数据库端点，包括连接字符串和 IP 地址
* `polardb_describe_db_cluster_access_whitelist`：获取 PolarDB 集群的当前活动访问白名单配置
* `polardb_modify_db_cluster_access_whitelist`：修改 PolarDB 集群的访问白名单以控制哪些 IP 地址可以连接
* `polardb_describe_global_security_ipgroup_relation`：获取特定 PolarDB 集群的全局安全 IP 组关系
* `polardb_describe_db_cluster_connectivity`：测试从特定源 IP 地址到 PolarDB 集群的网络连接性

### 性能和监控
* `polardb_describe_slow_log_records`：获取特定 PolarDB 集群在时间范围内的慢日志记录
* `polardb_describe_db_node_performance`：获取特定 PolarDB 数据库节点在时间范围内的性能指标
* `polardb_describe_db_cluster_performance`：获取特定 PolarDB 集群在时间范围内的性能指标，包含增强分析
* `polardb_describe_db_proxy_performance`：获取特定 PolarDB 集群在时间范围内的代理性能指标，包含增强分析

### 配置和参数
* `polardb_describe_db_node_parameters`：获取特定 PolarDB 数据库节点的配置参数
* `polardb_describe_db_cluster_parameters`：获取 PolarDB 集群的配置参数，按类别组织并突出显示重要参数
* `polardb_modify_db_node_parameters`：修改 PolarDB 数据库节点的配置参数
* `polardb_modify_db_cluster_parameters`：修改 PolarDB 集群的配置参数

### 节点管理
* `polardb_extract_node_ids`：按角色（读写节点）从 PolarDB 集群中提取节点 ID
* `polardb_restart_db_node`：重启特定的 PolarDB 数据库节点，提供全面的监控指导和安全建议

### VPC 和网络基础设施
* `vpc_describe_vpcs`：列出特定地域中的所有 VPC（虚拟私有云），提供详细的网络配置信息
* `vpc_describe_vswitches`：列出特定地域中的所有交换机（虚拟交换机），提供详细的子网配置信息

## 配置选项

### 环境变量

| 变量 | 描述 | 默认值 | 必需 |
|------|------|--------|------|
| `ALIBABA_CLOUD_ACCESS_KEY_ID` | 阿里云访问密钥 ID | - | 是 |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | 阿里云访问密钥密码 | - | 是 |
| `ALIBABA_CLOUD_REGION` | 阿里云地域 | `cn-hangzhou` | 否 |
| `RUN_MODE` | 服务器模式（`stdio` 或 `sse`） | `stdio` | 否 |
| `SSE_BIND_HOST` | SSE 服务器绑定主机 | `127.0.0.1` | 否 |
| `SSE_BIND_PORT` | SSE 服务器绑定端口 | `8080` | 否 |

### 权限

确保您的阿里云凭证具有以下权限：
- PolarDB 读写访问权限
- VPC 读取访问权限  
- DAS（数据库自治服务）访问权限
- 用于性能指标的云监控访问权限

## 开发

### 本地开发设置
```bash
git clone https://github.com/aliyun/alibabacloud-polardb-mcp-server.git
cd alibabacloud-polardb-mcp-server/polardb-openapi-mcp-server

# 安装依赖
pipx install -e .

# 运行测试
pytest test/
```

### 从源代码构建
```bash
uv build
uv publish  # 仅限维护者
```

## 贡献

欢迎贡献！请随时提交 Pull Request。

1. Fork 仓库
2. 创建您的功能分支（`git checkout -b feature/amazing-feature`）
3. 提交您的更改（`git commit -m 'Add some amazing feature'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 打开 Pull Request

## 支持

- **文档**：[阿里云 PolarDB 文档](https://help.aliyun.com/zh/polardb)
- **问题反馈**：在 [GitHub](https://github.com/aliyun/alibabacloud-polardb-mcp-server/issues) 上报告问题
- **MCP 协议**：[Model Context Protocol](https://modelcontextprotocol.io)

## 许可证

此项目基于 Apache License 2.0 许可证 - 有关详细信息，请参阅 [LICENSE](../LICENSE) 文件。