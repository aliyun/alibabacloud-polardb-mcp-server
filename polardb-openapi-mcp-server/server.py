from starlette.applications import Starlette
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.routing import Mount, Route
from mcp.server import Server
import uvicorn
import logging
import os
import sys
from mysql.connector import connect, Error
from mcp.types import Resource, Tool, TextContent, ResourceTemplate
from pydantic import AnyUrl
from dotenv import load_dotenv
import asyncio
import sqlparse
from pathlib import Path
from typing import Any, List, Optional, Dict
from datetime import datetime, timedelta
import pytz
import re
import subprocess

# Lazy imports for faster startup
def _import_alibaba_modules():
    global polardb20170801Client, CredentialClient, open_api_models, polardb_20170801_models
    global util_models, UtilClient, Vpc20160428Client, vpc_20160428_models
    global DAS20200116Client, das20200116_models
    
    from alibabacloud_polardb20170801.client import Client as polardb20170801Client
    from alibabacloud_credentials.client import Client as CredentialClient
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_polardb20170801 import models as polardb_20170801_models
    from alibabacloud_tea_util import models as util_models
    from alibabacloud_tea_util.client import Client as UtilClient
    from alibabacloud_vpc20160428.client import Client as Vpc20160428Client
    from alibabacloud_vpc20160428 import models as vpc_20160428_models
    from alibabacloud_das20200116.client import Client as DAS20200116Client
    from alibabacloud_das20200116 import models as das20200116_models

# Initialize as None - will be loaded when needed
polardb20170801Client = None
CredentialClient = None
open_api_models = None
polardb_20170801_models = None
util_models = None
UtilClient = None
Vpc20160428Client = None
vpc_20160428_models = None
DAS20200116Client = None
das20200116_models = None

class SmartMCPDispatcher:
    """Intelligent dispatcher that recognizes user intent and calls appropriate tools directly"""
    
    def __init__(self):
        self.intent_patterns = [
            # Restart operations
            {
                "pattern": r"重启节点?\s*(pi-[a-zA-Z0-9]+)",
                "intent": "restart_node",
                "tool": "polardb_restart_db_node",
                "extract_params": self._extract_node_restart_params
            },
            {
                "pattern": r"restart\s+node\s+(pi-[a-zA-Z0-9]+)",
                "intent": "restart_node", 
                "tool": "polardb_restart_db_node",
                "extract_params": self._extract_node_restart_params
            },
            
            # Performance operations
            {
                "pattern": r"获取集群\s*(pc-[a-zA-Z0-9]+)\s*的?性能",
                "intent": "cluster_performance",
                "tool": "polardb_describe_db_cluster_performance", 
                "extract_params": self._extract_cluster_performance_params
            },
            {
                "pattern": r"get\s+performance\s+for\s+cluster\s+(pc-[a-zA-Z0-9]+)",
                "intent": "cluster_performance",
                "tool": "polardb_describe_db_cluster_performance",
                "extract_params": self._extract_cluster_performance_params
            },
            
            # Node performance operations
            {
                "pattern": r"获取节点\s*(pi-[a-zA-Z0-9]+)\s*的?性能",
                "intent": "node_performance",
                "tool": "polardb_describe_db_node_performance",
                "extract_params": self._extract_node_performance_params
            },
            {
                "pattern": r"get\s+performance\s+for\s+node\s+(pi-[a-zA-Z0-9]+)",
                "intent": "node_performance", 
                "tool": "polardb_describe_db_node_performance",
                "extract_params": self._extract_node_performance_params
            },
            
            # Cluster information
            {
                "pattern": r"查看集群\s*(pc-[a-zA-Z0-9]+)\s*信息",
                "intent": "cluster_info",
                "tool": "polardb_describe_db_cluster",
                "extract_params": self._extract_cluster_info_params
            },
            {
                "pattern": r"describe\s+cluster\s+(pc-[a-zA-Z0-9]+)",
                "intent": "cluster_info",
                "tool": "polardb_describe_db_cluster", 
                "extract_params": self._extract_cluster_info_params
            },
            
            # Whitelist operations
            {
                "pattern": r"查看集群\s*(pc-[a-zA-Z0-9]+)\s*的?白名单",
                "intent": "view_whitelist",
                "tool": "polardb_describe_db_cluster_access_whitelist",
                "extract_params": self._extract_whitelist_params
            },
            {
                "pattern": r"show\s+whitelist\s+for\s+cluster\s+(pc-[a-zA-Z0-9]+)",
                "intent": "view_whitelist",
                "tool": "polardb_describe_db_cluster_access_whitelist",
                "extract_params": self._extract_whitelist_params
            },
            
            # Extract node IDs from clusters
            {
                "pattern": r"提取集群\s*(pc-[a-zA-Z0-9]+)\s*的?节点",
                "intent": "extract_nodes",
                "tool": "polardb_extract_node_ids",
                "extract_params": self._extract_nodes_params
            },
            {
                "pattern": r"extract\s+nodes?\s+from\s+cluster\s+(pc-[a-zA-Z0-9]+)",
                "intent": "extract_nodes",
                "tool": "polardb_extract_node_ids", 
                "extract_params": self._extract_nodes_params
            }
        ]
    
    def parse_user_intent(self, user_query: str) -> Optional[Dict[str, Any]]:
        """Parse user query and return tool call if pattern matches"""
        user_query = user_query.strip()
        
        for pattern_config in self.intent_patterns:
            pattern = pattern_config["pattern"]
            match = re.search(pattern, user_query, re.IGNORECASE)
            
            if match:
                tool_name = pattern_config["tool"]
                extract_func = pattern_config["extract_params"]
                
                # Extract parameters using the specific function
                params = extract_func(match, user_query)
                
                return {
                    "intent": pattern_config["intent"],
                    "tool_name": tool_name,
                    "arguments": params,
                    "confidence": "high",
                    "matched_pattern": pattern,
                    "original_query": user_query
                }
        
        return None
    
    def _extract_node_restart_params(self, match: re.Match, query: str) -> Dict[str, Any]:
        """Extract parameters for node restart"""
        node_id = match.group(1)
        return {"dbnode_id": node_id}
    
    def _extract_cluster_performance_params(self, match: re.Match, query: str) -> Dict[str, Any]:
        """Extract parameters for cluster performance with smart defaults"""
        cluster_id = match.group(1)
        
        # Smart time range - default to last hour
        from datetime import datetime, timedelta
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        
        return {
            "db_cluster_id": cluster_id,
            "start_time": start_time.strftime('%Y-%m-%dT%H:%MZ'),
            "end_time": end_time.strftime('%Y-%m-%dT%H:%MZ'),
            "key": "PolarDBDiskUsage, PolarDBCPU, PolarDBMemory, PolarDBConnections, PolarDBIOSTAT"
        }
    
    def _extract_node_performance_params(self, match: re.Match, query: str) -> Dict[str, Any]:
        """Extract parameters for node performance with smart defaults"""
        node_id = match.group(1)
        
        # Smart time range - default to last hour
        from datetime import datetime, timedelta
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)
        
        return {
            "dbnode_id": node_id,
            "start_time": start_time.strftime('%Y-%m-%dT%H:%MZ'), 
            "end_time": end_time.strftime('%Y-%m-%dT%H:%MZ'),
            "key": "PolarDBDiskUsage, PolarDBCPU, PolarDBMemory, PolarDBConnections, PolarDBIOSTAT"
        }
    
    def _extract_cluster_info_params(self, match: re.Match, query: str) -> Dict[str, Any]:
        """Extract parameters for cluster information"""
        cluster_id = match.group(1)
        return {"db_cluster_id": cluster_id}
    
    def _extract_whitelist_params(self, match: re.Match, query: str) -> Dict[str, Any]:
        """Extract parameters for whitelist viewing"""
        cluster_id = match.group(1)
        return {"dbcluster_id": cluster_id}
    
    def _extract_nodes_params(self, match: re.Match, query: str) -> Dict[str, Any]:
        """Extract parameters for node extraction"""
        cluster_id = match.group(1)
        return {"db_cluster_id": cluster_id}


# Add a new tool to handle smart queries
def polardb_smart_query(arguments: dict) -> list[TextContent]:
    """Smart query dispatcher that understands natural language intent"""
    query = arguments.get("query", "")
    
    if not query:
        return [TextContent(type="text", text="❌ 缺少查询参数：需要提供 'query' 参数")]
    
    # Initialize dispatcher
    dispatcher = SmartMCPDispatcher()
    
    # Parse user intent
    intent_result = dispatcher.parse_user_intent(query)
    
    if not intent_result:
        # No pattern matched - provide helpful guidance
        return [TextContent(type="text", text=f"""❓ 无法识别查询意图: "{query}"

🤖 **支持的智能查询格式**:

**节点操作**:
• "重启节点 pi-xxxxx" - 重启指定节点
• "获取节点 pi-xxxxx 的性能" - 获取节点性能数据

**集群操作**:
• "获取集群 pc-xxxxx 的性能" - 获取集群性能数据  
• "查看集群 pc-xxxxx 信息" - 查看集群详细信息
• "查看集群 pc-xxxxx 的白名单" - 查看访问白名单
• "提取集群 pc-xxxxx 的节点" - 提取集群中的节点ID

**English formats**:
• "restart node pi-xxxxx"
• "get performance for cluster pc-xxxxx"
• "describe cluster pc-xxxxx"

💡 **提示**: 请提供具体的节点ID (pi-xxxxx) 或集群ID (pc-xxxxx)
""")]
    
    # Execute the identified tool
    tool_name = intent_result["tool_name"]
    tool_arguments = intent_result["arguments"]
    
    try:
        # Get the actual tool function
        if tool_name == "polardb_restart_db_node":
            result = polardb_restart_db_node(tool_arguments)
        elif tool_name == "polardb_describe_db_cluster_performance":
            result = polardb_describe_db_cluster_performance(tool_arguments)
        elif tool_name == "polardb_describe_db_node_performance":
            result = polardb_describe_db_node_performance(tool_arguments)
        elif tool_name == "polardb_describe_db_cluster":
            result = polardb_describe_db_cluster(tool_arguments)
        elif tool_name == "polardb_describe_db_cluster_access_whitelist":
            result = polardb_describe_db_cluster_access_whitelist(tool_arguments)
        elif tool_name == "polardb_extract_node_ids":
            result = polardb_extract_node_ids(tool_arguments)
        else:
            return [TextContent(type="text", text=f"❌ 未找到工具: {tool_name}")]
        
        # Add smart query context to the result
        smart_context = [
            TextContent(type="text", text=f"""🤖 **智能查询已执行**

📝 **原始查询**: {query}
🎯 **识别意图**: {intent_result['intent']}
🔧 **调用工具**: {tool_name}
📋 **使用参数**: {tool_arguments}
⚡ **执行结果**:

""")
        ]
        
        return smart_context + result
        
    except Exception as e:
        logger.error(f"Error executing smart query tool {tool_name}: {str(e)}")
        return [TextContent(type="text", text=f"❌ 执行智能查询失败: {str(e)}")]


# The smart query tool is defined within the list_tools() function to avoid duplication

# PolarDB MySQL有效性能指标列表
VALID_POLARDB_MYSQL_METRICS = {
    # Core performance metrics (default set)
    "PolarDBDiskUsage": "磁盘使用情况",
    "PolarDBCPU": "CPU使用率", 
    "PolarDBMemory": "内存使用率",
    "PolarDBConnections": "数据库连接数",
    "PolarDBIOSTAT": "IOPS统计",
    
    # Extended performance metrics
    "PolarDBQPSTPS": "QPS/TPS查询统计",
    "PolarDBNetworkTraffic": "网络流量",
    "PolarDBInnoDBBufferRatio": "InnoDB缓冲池命中率",
    "PolarDBInnoDBDataReadWrite": "InnoDB数据读写",
    "PolarDBInnoDBBufferRequests": "InnoDB缓冲池请求",
    "PolarDBInnoDBLogWrites": "InnoDB日志写入",
    "PolarDBCOMDML": "DML操作统计",
    "PolarDBRowDML": "行级DML操作",
    "PolarDBReplicaLag": "副本延迟"
}

# PolarDB Proxy valid performance metrics list
VALID_POLARDB_PROXY_METRICS = {
    # Core proxy metrics (default set)
    "PolarProxy_CurrentConns": "当前连接数",
    "PolarProxy_DBConns": "数据库连接数", 
    "PolarProxy_DBActionOps": "数据库操作次数",
    
    # Extended proxy metrics (from the documentation)
    "PolarProxy_CPU": "代理CPU使用率",
    "PolarProxy_Memory": "代理内存使用率",
    "PolarProxy_NetworkIn": "网络输入流量",
    "PolarProxy_NetworkOut": "网络输出流量",
    "PolarProxy_QPS": "每秒查询数",
    "PolarProxy_TPS": "每秒事务数",
    "PolarProxy_AvgResponseTime": "平均响应时间",
    "PolarProxy_SlowQueries": "慢查询数量",
    "PolarProxy_ConnectionPool": "连接池使用情况",
    "PolarProxy_ThreadPool": "线程池使用情况"
}

# Default performance metrics (maximum 5 keys)
_BASE_PERFORMANCE_METRICS = "PolarDBDiskUsage, PolarDBCPU, PolarDBMemory, PolarDBConnections, PolarDBIOSTAT"
DEFAULT_CLUSTER_PERFORMANCE_METRICS = _BASE_PERFORMANCE_METRICS
DEFAULT_NODE_PERFORMANCE_METRICS = _BASE_PERFORMANCE_METRICS

DEFAULT_PROXY_PERFORMANCE_METRICS = "PolarProxy_CurrentConns,PolarProxy_DBConns,PolarProxy_DBActionOps"

def validate_proxy_performance_keys(key_string: str) -> tuple[str, list[str]]:
    """Validate and limit proxy performance keys to maximum 5"""
    warnings = []
    
    if not key_string or key_string.strip() == "":
        return "", ["❌ 代理性能指标key参数为必填项，不能为空"]
    
    # Split and clean metrics
    requested_metrics = [metric.strip() for metric in key_string.split(',') if metric.strip()]
    valid_metrics = []
    invalid_metrics = []
    
    # Validate each metric
    for metric in requested_metrics:
        if metric in VALID_POLARDB_PROXY_METRICS:
            valid_metrics.append(metric)
        else:
            invalid_metrics.append(metric)
    
    # Report invalid metrics
    if invalid_metrics:
        warnings.append(f"无效的代理性能指标已被移除: {', '.join(invalid_metrics)}")
        warnings.append(f"有效的PolarDB代理性能指标: {', '.join(VALID_POLARDB_PROXY_METRICS.keys())}")
    
    # Limit to maximum 5 metrics
    if len(valid_metrics) > 5:
        removed_metrics = valid_metrics[5:]
        valid_metrics = valid_metrics[:5]
        warnings.append(f"代理性能指标限制为5个，已移除: {', '.join(removed_metrics)}")
    
    # Return error if no valid metrics
    if not valid_metrics:
        return "", ["❌ 没有有效的代理性能指标，请提供正确的指标名称"]
    
    return ",".join(valid_metrics), warnings

def analyze_proxy_performance_data(performance_data: dict, time_range: dict) -> dict:
    """Analyze proxy performance data and provide insights"""
    analysis = {
        "summary": {
            "cluster_id": performance_data.get("cluster_id", "Unknown"),
            "time_range": f"{time_range.get('start', 'Unknown')} to {time_range.get('end', 'Unknown')}",
            "total_metrics": 0,
            "analysis_time": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        },
        "metrics_analysis": {},
        "performance_insights": [],
        "recommendations": [],
        "alerts": []
    }
    
    try:
        metrics = performance_data.get("metrics", [])
        analysis["summary"]["total_metrics"] = len(metrics)
        
        # Analyze each metric
        for metric in metrics:
            measurement = metric.get("measurement", "")
            metric_name = metric.get("metric_name", "")
            points = metric.get("points", [])
            
            if not points:
                continue
                
            # Extract numeric values
            values = []
            for point in points:
                try:
                    value = float(point.get("value", 0))
                    values.append(value)
                except (ValueError, TypeError):
                    continue
            
            if not values:
                continue
                
            # Statistical analysis
            metric_stats = {
                "measurement": measurement,
                "metric_name": metric_name,
                "data_points": len(values),
                "average": round(sum(values) / len(values), 2),
                "minimum": round(min(values), 2),
                "maximum": round(max(values), 2),
                "latest": round(values[-1], 2),
                "trend": analyze_trend_direction(values),
                "variation": round((max(values) - min(values)), 2),
                "stability": "stable" if (max(values) - min(values)) / max(max(values), 1) < 0.1 else "variable"
            }
            
            # Add metric-specific analysis
            friendly_name = get_proxy_metric_friendly_name(measurement, metric_name)
            analysis["metrics_analysis"][friendly_name] = metric_stats
            
            # Generate specific insights
            insights = generate_proxy_metric_insights(measurement, metric_name, metric_stats)
            analysis["performance_insights"].extend(insights)
            
            # Generate alerts if needed
            alerts = generate_proxy_metric_alerts(measurement, metric_name, metric_stats)
            analysis["alerts"].extend(alerts)
        
        # Generate overall recommendations
        analysis["recommendations"] = generate_proxy_recommendations(analysis["metrics_analysis"])
        
        return analysis
        
    except Exception as e:
        logger.error(f"Error analyzing proxy performance data: {e}")
        analysis["error"] = f"Analysis failed: {str(e)}"
        return analysis

def get_proxy_metric_friendly_name(measurement: str, metric_name: str) -> str:
    """Get friendly names for proxy metrics"""
    name_mapping = {
        # Connection metrics
        ("PolarProxy_CurrentConns", "service_current_connections"): "当前连接数",
        ("PolarProxy_DBConns", "db_connections"): "数据库连接数",
        ("PolarProxy_ConnectionPool", "pool_usage"): "连接池使用率(%)",
        
        # Operation metrics
        ("PolarProxy_DBActionOps", "db_action_operations"): "数据库操作次数",
        ("PolarProxy_QPS", "queries_per_second"): "每秒查询数(QPS)",
        ("PolarProxy_TPS", "transactions_per_second"): "每秒事务数(TPS)",
        
        # Performance metrics
        ("PolarProxy_CPU", "cpu_usage"): "代理CPU使用率(%)",
        ("PolarProxy_Memory", "memory_usage"): "代理内存使用率(%)",
        ("PolarProxy_AvgResponseTime", "avg_response_time"): "平均响应时间(ms)",
        ("PolarProxy_SlowQueries", "slow_query_count"): "慢查询数量",
        
        # Network metrics
        ("PolarProxy_NetworkIn", "network_in_bytes"): "网络输入流量(MB/s)",
        ("PolarProxy_NetworkOut", "network_out_bytes"): "网络输出流量(MB/s)",
        
        # Thread metrics
        ("PolarProxy_ThreadPool", "thread_pool_usage"): "线程池使用率(%)",
    }
    
    return name_mapping.get((measurement, metric_name), f"{measurement}-{metric_name}")

def generate_proxy_metric_insights(measurement: str, metric_name: str, stats: dict) -> list:
    """Generate insights for specific proxy metrics"""
    insights = []
    
    try:
        avg = stats["average"]
        max_val = stats["maximum"]
        trend = stats["trend"]
        
        # Connection insights
        if measurement == "PolarProxy_CurrentConns":
            if avg > 1000:
                insights.append(f"🔴 高并发连接: 平均当前连接数 {avg}，峰值 {max_val}")
            elif avg > 100:
                insights.append(f"🟡 中等并发连接: 平均当前连接数 {avg}")
            else:
                insights.append(f"🟢 正常连接数: 平均当前连接数 {avg}")
                
            if trend == "increasing":
                insights.append("📈 当前连接数呈上升趋势，注意监控连接池")
        
        # Database connection insights
        elif measurement == "PolarProxy_DBConns":
            if avg > 500:
                insights.append(f"🔴 数据库连接数偏高: 平均 {avg} 个连接")
            elif avg > 100:
                insights.append(f"🟡 数据库连接数中等: 平均 {avg} 个连接")
            else:
                insights.append(f"🟢 数据库连接数正常: 平均 {avg} 个连接")
        
        # Operation insights
        elif measurement == "PolarProxy_DBActionOps":
            if avg > 10000:
                insights.append(f"📊 高操作频率: 平均每秒 {avg} 次数据库操作")
            elif avg < 10:
                insights.append(f"📊 低操作频率: 平均每秒 {avg} 次数据库操作")
            
            if trend == "increasing":
                insights.append("📈 数据库操作频率持续增长")
        
        # Performance insights
        elif measurement == "PolarProxy_CPU" and avg > 80:
            insights.append(f"⚠️ 代理CPU使用率过高: 平均 {avg}%")
        elif measurement == "PolarProxy_Memory" and avg > 80:
            insights.append(f"⚠️ 代理内存使用率过高: 平均 {avg}%")
        elif measurement == "PolarProxy_AvgResponseTime" and avg > 100:
            insights.append(f"⚠️ 平均响应时间较长: {avg} ms")
        elif measurement == "PolarProxy_SlowQueries" and avg > 0:
            insights.append(f"🐌 检测到慢查询: 平均每秒 {avg} 个慢查询")
        
    except Exception as e:
        logger.warning(f"Error generating proxy insights for {measurement}-{metric_name}: {e}")
    
    return insights

def generate_proxy_metric_alerts(measurement: str, metric_name: str, stats: dict) -> list:
    """Generate alerts for critical proxy metrics"""
    alerts = []
    
    try:
        avg = stats["average"]
        max_val = stats["maximum"]
        
        # Critical connection alerts
        if measurement == "PolarProxy_CurrentConns":
            if max_val > 2000:
                alerts.append({
                    "level": "critical",
                    "metric": "当前连接数",
                    "message": f"当前连接数峰值达到 {max_val}，可能影响性能",
                    "recommendation": "考虑连接池优化或扩容代理资源"
                })
        
        # Critical CPU alert
        elif measurement == "PolarProxy_CPU":
            if max_val > 90:
                alerts.append({
                    "level": "critical", 
                    "metric": "代理CPU使用率",
                    "message": f"代理CPU使用率峰值达到 {max_val}%",
                    "recommendation": "考虑增加代理实例或优化查询"
                })
        
        # Memory alert
        elif measurement == "PolarProxy_Memory":
            if avg > 85:
                alerts.append({
                    "level": "warning",
                    "metric": "代理内存使用率", 
                    "message": f"代理内存使用率平均 {avg}%，接近上限",
                    "recommendation": "监控内存使用，考虑增加代理内存资源"
                })
        
        # Response time alert
        elif measurement == "PolarProxy_AvgResponseTime":
            if avg > 200:
                alerts.append({
                    "level": "warning",
                    "metric": "平均响应时间",
                    "message": f"平均响应时间 {avg} ms，较慢",
                    "recommendation": "检查代理配置和后端数据库性能"
                })
                
    except Exception as e:
        logger.warning(f"Error generating proxy alerts for {measurement}-{metric_name}: {e}")
    
    return alerts

def generate_proxy_recommendations(metrics_analysis: dict) -> list:
    """Generate overall proxy recommendations"""
    recommendations = []
    
    try:
        # Check for high connection usage
        high_connections = any("连接数" in k and v["average"] > 1000 for k, v in metrics_analysis.items())
        high_operations = any("操作次数" in k and v["average"] > 10000 for k, v in metrics_analysis.items())
        high_cpu = any("CPU" in k and v["average"] > 70 for k, v in metrics_analysis.items())
        high_memory = any("内存" in k and v["average"] > 75 for k, v in metrics_analysis.items())
        
        if high_connections and high_operations:
            recommendations.append("🔧 建议优化连接池配置：高并发和高操作频率同时出现")
        elif high_connections:
            recommendations.append("🔧 建议优化连接管理或增加代理实例数量")
        
        if high_cpu and high_memory:
            recommendations.append("🔧 建议进行代理扩容：CPU和内存使用率都偏高")
        elif high_cpu:
            recommendations.append("🔧 建议优化查询性能或增加代理CPU资源")
        elif high_memory:
            recommendations.append("🔧 建议增加代理内存资源或优化缓存配置")
        
        # Check for slow queries
        slow_queries = any("慢查询" in k and v["average"] > 0 for k, v in metrics_analysis.items())
        if slow_queries:
            recommendations.append("🐌 建议优化慢查询和索引配置")
        
        # General recommendations
        if len(recommendations) == 0:
            recommendations.append("✅ 代理性能指标正常，继续监控")
        else:
            recommendations.append("📊 建议定期监控代理性能趋势，制定容量规划")
            
    except Exception as e:
        logger.warning(f"Error generating proxy recommendations: {e}")
        recommendations.append("📊 建议定期监控代理性能指标")
    
    return recommendations

def validate_node_performance_keys(key_string: str) -> tuple[str, list[str]]:
    """Validate and limit node performance keys to maximum 5, same as cluster"""
    warnings = []
    
    if not key_string or key_string.strip() == "":
        warnings.append("使用默认节点性能指标 (5个核心指标)")
        return DEFAULT_NODE_PERFORMANCE_METRICS, warnings
    
    # Use the same validation logic as cluster
    return validate_cluster_performance_keys(key_string)

def convert_to_beijing_time(time_str: str) -> str:
    """Convert local time to Beijing time (UTC+8) and format for API"""
    try:
        # Parse the input time string
        if 'T' in time_str and 'Z' in time_str:
            # ISO format with Z (UTC)
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            # Convert to Beijing time
            beijing_tz = pytz.timezone('Asia/Shanghai')
            dt_beijing = dt.astimezone(beijing_tz)
        elif 'T' in time_str:
            # ISO format without timezone info - assume local
            dt = datetime.fromisoformat(time_str)
            # Assume it's local time and convert to Beijing
            local_tz = pytz.timezone('Asia/Shanghai')  # or detect system timezone
            dt_local = local_tz.localize(dt)
            dt_beijing = dt_local
        else:
            # Try to parse other formats
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            beijing_tz = pytz.timezone('Asia/Shanghai')
            dt_beijing = beijing_tz.localize(dt)
        
        # Format for PolarDB API (UTC format but adjusted to Beijing time)
        # PolarDB expects UTC format, so we convert Beijing time back to UTC for API
        dt_utc = dt_beijing.astimezone(pytz.UTC)
        return dt_utc.strftime('%Y-%m-%dT%H:%MZ')
        
    except Exception as e:
        logger.warning(f"Time conversion failed for '{time_str}': {e}")
        # Fallback: return as-is if conversion fails
        return time_str

def validate_cluster_performance_keys(key_string: str) -> tuple[str, list[str]]:
    """Validate and limit performance keys to maximum 5, with Beijing time consideration"""
    warnings = []
    
    if not key_string or key_string.strip() == "":
        warnings.append("使用默认性能指标 (5个核心指标)")
        return DEFAULT_CLUSTER_PERFORMANCE_METRICS, warnings
    
    # Split and clean metrics
    requested_metrics = [metric.strip() for metric in key_string.split(',') if metric.strip()]
    valid_metrics = []
    invalid_metrics = []
    
    # Validate each metric
    for metric in requested_metrics:
        if metric in VALID_POLARDB_MYSQL_METRICS:
            valid_metrics.append(metric)
        else:
            invalid_metrics.append(metric)
    
    # Report invalid metrics
    if invalid_metrics:
        warnings.append(f"无效的性能指标已被移除: {', '.join(invalid_metrics)}")
        warnings.append(f"有效的PolarDB性能指标: {', '.join(VALID_POLARDB_MYSQL_METRICS.keys())}")
    
    # Limit to maximum 5 metrics
    if len(valid_metrics) > 5:
        removed_metrics = valid_metrics[5:]
        valid_metrics = valid_metrics[:5]
        warnings.append(f"性能指标限制为5个，已移除: {', '.join(removed_metrics)}")
    
    # Use defaults if no valid metrics
    if not valid_metrics:
        warnings.append("没有有效的性能指标，使用默认指标")
        return DEFAULT_CLUSTER_PERFORMANCE_METRICS, warnings
    
    return ", ".join(valid_metrics), warnings

# Requirements installation removed - packages should be installed via pip/uv during package installation

# Import check - packages should be installed via pip/uv
try:
    import alibabacloud_polardb20170801
    print("Successfully imported alibabacloud_polardb20170801", file=sys.stderr)
except ImportError as e:
    print(f"Import error: {e}", file=sys.stderr)
    sys.exit(1)


class PromptManager:
    """Intelligent prompt management for MCP server responses"""
    
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir)
        self.ensure_prompt_dir()
        self.conversation_context = {}
        self.error_history = []
        
        # Core prompt sections
        self.sections = {
            "base_instructions": """
You are a PolarDB Management Assistant integrated with an MCP server. 
Provide accurate, helpful guidance for PolarDB operations.
""",
            "cluster_parsing": """
CRITICAL: HOW TO PARSE CLUSTER RESPONSES TO FIND NODES
When parsing cluster information:
1. Look at EACH cluster in the 'DBCluster' array
2. For each cluster, examine 'DBNodes' -> 'DBNode' array  
3. Check each 'DBNodeId' in that array
4. Node IDs (pi-xxx) are NOT related to cluster IDs (pc-xxx) by simple prefix replacement

EXAMPLE: Node 'pi-6nnp9h5z59l323jpf' belongs to cluster 'pc-6nnxi02yw7ma1fopw' (completely different!)
""",
            "region_search": """
COMPREHENSIVE REGION SEARCH STRATEGY:
1. First get all available regions using polardb_describe_regions
2. Search systematically through ALL regions, including:
   - cn-hangzhou (Hangzhou)
   - cn-shanghai (Shanghai) 
   - cn-beijing (Beijing)
   - cn-shenzhen (Shenzhen)
   - And any other regions returned by the API
3. Never give up after searching only 2-3 regions
""",
            "time_format": """
CRITICAL TIME FORMAT REQUIREMENTS:
- Use format "YYYY-MM-DDTHH:MMZ" (NO SECONDS)
- Example: "2025-06-05T04:25Z" (correct) vs "2025-06-05T04:25:00Z" (incorrect)
- Always use UTC timezone (Z suffix)
""",
            "performance_analysis": """
PERFORMANCE DATA ANALYSIS:
- For performance metrics "key" parameter: Use spaces after commas
- Example: "PolarDBDiskUsage, PolarDBCPU, PolarDBMemory" (correct)
- Use recent 1-hour time ranges for current data
- Handle zero values in calculations to avoid division by zero
""",
            "node_search_strategy": """
CRITICAL NODE SEARCH AND IDENTIFICATION STRATEGY:
When users ask to find nodes or get node information:

1. NEVER assume node IDs from cluster IDs - they are completely unrelated
2. ALWAYS use systematic search approach:
   - First search for clusters using polardb_describe_db_clusters
   - Then use polardb_extract_node_ids to get actual node IDs from found clusters
   - Use the extracted node IDs for subsequent operations

3. NODE ID EXTRACTION PRIORITY:
   - Use polardb_extract_node_ids tool for reliable node discovery
   - This tool provides clean, structured output with both reader and writer nodes
   - It includes usage instructions for subsequent parameter queries

4. MULTI-REGION SEARCH PROTOCOL:
   - Search priority regions first: cn-hangzhou, cn-shanghai, cn-beijing  
   - If nodes not found in priority regions, expand search systematically
   - Never conclude "node not found" after checking only 1-2 regions

5. ERROR PREVENTION:
   - Always verify cluster-to-node relationships using extract_node_ids tool
   - Don't use pattern matching (pi-xxx from pc-xxx) - this is unreliable
   - Provide specific node IDs in user responses, not generic examples

EXAMPLE WORKFLOW:
User: "Find reader nodes"
→ Search clusters in priority regions
→ Use extract_node_ids on found clusters  
→ Report actual reader node IDs with cluster associations
→ Provide ready-to-use parameter query examples
""",
            "error_handling": """
ERROR HANDLING PROCEDURES:
- Never assume cluster IDs from node IDs
- Always search ALL regions systematically  
- Parse API responses carefully to extract actual data
- Provide specific error messages with actionable solutions
- Check network connectivity for timeout issues
"""
        }
        
        # Initialize prompt files
        self.save_default_prompts()
    
    def ensure_prompt_dir(self):
        """Create prompts directory if it doesn't exist"""
        self.prompts_dir.mkdir(exist_ok=True)
        for subdir in ["base", "database", "performance", "examples", "context_specific"]:
            (self.prompts_dir / subdir).mkdir(exist_ok=True)
    
    def save_default_prompts(self):
        """Save default prompt sections to files"""
        for section_name, content in self.sections.items():
            file_path = self.prompts_dir / "base" / f"{section_name}.txt"
            if not file_path.exists():
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content.strip())
    
    def load_prompt_section(self, section_name: str, category: str = "base") -> str:
        """Load a prompt section from file"""
        file_path = self.prompts_dir / category / f"{section_name}.txt"
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        return self.sections.get(section_name, "")
    
    def update_conversation_context(self, tool_name: str, arguments: dict, result: Any):
        """Update conversation context with tool usage"""
        context_key = f"{tool_name}_{datetime.now().isoformat()}"
        self.conversation_context[context_key] = {
            "tool": tool_name,
            "arguments": arguments,
            "timestamp": datetime.now().isoformat(),
            "success": "error" not in str(result).lower() and "no polardb clusters found" not in str(result).lower()
        }
        
        # Keep only last 10 interactions
        if len(self.conversation_context) > 10:
            oldest_key = min(self.conversation_context.keys())
            del self.conversation_context[oldest_key]
    
    def add_error(self, error_msg: str, tool_name: str = None):
        """Track errors for prompt enhancement"""
        self.error_history.append({
            "error": error_msg,
            "tool": tool_name,
            "timestamp": datetime.now().isoformat()
        })
        
        # Keep only last 5 errors
        if len(self.error_history) > 5:
            self.error_history.pop(0)
    
    def determine_context(self, tool_name: str, arguments: dict) -> str:
        """Determine what type of guidance is needed"""
        tool_lower = tool_name.lower()
        
        if "performance" in tool_lower:
            return "performance"
        elif "clusters" in tool_lower or "cluster" in tool_lower:
            return "cluster_search"
        elif "regions" in tool_lower:
            return "region_search"
        elif "node" in tool_lower:
            return "node_operations"
        elif "create" in tool_lower:
            return "cluster_creation"
        elif "node" in tool_lower or "find" in arguments.get("query", "").lower():
            return "node_search"
        else:
            return "general"
    
    def generate_contextual_guidance(self, tool_name: str, arguments: dict, 
                                   previous_errors: List[str] = None) -> str:
        """Generate contextual guidance based on tool and context"""
        
        context_type = self.determine_context(tool_name, arguments)
        guidance_parts = [self.load_prompt_section("base_instructions")]
        
        # Add context-specific guidance
        if context_type == "performance":
            guidance_parts.extend([
                self.load_prompt_section("time_format"),
                self.load_prompt_section("performance_analysis")
            ])
        elif context_type == "cluster_search":
            guidance_parts.extend([
                self.load_prompt_section("cluster_parsing"),
                self.load_prompt_section("region_search")
            ])
        elif context_type == "node_operations":
            guidance_parts.extend([
                self.load_prompt_section("cluster_parsing"),
                self.load_prompt_section("region_search"),
                "REMEMBER: Node IDs (pi-xxx) do NOT correspond to cluster IDs (pc-xxx)"
            ])
        elif context_type == "node_search":
            guidance_parts.extend([
                self.load_prompt_section("node_search_strategy"),
                self.load_prompt_section("region_search"),
                "CRITICAL: Use polardb_extract_node_ids tool for reliable node discovery"
            ])
        elif context_type == "region_search":
            guidance_parts.append(self.load_prompt_section("region_search"))
        
        # Add error-specific guidance
        if previous_errors or self.error_history:
            guidance_parts.append(self.load_prompt_section("error_handling"))
            
            error_guidance = self.generate_error_specific_guidance(previous_errors)
            if error_guidance:
                guidance_parts.append(error_guidance)
        
        # Add recent context if relevant
        recent_context = self.get_recent_context_guidance(tool_name)
        if recent_context:
            guidance_parts.append(recent_context)
        
        return "\n\n".join(filter(None, guidance_parts))
    
    def generate_error_specific_guidance(self, errors: List[str]) -> str:
        """Generate specific guidance based on errors"""
        if not errors and not self.error_history:
            return ""
        
        all_errors = (errors or []) + [e["error"] for e in self.error_history]
        guidance = ["BASED ON RECENT ERRORS:"]
        
        for error in all_errors:
            error_lower = error.lower()
            if "not found" in error_lower and ("cluster" in error_lower or "node" in error_lower):
                guidance.append("- Search ALL regions systematically before concluding cluster/node doesn't exist")
            elif "division by zero" in error_lower:
                guidance.append("- Handle zero values in trend calculations carefully")
            elif "json" in error_lower or "parse" in error_lower:
                guidance.append("- Validate data structure before parsing")
            elif "timeout" in error_lower or "connection" in error_lower:
                guidance.append("- Check network connectivity and increase timeout values")
            elif "invalid" in error_lower and "time" in error_lower:
                guidance.append("- Use correct time format: YYYY-MM-DDTHH:MMZ (no seconds)")
        
        return "\n".join(guidance) if len(guidance) > 1 else ""
    
    def get_recent_context_guidance(self, current_tool: str) -> str:
        """Get guidance based on recent tool usage patterns"""
        if not self.conversation_context:
            return ""
        
        recent_tools = [ctx["tool"] for ctx in list(self.conversation_context.values())[-3:]]
        
        # Pattern: If user is searching for nodes across regions
        if ("describe_db_clusters" in " ".join(recent_tools) and 
            "performance" in current_tool.lower()):
            return "CONTEXT: Since you've been searching clusters, ensure you use the correct cluster ID found in the search results."
        
        # Pattern: Multiple failed cluster searches
        failed_searches = sum(1 for ctx in self.conversation_context.values() 
                            if "clusters" in ctx["tool"] and not ctx["success"])
        if failed_searches >= 2:
            return "CONTEXT: Multiple cluster searches failed. Consider checking different regions or verifying cluster IDs."
        
        return ""

# Initialize prompt manager globally
prompt_manager = PromptManager()

def enhanced_tool_call(tool_func):
    """Decorator to add intelligent guidance to tool responses"""
    def wrapper(arguments: dict = None) -> List[TextContent]:
        arguments = arguments or {}
        tool_name = tool_func.__name__
        
        try:
            # Execute the original tool
            result = tool_func(arguments)
            
            # Update conversation context
            prompt_manager.update_conversation_context(tool_name, arguments, result)
            
            # Check if we should add guidance
            if should_add_guidance(tool_name, arguments, result):
                guidance = prompt_manager.generate_contextual_guidance(
                    tool_name, arguments, get_recent_errors(result)
                )
                
                # Add guidance to the response
                if guidance and result:
                    enhanced_result = result + [
                        TextContent(
                            type="text", 
                            text=f"\n\n💡 INTELLIGENT GUIDANCE:\n{guidance}"
                        )
                    ]
                    return enhanced_result
            
            return result
            
        except Exception as e:
            # Track error
            prompt_manager.add_error(str(e), tool_name)
            
            # Generate error-specific guidance
            error_guidance = prompt_manager.generate_contextual_guidance(
                tool_name, arguments, [str(e)]
            )
            
            error_response = [
                TextContent(type="text", text=f"Error in {tool_name}: {str(e)}"),
                TextContent(type="text", text=f"\n💡 GUIDANCE:\n{error_guidance}")
            ]
            
            return error_response
    
    return wrapper

def should_add_guidance(tool_name: str, arguments: dict, result: List[TextContent]) -> bool:
    """Determine if guidance should be added to the response"""
    
    # Add guidance for complex operations
    complex_tools = [
        "polardb_describe_db_clusters",
        "polardb_describe_db_node_performance", 
        "polardb_create_cluster",
        "polardb_describe_db_cluster"
        "polardb_extract_node_ids"
    ]
    
    if tool_name in complex_tools:
        return True
    
    # Add guidance if result contains errors or "not found"
    if result and any("error" in str(content).lower() or "not found" in str(content).lower() 
                     for content in result):
        return True
    
    # Add guidance for first-time users (no conversation context)
    if not prompt_manager.conversation_context:
        return True
    
    return False

def get_recent_errors(result: List[TextContent]) -> List[str]:
    """Extract error messages from result"""
    errors = []
    if result:
        for content in result:
            text = str(content)
            if "error" in text.lower() or "not found" in text.lower():
                errors.append(text)
    return errors

# Enhanced versions of key tools
@enhanced_tool_call
def enhanced_polardb_describe_db_clusters(arguments: dict) -> List[TextContent]:
    """Enhanced version with intelligent guidance using the updated parsing"""
    return polardb_describe_db_clusters(arguments)

@enhanced_tool_call  
def enhanced_polardb_describe_db_node_performance(arguments: dict) -> List[TextContent]:
    """Enhanced version with intelligent guidance"""
    return polardb_describe_db_node_performance(arguments)

@enhanced_tool_call
def enhanced_polardb_create_cluster(arguments: dict) -> List[TextContent]:
    """Enhanced version with intelligent guidance"""
    return polardb_create_cluster(arguments)

# New guidance tool
def polardb_get_guidance(arguments: dict) -> List[TextContent]:
    """Get contextual guidance for PolarDB operations"""
    
    operation_type = arguments.get("operation_type", "general")
    specific_context = arguments.get("context", "")
    
    # Generate appropriate guidance
    guidance = prompt_manager.generate_contextual_guidance(
        f"guidance_{operation_type}", 
        {"context": specific_context}
    )
    
    # Add recent context summary
    if prompt_manager.conversation_context:
        recent_summary = "\n\nRECENT OPERATIONS:\n"
        for ctx in list(prompt_manager.conversation_context.values())[-3:]:
            status = "✅" if ctx["success"] else "❌"
            recent_summary += f"{status} {ctx['tool']} at {ctx['timestamp'][:19]}\n"
        guidance += recent_summary
    
    return [TextContent(type="text", text=guidance)]

enable_write = False
enable_update = False
enable_insert = False
enable_ddl = False
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger("polardb-openapi-mcp-server")

def create_client():
    """
    Initialize the Client with the credentials from the environment variables.
    @return: polardb20170801Client
    """
    # Import modules when needed
    if polardb20170801Client is None:
        _import_alibaba_modules()
    
    # Load environment variables from .env file
    load_dotenv()

    # Retrieve Alibaba Cloud Access Key and Secret from environment variables
    access_key_id = os.getenv('ALIBABA_CLOUD_ACCESS_KEY_ID')
    access_key_secret = os.getenv('ALIBABA_CLOUD_ACCESS_KEY_SECRET')

    if not access_key_id or not access_key_secret:
        print("Missing Access Key ID or Access Key Secret.")
        return None

    # Create a Config object to store your credentials
    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id='cn-hangzhou'  # Update this with your region if needed
    )
    # Set the endpoint for the PolarDB API
    config.endpoint = 'polardb.aliyuncs.com'
    return polardb20170801Client(config)

def create_vpc_client():
    """
    Initialize the VPC Client with the credentials from the environment variables.
    @return: Vpc20160428Client
    """
    # Import modules when needed
    if Vpc20160428Client is None:
        _import_alibaba_modules()
    
    # Load environment variables from .env file
    load_dotenv()

    # Retrieve Alibaba Cloud Access Key and Secret from environment variables
    access_key_id = os.getenv('ALIBABA_CLOUD_ACCESS_KEY_ID')
    access_key_secret = os.getenv('ALIBABA_CLOUD_ACCESS_KEY_SECRET')

    if not access_key_id or not access_key_secret:
        print("Missing Access Key ID or Access Key Secret.")
        return None

    # Create a Config object to store your credentials
    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        region_id='cn-hangzhou'  # Update this with your region if needed
    )
    # Set the endpoint for the VPC API
    config.endpoint = 'vpc.cn-hangzhou.aliyuncs.com'
    return Vpc20160428Client(config)

def create_das_client():
    """
    Initialize the DAS Client with the credentials from the environment variables.
    @return: DAS20200116Client
    """
    # Import modules when needed
    if DAS20200116Client is None:
        _import_alibaba_modules()
    
    # Load environment variables from .env file
    load_dotenv()

    # Retrieve Alibaba Cloud Access Key and Secret from environment variables
    access_key_id = os.getenv('ALIBABA_CLOUD_ACCESS_KEY_ID')
    access_key_secret = os.getenv('ALIBABA_CLOUD_ACCESS_KEY_SECRET')

    if not access_key_id or not access_key_secret:
        print("Missing Access Key ID or Access Key Secret.")
        return None

    # Create a Config object to store your credentials
    config = open_api_models.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
    )
    # Set the endpoint for the DAS API
    config.endpoint = 'das.cn-shanghai.aliyuncs.com'
    return DAS20200116Client(config)

# Initialize server
app = Server("polardb-openapi-mcp-server")

@app.list_resources()
async def list_resources() -> list[Resource]:
    try:
        return [
            Resource(
                uri=f"polardb-mysql://regions",
                name="get_regions",
                description="List all available regions for Alibaba Cloud PolarDB",
                mimeType="text/plain"
            ),
            Resource(
                uri=f"polardb-mysql://clusters",
                name="get_clusters",
                description="List all PolarDB clusters across all regions",
                mimeType="text/plain"
            )
        ]
    except Exception as e:
        logger.error(f"Error listing resources: {str(e)}")
        raise

@app.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    return [
        ResourceTemplate(
            uriTemplate=f"polardb-mysql://{{region_id}}/clusters",
            name="region_clusters",
            description="get all PolarDB clusters in a specific region",
            mimeType="text/plain"
        ),
        ResourceTemplate(
            uriTemplate=f"polardb-mysql://classes/{{region_id}}/{{db_type}}",
            name="region_db_type_classes",
            description="get all PolarDB classes specifications for a specific region and database type",
            mimeType="text/plain"
        )
    ]

@app.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    """Read resource contents"""
    uri_str = str(uri)
    logger.info(f"Reading resource: {uri_str}")

    # Handle polardb-mysql:// URIs for PolarDB API resources
    if uri_str.startswith("polardb-mysql://"):
        prefix = "polardb-mysql://"
        parts = uri_str[len(prefix):].split('/')

        if len(parts) == 1 and parts[0] == "regions":
            # List all regions
            return await get_polardb_regions()

        elif len(parts) == 1 and parts[0] == "clusters":
            # List all clusters across all regions
            return await get_all_polardb_clusters()

        elif len(parts) == 2 and parts[1] == "clusters":
            # List clusters in a specific region
            region_id = parts[0]
            return await get_polardb_clusters(region_id)

        else:
            logger.error(f"Invalid URI: {uri_str}")
            raise ValueError(f"Invalid URI: {uri_str}")

    else:
        logger.error(f"Invalid URI scheme: {uri_str}")
        raise ValueError(f"Invalid URI scheme: {uri_str}")

# PolarDB API helper functions
async def get_polardb_regions() -> str:
    """Get all available PolarDB regions"""
    client = create_client()
    if not client:
        return "Failed to create PolarDB client. Please check your credentials."

    try:
        # Create the request model for DescribeRegions
        describe_regions_request = polardb_20170801_models.DescribeRegionsRequest()
        runtime = util_models.RuntimeOptions()

        # Call the API to get the regions list
        response = client.describe_regions_with_options(describe_regions_request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'regions') and response.body.regions:
            regions_info = []
            for region in response.body.regions.region:
                regions_info.append(f"{region.region_id}: {region.local_name}")

            return "\n".join(regions_info)
        else:
            return "No regions found or empty response"

    except Exception as e:
        logger.error(f"Error describing PolarDB regions: {str(e)}")
        return f"Error retrieving regions: {str(e)}"

async def get_polardb_clusters(region_id: str) -> str:
    """Get all PolarDB clusters in a specific region"""
    client = create_client()
    if not client:
        return "Failed to create PolarDB client. Please check your credentials."

    try:
        # Create request for describing DB clusters
        request = polardb_20170801_models.DescribeDBClustersRequest(
            region_id=region_id
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbclusters_with_options(request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'items') and response.body.items:
            clusters_info = []
            for cluster in response.body.items.db_cluster:
                cluster_info = (
                    f"Cluster ID: {cluster.db_cluster_id}\n"
                    f"Description: {cluster.db_cluster_description}\n"
                    f"Status: {cluster.db_cluster_status}\n"
                    f"Engine: {cluster.engine} {cluster.db_version}\n"
                    f"Created: {cluster.create_time}\n"
                    f"----------------------------------"
                )
                clusters_info.append(cluster_info)

            return "\n".join(clusters_info)
        else:
            return f"No PolarDB clusters found in region {region_id}"

    except Exception as e:
        logger.error(f"Error describing PolarDB clusters: {str(e)}")
        return f"Error retrieving clusters: {str(e)}"


def polardb_extract_node_ids(arguments: dict) -> list[TextContent]:
    """Extract node IDs from a PolarDB cluster - dedicated tool for reliable node ID retrieval"""
    db_cluster_id = arguments.get("db_cluster_id")
    node_type = arguments.get("node_type", "all")  # "reader", "writer", or "all"
    
    if not db_cluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client")]

    try:
        # Create request for describing a specific DB cluster
        request = polardb_20170801_models.DescribeDBClusterAttributeRequest(
            dbcluster_id=db_cluster_id
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbcluster_attribute_with_options(request, runtime)
        response_dict = response.to_map()
        
        if not response_dict or 'body' not in response_dict:
            return [TextContent(type="text", text=f"No response for cluster {db_cluster_id}")]
        
        body = response_dict['body']
        db_nodes = body.get('DBNodes', [])
        
        if not db_nodes:
            return [TextContent(type="text", text=f"No nodes found in cluster {db_cluster_id}")]
        
        # Extract nodes by role
        reader_nodes = []
        writer_nodes = []
        
        for node in db_nodes:
            role = node.get('DBNodeRole', '').lower()
            if 'reader' in role:
                reader_nodes.append({
                    'id': node.get('DBNodeId'),
                    'status': node.get('DBNodeStatus'),
                    'class': node.get('DBNodeClass'),
                    'zone': node.get('ZoneId')
                })
            elif 'writer' in role:
                writer_nodes.append({
                    'id': node.get('DBNodeId'),
                    'status': node.get('DBNodeStatus'),
                    'class': node.get('DBNodeClass'),
                    'zone': node.get('ZoneId')
                })
        
        # Build simple response
        result = [
            f"CLUSTER: {db_cluster_id}",
            f"TOTAL_NODES: {len(db_nodes)}",
            ""
        ]
        
        if node_type.lower() in ["reader", "all"] and reader_nodes:
            result.extend([
                f"READER_NODES: {len(reader_nodes)}",
                ""
            ])
            for i, node in enumerate(reader_nodes, 1):
                result.extend([
                    f"READER_{i}:",
                    f"  NODE_ID: {node['id']}",
                    f"  STATUS: {node['status']}",
                    f"  CLASS: {node['class']}",
                    f"  ZONE: {node['zone']}",
                    ""
                ])
        
        if node_type.lower() in ["writer", "all"] and writer_nodes:
            result.extend([
                f"WRITER_NODES: {len(writer_nodes)}",
                ""
            ])
            for i, node in enumerate(writer_nodes, 1):
                result.extend([
                    f"WRITER_{i}:",
                    f"  NODE_ID: {node['id']}",
                    f"  STATUS: {node['status']}",
                    f"  CLASS: {node['class']}",
                    f"  ZONE: {node['zone']}",
                    ""
                ])
        
        # Add usage instructions
        if reader_nodes and node_type.lower() in ["reader", "all"]:
            result.extend([
                f"FOR_READER_PARAMETERS:",
                f"  Tool: polardb_describe_db_node_parameters",
                f"  db_cluster_id: {db_cluster_id}",
                f"  dbnode_id: {reader_nodes[0]['id']}",
                ""
            ])
        
        if writer_nodes and node_type.lower() in ["writer", "all"]:
            result.extend([
                f"FOR_WRITER_PARAMETERS:",
                f"  Tool: polardb_describe_db_node_parameters", 
                f"  db_cluster_id: {db_cluster_id}",
                f"  dbnode_id: {writer_nodes[0]['id']}",
                ""
            ])
        
        return [TextContent(type="text", text="\n".join(result))]

    except Exception as e:
        logger.error(f"Error extracting node IDs: {str(e)}")
        return [TextContent(type="text", text=f"ERROR extracting nodes: {str(e)}")]

def vpc_describe_vpcs(arguments: dict) -> list[TextContent]:
    """List all VPCs in a specific region"""
    region_id = arguments.get("region_id", "cn-hangzhou")

    client = create_vpc_client()
    if not client:
        return [TextContent(type="text", text="Failed to create VPC client. Please check your credentials.")]

    try:
        # Create request for describing VPCs
        request = vpc_20160428_models.DescribeVpcsRequest(
            region_id=region_id
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_vpcs_with_options(request, runtime)
        
        # Parse and format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Convert to dictionary for easier access
                response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                
                # Build comprehensive response
                result = [
                    f"=== VPC LISTING FOR REGION: {region_id.upper()} ===",
                    f"REQUEST_ID: {response_dict.get('RequestId', 'N/A')}",
                    f"PAGE_NUMBER: {response_dict.get('PageNumber', 'N/A')}",
                    f"PAGE_SIZE: {response_dict.get('PageSize', 'N/A')}",
                    f"TOTAL_COUNT: {response_dict.get('TotalCount', 'N/A')}",
                    "=" * 60,
                    ""
                ]
                
                # Process VPCs
                if 'Vpcs' in response_dict and 'Vpc' in response_dict['Vpcs']:
                    vpcs = response_dict['Vpcs']['Vpc']
                    
                    # Handle both single VPC and list of VPCs
                    if not isinstance(vpcs, list):
                        vpcs = [vpcs]
                    
                    result.append(f"TOTAL_VPCS_FOUND: {len(vpcs)}")
                    result.append("")
                    
                    for i, vpc in enumerate(vpcs, 1):
                        vpc_id = vpc.get('VpcId', 'N/A')
                        vpc_name = vpc.get('VpcName', 'No name')
                        cidr_block = vpc.get('CidrBlock', 'N/A')
                        status = vpc.get('Status', 'N/A')
                        is_default = vpc.get('IsDefault', False)
                        creation_time = vpc.get('CreationTime', 'N/A')
                        description = vpc.get('Description', 'No description')
                        resource_group_id = vpc.get('ResourceGroupId', 'N/A')
                        vrouter_id = vpc.get('VRouterId', 'N/A')
                        owner_id = vpc.get('OwnerId', 'N/A')
                        
                        # Handle empty name and description
                        if not vpc_name or vpc_name.strip() == "":
                            vpc_name = "No name provided"
                        if not description or description.strip() == "":
                            description = "No description provided"
                        
                        result.extend([
                            f"VPC_{i}:",
                            f"  VPC_ID: {vpc_id}",
                            f"  VPC_NAME: {vpc_name}",
                            f"  CIDR_BLOCK: {cidr_block}",
                            f"  STATUS: {status}",
                            f"  IS_DEFAULT: {'Yes' if is_default else 'No'}",
                            f"  CREATION_TIME: {creation_time}",
                            f"  DESCRIPTION: {description}",
                            f"  RESOURCE_GROUP_ID: {resource_group_id}",
                            f"  VROUTER_ID: {vrouter_id}",
                            f"  OWNER_ID: {owner_id}",
                            ""
                        ])
                        
                        # Process VSwitches if available
                        if 'VSwitchIds' in vpc and 'VSwitchId' in vpc['VSwitchIds']:
                            vswitch_ids = vpc['VSwitchIds']['VSwitchId']
                            if vswitch_ids:
                                result.append(f"  VSWITCHES: {len(vswitch_ids)} vSwitch(es)")
                                for j, vswitch_id in enumerate(vswitch_ids, 1):
                                    result.append(f"    vSwitch_{j}: {vswitch_id}")
                                result.append("")
                        
                        # Process Route Tables if available
                        if 'RouterTableIds' in vpc and 'RouterTableIds' in vpc['RouterTableIds']:
                            route_table_ids = vpc['RouterTableIds']['RouterTableIds']
                            if route_table_ids:
                                result.append(f"  ROUTE_TABLES: {len(route_table_ids)} route table(s)")
                                for j, route_table_id in enumerate(route_table_ids, 1):
                                    result.append(f"    RouteTable_{j}: {route_table_id}")
                                result.append("")
                        
                        # IPv6 information
                        ipv6_enabled = vpc.get('EnabledIpv6', False)
                        ipv6_cidr = vpc.get('Ipv6CidrBlock', '')
                        result.extend([
                            f"  IPV6_ENABLED: {'Yes' if ipv6_enabled else 'No'}",
                            f"  IPV6_CIDR_BLOCK: {ipv6_cidr if ipv6_cidr else 'None'}",
                            ""
                        ])
                        
                        # CEN and NAT Gateway information
                        cen_status = vpc.get('CenStatus', 'N/A')
                        nat_gateways = vpc.get('NatGatewayIds', {}).get('NatGatewayIds', [])
                        result.extend([
                            f"  CEN_STATUS: {cen_status}",
                            f"  NAT_GATEWAYS: {len(nat_gateways)} NAT gateway(s)",
                            ""
                        ])
                        
                        result.append("-" * 50)
                        result.append("")
                    
                    # Summary
                    result.extend([
                        "=== VPC SUMMARY ===",
                        f"Region: {region_id}",
                        f"Total VPCs: {len(vpcs)}",
                        f"Default VPCs: {sum(1 for vpc in vpcs if vpc.get('IsDefault', False))}",
                        f"Custom VPCs: {sum(1 for vpc in vpcs if not vpc.get('IsDefault', False))}",
                        ""
                    ])
                    
                    # List all VPC IDs for easy reference
                    vpc_id_list = [vpc.get('VpcId', 'Unknown') for vpc in vpcs]
                    result.extend([
                        "VPC_ID_LIST:",
                        ", ".join(vpc_id_list),
                        "",
                        "USAGE_EXAMPLES:",
                        "• Use these VPC IDs when creating PolarDB clusters",
                        "• Reference vSwitch IDs for subnet configuration",
                        "• Check route table configurations for network setup"
                    ])
                    
                else:
                    result.extend([
                        "NO_VPCS_FOUND",
                        f"No VPCs found in region {region_id}",
                        "This may indicate:",
                        "• No VPCs have been created in this region",
                        "• Insufficient permissions to view VPCs",
                        "• Region ID may be incorrect"
                    ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing VPC response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"VPC_QUERY_COMPLETED: {region_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed"
                ))]
        else:
            return [TextContent(type="text", text=f"NO_API_RESPONSE_FOR_REGION: {region_id}")]

    except Exception as e:
        logger.error(f"Error describing VPCs in {region_id}: {str(e)}")
        return [TextContent(type="text", text=f"ERROR_RETRIEVING_VPCS: {str(e)}")]

def vpc_describe_vswitches(arguments: dict) -> list[TextContent]:
    """List all VSwitches in a specific region, optionally filtered by VPC ID or Zone ID"""
    region_id = arguments.get("region_id", "cn-hangzhou")
    vpc_id = arguments.get("vpc_id")
    zone_id = arguments.get("zone_id")
    vswitch_id = arguments.get("vswitch_id")

    client = create_vpc_client()
    if not client:
        return [TextContent(type="text", text="Failed to create VPC client. Please check your credentials.")]

    try:
        # Create request for describing VSwitches
        request = vpc_20160428_models.DescribeVSwitchesRequest(
            region_id=region_id
        )
        
        # Add optional filters
        if vpc_id:
            request.vpc_id = vpc_id
        if zone_id:
            request.zone_id = zone_id
        if vswitch_id:
            request.vswitch_id = vswitch_id
            
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_vswitches_with_options(request, runtime)
        
        # Parse and format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Convert to dictionary for easier access
                response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                
                # Build comprehensive response
                filters_applied = []
                if vpc_id:
                    filters_applied.append(f"VPC: {vpc_id}")
                if zone_id:
                    filters_applied.append(f"Zone: {zone_id}")
                if vswitch_id:
                    filters_applied.append(f"VSwitch: {vswitch_id}")
                
                filter_text = f" (Filters: {', '.join(filters_applied)})" if filters_applied else ""
                
                result = [
                    f"=== VSWITCH LISTING FOR REGION: {region_id.upper()}{filter_text} ===",
                    f"REQUEST_ID: {response_dict.get('RequestId', 'N/A')}",
                    f"PAGE_NUMBER: {response_dict.get('PageNumber', 'N/A')}",
                    f"PAGE_SIZE: {response_dict.get('PageSize', 'N/A')}",
                    f"TOTAL_COUNT: {response_dict.get('TotalCount', 'N/A')}",
                    "=" * 60,
                    ""
                ]
                
                # Process VSwitches
                if 'VSwitches' in response_dict and 'VSwitch' in response_dict['VSwitches']:
                    vswitches = response_dict['VSwitches']['VSwitch']
                    
                    # Handle both single VSwitch and list of VSwitches
                    if not isinstance(vswitches, list):
                        vswitches = [vswitches]
                    
                    result.append(f"TOTAL_VSWITCHES_FOUND: {len(vswitches)}")
                    result.append("")
                    
                    # Group VSwitches by VPC for better organization
                    vpc_groups = {}
                    for vswitch in vswitches:
                        vpc_id_key = vswitch.get('VpcId', 'Unknown')
                        if vpc_id_key not in vpc_groups:
                            vpc_groups[vpc_id_key] = []
                        vpc_groups[vpc_id_key].append(vswitch)
                    
                    vswitch_counter = 1
                    for vpc_id_key, vpc_vswitches in vpc_groups.items():
                        result.extend([
                            f"VPC: {vpc_id_key} ({len(vpc_vswitches)} vSwitch(es))",
                            "-" * 40,
                            ""
                        ])
                        
                        for vswitch in vpc_vswitches:
                            vswitch_id = vswitch.get('VSwitchId', 'N/A')
                            vswitch_name = vswitch.get('VSwitchName', 'No name')
                            cidr_block = vswitch.get('CidrBlock', 'N/A')
                            status = vswitch.get('Status', 'N/A')
                            is_default = vswitch.get('IsDefault', False)
                            creation_time = vswitch.get('CreationTime', 'N/A')
                            description = vswitch.get('Description', 'No description')
                            zone_id = vswitch.get('ZoneId', 'N/A')
                            available_ip_count = vswitch.get('AvailableIpAddressCount', 0)
                            resource_group_id = vswitch.get('ResourceGroupId', 'N/A')
                            owner_id = vswitch.get('OwnerId', 'N/A')
                            
                            # Handle empty name and description
                            if not vswitch_name or vswitch_name.strip() == "":
                                vswitch_name = "No name provided"
                            if not description or description.strip() == "":
                                description = "No description provided"
                            
                            result.extend([
                                f"VSWITCH_{vswitch_counter}:",
                                f"  VSWITCH_ID: {vswitch_id}",
                                f"  VSWITCH_NAME: {vswitch_name}",
                                f"  CIDR_BLOCK: {cidr_block}",
                                f"  ZONE_ID: {zone_id}",
                                f"  STATUS: {status}",
                                f"  IS_DEFAULT: {'Yes' if is_default else 'No'}",
                                f"  AVAILABLE_IP_COUNT: {available_ip_count:,}",
                                f"  CREATION_TIME: {creation_time}",
                                f"  DESCRIPTION: {description}",
                                f"  RESOURCE_GROUP_ID: {resource_group_id}",
                                f"  OWNER_ID: {owner_id}",
                                ""
                            ])
                            
                            # Route Table information
                            if 'RouteTable' in vswitch and vswitch['RouteTable']:
                                route_table = vswitch['RouteTable']
                                route_table_id = route_table.get('RouteTableId', 'N/A')
                                route_table_type = route_table.get('RouteTableType', 'N/A')
                                result.extend([
                                    f"  ROUTE_TABLE:",
                                    f"    TABLE_ID: {route_table_id}",
                                    f"    TABLE_TYPE: {route_table_type}",
                                    ""
                                ])
                            
                            # IPv6 information
                            ipv6_cidr = vswitch.get('Ipv6CidrBlock', '')
                            result.extend([
                                f"  IPV6_CIDR_BLOCK: {ipv6_cidr if ipv6_cidr else 'None'}",
                                ""
                            ])
                            
                            # Network ACL information
                            network_acl_id = vswitch.get('NetworkAclId', '')
                            share_type = vswitch.get('ShareType', '')
                            result.extend([
                                f"  NETWORK_ACL_ID: {network_acl_id if network_acl_id else 'None'}",
                                f"  SHARE_TYPE: {share_type if share_type else 'Private'}",
                                ""
                            ])
                            
                            result.append("-" * 30)
                            result.append("")
                            vswitch_counter += 1
                    
                    # Summary by VPC
                    result.extend([
                        "=== VSWITCH SUMMARY BY VPC ===",
                        ""
                    ])
                    
                    total_available_ips = 0
                    zone_distribution = {}
                    
                    for vpc_id_key, vpc_vswitches in vpc_groups.items():
                        vpc_available_ips = sum(vs.get('AvailableIpAddressCount', 0) for vs in vpc_vswitches)
                        total_available_ips += vpc_available_ips
                        
                        result.extend([
                            f"VPC {vpc_id_key}:",
                            f"  VSwitches: {len(vpc_vswitches)}",
                            f"  Available IPs: {vpc_available_ips:,}",
                            f"  Zones: {', '.join(set(vs.get('ZoneId', 'Unknown') for vs in vpc_vswitches))}",
                            ""
                        ])
                        
                        # Count zone distribution
                        for vs in vpc_vswitches:
                            zone = vs.get('ZoneId', 'Unknown')
                            zone_distribution[zone] = zone_distribution.get(zone, 0) + 1
                    
                    # Overall summary
                    result.extend([
                        "=== OVERALL SUMMARY ===",
                        f"Region: {region_id}",
                        f"Total VSwitches: {len(vswitches)}",
                        f"Total Available IPs: {total_available_ips:,}",
                        f"VPCs Covered: {len(vpc_groups)}",
                        f"Zones Covered: {len(zone_distribution)}",
                        ""
                    ])
                    
                    # Zone distribution
                    if zone_distribution:
                        result.append("ZONE_DISTRIBUTION:")
                        for zone, count in sorted(zone_distribution.items()):
                            result.append(f"  {zone}: {count} vSwitch(es)")
                        result.append("")
                    
                    # List all VSwitch IDs for easy reference
                    vswitch_id_list = [vs.get('VSwitchId', 'Unknown') for vs in vswitches]
                    result.extend([
                        "VSWITCH_ID_LIST:",
                        ", ".join(vswitch_id_list),
                        "",
                        "USAGE_EXAMPLES:",
                        "• Use these vSwitch IDs when creating PolarDB clusters",
                        "• Choose vSwitches in different zones for high availability",
                        "• Consider available IP count when planning deployments",
                        "• Use vSwitches in the same VPC for internal communication"
                    ])
                    
                else:
                    result.extend([
                        "NO_VSWITCHES_FOUND",
                        f"No VSwitches found in region {region_id}",
                        ""
                    ])
                    
                    if filters_applied:
                        result.extend([
                            "Applied filters may have limited results:",
                            *[f"• {filter_item}" for filter_item in filters_applied],
                            ""
                        ])
                    
                    result.extend([
                        "This may indicate:",
                        "• No VSwitches have been created in this region/VPC",
                        "• Insufficient permissions to view VSwitches",
                        "• Region ID, VPC ID, or Zone ID may be incorrect"
                    ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing VSwitch response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"VSWITCH_QUERY_COMPLETED: {region_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed"
                ))]
        else:
            return [TextContent(type="text", text=f"NO_API_RESPONSE_FOR_REGION: {region_id}")]

    except Exception as e:
        logger.error(f"Error describing VSwitches in {region_id}: {str(e)}")
        return [TextContent(type="text", text=f"ERROR_RETRIEVING_VSWITCHES: {str(e)}")]

def polardb_modify_db_cluster_access_whitelist_enhanced(arguments: dict) -> list[TextContent]:
    """Modify the access whitelist for a PolarDB cluster with enhanced response formatting"""
    dbcluster_id = arguments.get("dbcluster_id")
    security_ips = arguments.get("security_ips")
    db_cluster_iparray_name = arguments.get("db_cluster_iparray_name", "default")
    modify_mode = arguments.get("modify_mode", "Cover")
    white_list_type = arguments.get("white_list_type", "IP")
    security_group_ids = arguments.get("security_group_ids")

    # Validate required parameters
    if not dbcluster_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: DB Cluster ID is required")]
    
    # Validate white_list_type
    valid_white_list_types = ["IP", "SecurityGroup"]
    if white_list_type not in valid_white_list_types:
        return [TextContent(type="text", text=f"❌ INVALID_PARAMETER: white_list_type must be one of {valid_white_list_types}. Got: {white_list_type}")]
    
    # Validate parameters based on white_list_type
    if white_list_type == "IP" and not security_ips:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: Security IPs are required when white_list_type is 'IP' (e.g., '192.168.1.1,10.0.0.1' or '0.0.0.0/0' for all)")]
    
    if white_list_type == "SecurityGroup" and not security_group_ids:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: Security Group IDs are required when white_list_type is 'SecurityGroup' (e.g., 'sg-12345,sg-67890')")]

    # Validate modify_mode
    valid_modes = ["Cover", "Append", "Delete"]
    if modify_mode not in valid_modes:
        return [TextContent(type="text", text=f"❌ INVALID_PARAMETER: modify_mode must be one of {valid_modes}. Got: {modify_mode}")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ CLIENT_ERROR: Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for modifying DB cluster access whitelist
        request = polardb_20170801_models.ModifyDBClusterAccessWhitelistRequest(
            dbcluster_id=dbcluster_id,
            db_cluster_iparray_name=db_cluster_iparray_name,
            modify_mode=modify_mode,
            white_list_type=white_list_type
        )

        # Set parameters based on white_list_type
        if white_list_type == "IP" and security_ips:
            request.security_ips = security_ips
        elif white_list_type == "SecurityGroup" and security_group_ids:
            request.security_group_ids = security_group_ids
        
        # Set optional security group IDs if provided and white_list_type is IP
        if white_list_type == "IP" and security_group_ids:
            request.security_group_ids = security_group_ids

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.modify_dbcluster_access_whitelist_with_options(request, runtime)

        # Format the response with comprehensive details
        if hasattr(response, 'body') and response.body:
            try:
                # Convert to dictionary for easier access
                response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                
                result = [
                    "=== POLARDB ACCESS WHITELIST MODIFICATION COMPLETED ===",
                    f"🎯 TARGET_CLUSTER: {dbcluster_id}",
                    f"🔧 OPERATION_TYPE: {modify_mode}",
                    f"📅 TIMESTAMP: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    "=" * 60,
                    ""
                ]
                
                # Operation details
                result.extend([
                    "OPERATION_DETAILS:",
                    f"  WHITE_LIST_TYPE: {white_list_type}",
                    f"  IP_ARRAY_NAME: {db_cluster_iparray_name}",
                    f"  MODIFY_MODE: {modify_mode}",
                ])
                
                if white_list_type == "IP" and security_ips:
                    result.append(f"  SECURITY_IPS: {security_ips}")
                
                if white_list_type == "SecurityGroup" and security_group_ids:
                    result.append(f"  SECURITY_GROUPS: {security_group_ids}")
                elif white_list_type == "IP" and security_group_ids:
                    result.append(f"  ADDITIONAL_SECURITY_GROUPS: {security_group_ids}")
                
                result.append("")
                
                # Analyze configuration based on white_list_type
                if white_list_type == "IP" and security_ips:
                    result.append("IP_CONFIGURATION_ANALYSIS:")
                    ip_list = [ip.strip() for ip in security_ips.split(',') if ip.strip()]
                    
                    for i, ip in enumerate(ip_list, 1):
                        if ip == '0.0.0.0/0':
                            result.extend([
                                f"  IP_{i}: {ip}",
                                f"    TYPE: OPEN_TO_ALL_INTERNET",
                                f"    SECURITY_LEVEL: 🔴 MAXIMUM_RISK",
                                f"    DESCRIPTION: Allows access from any IP address worldwide",
                                ""
                            ])
                        elif ip.startswith('127.'):
                            result.extend([
                                f"  IP_{i}: {ip}",
                                f"    TYPE: LOCALHOST_ONLY",
                                f"    SECURITY_LEVEL: 🟢 MINIMAL_RISK",
                                f"    DESCRIPTION: Local machine access only",
                                ""
                            ])
                        elif ip.startswith(('192.168.', '10.', '172.')):
                            result.extend([
                                f"  IP_{i}: {ip}",
                                f"    TYPE: PRIVATE_NETWORK",
                                f"    SECURITY_LEVEL: 🟡 LOW_RISK",
                                f"    DESCRIPTION: Internal network IP address",
                                ""
                            ])
                        elif '/' in ip:
                            try:
                                network_size = int(ip.split('/')[-1])
                                if network_size <= 16:
                                    risk_level = "🟠 HIGH_RISK"
                                    description = f"Large network range (/{network_size})"
                                elif network_size <= 24:
                                    risk_level = "🟡 MEDIUM_RISK"
                                    description = f"Medium network range (/{network_size})"
                                else:
                                    risk_level = "🟢 LOW_RISK"
                                    description = f"Small network range (/{network_size})"
                            except:
                                risk_level = "❓ UNKNOWN_RISK"
                                description = "Invalid CIDR format"
                            
                            result.extend([
                                f"  IP_{i}: {ip}",
                                f"    TYPE: SUBNET_RANGE",
                                f"    SECURITY_LEVEL: {risk_level}",
                                f"    DESCRIPTION: {description}",
                                ""
                            ])
                        else:
                            result.extend([
                                f"  IP_{i}: {ip}",
                                f"    TYPE: SPECIFIC_IP",
                                f"    SECURITY_LEVEL: 🟢 LOW_RISK",
                                f"    DESCRIPTION: Single IP address access",
                                ""
                            ])
                
                elif white_list_type == "SecurityGroup" and security_group_ids:
                    result.append("SECURITY_GROUP_CONFIGURATION_ANALYSIS:")
                    sg_list = [sg.strip() for sg in security_group_ids.split(',') if sg.strip()]
                    
                    for i, sg in enumerate(sg_list, 1):
                        result.extend([
                            f"  SECURITY_GROUP_{i}: {sg}",
                            f"    TYPE: ECS_SECURITY_GROUP",
                            f"    SECURITY_LEVEL: 🟢 MANAGED_ACCESS",
                            f"    DESCRIPTION: Access controlled by security group rules",
                            f"    BENEFIT: Dynamic access control based on ECS instances",
                            ""
                        ])
                    
                    result.extend([
                        "SECURITY_GROUP_ADVANTAGES:",
                        "  • Dynamic access control - no need to update IPs when instances change",
                        "  • Centralized management through ECS security groups",
                        "  • Automatic handling of elastic scaling scenarios",
                        "  • Integration with Alibaba Cloud security policies",
                        ""
                    ])
                
                # White list type explanations
                result.extend([
                    "WHITE_LIST_TYPE_EXPLANATION:",
                    f"  SELECTED_TYPE: {white_list_type}",
                    ""
                ])
                
                if white_list_type == "IP":
                    result.extend([
                        "  📍 IP MODE:",
                        "    • Access control based on IP addresses and CIDR blocks",
                        "    • Direct IP-based filtering at network level",
                        "    • Suitable for fixed IP environments",
                        "    • Requires manual updates when IP addresses change",
                        ""
                    ])
                elif white_list_type == "SecurityGroup":
                    result.extend([
                        "  🛡️ SECURITY_GROUP MODE:",
                        "    • Access control based on ECS security group membership",
                        "    • Dynamic access control that adapts to instance changes",
                        "    • Suitable for elastic and auto-scaling environments",
                        "    • Centralized management through security group rules",
                        ""
                    ])
                
                # Mode-specific explanations
                result.extend([
                    "MODIFY_MODE_EXPLANATION:",
                    f"  SELECTED_MODE: {modify_mode}",
                    ""
                ])
                
                if modify_mode == "Cover":
                    result.extend([
                        "  🔄 COVER MODE:",
                        "    • Replaces ALL existing IPs in the specified IP array",
                        "    • Previous IP configurations will be completely overwritten",
                        "    • Use this mode for complete IP list replacement",
                        ""
                    ])
                elif modify_mode == "Append":
                    result.extend([
                        "  ➕ APPEND MODE:",
                        "    • Adds new IPs to the existing IP array",
                        "    • Previous IP configurations are preserved",
                        "    • Use this mode to add additional access sources",
                        ""
                    ])
                elif modify_mode == "Delete":
                    result.extend([
                        "  ➖ DELETE MODE:",
                        "    • Removes specified IPs from the existing IP array",
                        "    • Other IP configurations remain unchanged",
                        "    • Use this mode to revoke access from specific sources",
                        ""
                    ])
                
                # Response details
                request_id = response_dict.get('RequestId', 'N/A')
                result.extend([
                    "API_RESPONSE_DETAILS:",
                    f"  REQUEST_ID: {request_id}",
                    f"  STATUS: ✅ SUCCESS",
                    f"  OPERATION: Whitelist modification completed successfully",
                    ""
                ])
                
                # Security recommendations based on white_list_type
                result.extend([
                    "SECURITY_RECOMMENDATIONS:",
                ])
                
                if white_list_type == "IP":
                    result.extend([
                        "  IP-BASED ACCESS CONTROL:",
                        "  • Regularly review and audit IP whitelist configurations",
                        "  • Use specific IP addresses instead of broad ranges when possible",
                        "  • Avoid 0.0.0.0/0 unless absolutely necessary for public access",
                        "  • Consider using CIDR notation for network ranges",
                        "  • Monitor database access logs for unusual activity",
                        ""
                    ])
                elif white_list_type == "SecurityGroup":
                    result.extend([
                        "  SECURITY_GROUP-BASED ACCESS CONTROL:",
                        "  • Regularly review security group rules and membership",
                        "  • Use principle of least privilege for security group rules",
                        "  • Monitor ECS instances associated with security groups",
                        "  • Consider separate security groups for different environments",
                        "  • Audit security group changes and access patterns",
                        ""
                    ])
                
                result.extend([
                    "  GENERAL RECOMMENDATIONS:",
                    "  • Use VPC networks for additional network isolation",
                    "  • Enable database audit logs for access monitoring",
                    "  • Implement proper authentication and authorization",
                    "  • Regular security assessments and penetration testing",
                    ""
                ])
                
                # Next steps
                result.extend([
                    "VERIFICATION_STEPS:",
                    "  1. Use polardb_describe_db_cluster_access_whitelist to verify changes",
                    "  2. Test connectivity from allowed IP addresses",
                    "  3. Ensure applications can connect successfully",
                    "  4. Check for any connection issues from previously allowed IPs",
                    ""
                ])
                
                # Final status
                result.extend([
                    "=" * 60,
                    f"✅ WHITELIST MODIFICATION COMPLETED SUCCESSFULLY",
                    f"Cluster: {dbcluster_id}",
                    f"Mode: {modify_mode}",
                    f"Request ID: {request_id}",
                    "=" * 60
                ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing modify whitelist response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"WHITELIST_MODIFICATION_COMPLETED: {dbcluster_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed"
                ))]
        else:
            return [TextContent(type="text", text=f"⚠️  PARTIAL_SUCCESS: Modification completed but no response details received for cluster {dbcluster_id}")]

    except Exception as e:
        logger.error(f"Error modifying PolarDB cluster access whitelist: {str(e)}")
        
        # Provide helpful error context
        error_result = [
            f"❌ WHITELIST_MODIFICATION_FAILED",
            f"CLUSTER: {dbcluster_id}",
            f"ERROR: {str(e)}",
            "",
            "TROUBLESHOOTING_STEPS:",
            "• Verify cluster ID is correct and exists",
            "• Check IP address format (use commas to separate multiple IPs)",
            "• Ensure you have permission to modify cluster access whitelist",
            "• Verify network connectivity to Alibaba Cloud APIs",
            "• Check if cluster is in a modifiable state",
            "",
            "VALID_IP_FORMATS:",
            "• Single IP: '192.168.1.100'",
            "• Multiple IPs: '192.168.1.100,10.0.0.50'",
            "• CIDR blocks: '192.168.1.0/24,10.0.0.0/16'",
            "• Open access: '0.0.0.0/0' (not recommended for production)",
            "",
            f"PARAMETERS_USED:",
            f"• Cluster ID: {dbcluster_id}",
            f"• White List Type: {white_list_type}",
            f"• Modify Mode: {modify_mode}",
            f"• IP Array Name: {db_cluster_iparray_name}",
        ]
        
        if white_list_type == "IP" and security_ips:
            error_result.append(f"• Security IPs: {security_ips}")
        if security_group_ids:
            error_result.append(f"• Security Groups: {security_group_ids}")
        
        return [TextContent(type="text", text="\n".join(error_result))]

def polardb_modify_db_cluster_description(arguments: dict) -> list[TextContent]:
    """Modify the description of a PolarDB cluster with comprehensive validation and response formatting"""
    dbcluster_id = arguments.get("dbcluster_id")
    dbcluster_description = arguments.get("dbcluster_description")

    # Validate required parameters
    if not dbcluster_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: DB Cluster ID is required")]
    
    if not dbcluster_description:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: DB Cluster Description is required")]

    # Validate description format and content
    description_errors = []
    
    # Length validation
    if len(dbcluster_description) < 2:
        description_errors.append("Description must be at least 2 characters long")
    elif len(dbcluster_description) > 256:
        description_errors.append("Description must not exceed 256 characters")
    
    # Content validation - cannot start with http:// or https://
    if dbcluster_description.lower().startswith(('http://', 'https://')):
        description_errors.append("Description cannot start with 'http://' or 'https://'")
    
    # Additional format validations
    if dbcluster_description.strip() != dbcluster_description:
        description_errors.append("Description should not have leading or trailing whitespace")
    
    # Check for potentially problematic characters
    invalid_chars = ['<', '>', '"', "'", '&']
    found_invalid = [char for char in invalid_chars if char in dbcluster_description]
    if found_invalid:
        description_errors.append(f"Description contains potentially problematic characters: {', '.join(found_invalid)}")
    
    if description_errors:
        error_msg = [
            "❌ INVALID_DESCRIPTION: The provided description has the following issues:",
            ""
        ]
        for i, error in enumerate(description_errors, 1):
            error_msg.append(f"{i}. {error}")
        
        error_msg.extend([
            "",
            "DESCRIPTION_REQUIREMENTS:",
            "• Length: 2-256 characters",
            "• Cannot start with 'http://' or 'https://'",
            "• Should not contain HTML/XML special characters",
            "• Recommended: Use clear, descriptive text about the cluster purpose",
            "",
            f"CURRENT_DESCRIPTION: '{dbcluster_description}'",
            f"CURRENT_LENGTH: {len(dbcluster_description)} characters"
        ])
        
        return [TextContent(type="text", text="\n".join(error_msg))]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ CLIENT_ERROR: Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for modifying DB cluster description
        request = polardb_20170801_models.ModifyDBClusterDescriptionRequest(
            dbcluster_id=dbcluster_id,
            dbcluster_description=dbcluster_description
        )

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.modify_dbcluster_description_with_options(request, runtime)

        # Format the response with comprehensive details
        if hasattr(response, 'body') and response.body:
            try:
                # Convert to dictionary for easier access
                response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                
                result = [
                    "=== POLARDB CLUSTER DESCRIPTION MODIFICATION COMPLETED ===",
                    f"🎯 TARGET_CLUSTER: {dbcluster_id}",
                    f"📝 OPERATION_TYPE: Description Update",
                    f"📅 TIMESTAMP: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    "=" * 60,
                    ""
                ]
                
                # Operation details
                result.extend([
                    "OPERATION_DETAILS:",
                    f"  CLUSTER_ID: {dbcluster_id}",
                    f"  NEW_DESCRIPTION: '{dbcluster_description}'",
                    f"  DESCRIPTION_LENGTH: {len(dbcluster_description)} characters",
                    f"  VALIDATION_STATUS: ✅ PASSED",
                    ""
                ])
                
                # Description analysis
                result.extend([
                    "DESCRIPTION_ANALYSIS:",
                    f"  CHARACTER_COUNT: {len(dbcluster_description)}/256 max",
                    f"  WORD_COUNT: {len(dbcluster_description.split())} words",
                    f"  STARTS_WITH_URL: {'❌ No' if not dbcluster_description.lower().startswith(('http://', 'https://')) else '⚠️ Yes'}",
                    ""
                ])
                
                # Content assessment
                if len(dbcluster_description) < 20:
                    desc_quality = "🟡 Brief description"
                    quality_note = "Consider adding more details about the cluster purpose"
                elif len(dbcluster_description) < 100:
                    desc_quality = "🟢 Good description length"
                    quality_note = "Appropriate level of detail"
                else:
                    desc_quality = "🔵 Detailed description"
                    quality_note = "Comprehensive description provided"
                
                result.extend([
                    "DESCRIPTION_QUALITY_ASSESSMENT:",
                    f"  QUALITY_RATING: {desc_quality}",
                    f"  ASSESSMENT: {quality_note}",
                    ""
                ])
                
                # Check for common description patterns
                description_lower = dbcluster_description.lower()
                patterns = {
                    "environment": any(env in description_lower for env in ['prod', 'dev', 'test', 'staging', 'production', 'development']),
                    "purpose": any(purpose in description_lower for purpose in ['web', 'api', 'database', 'service', 'application', 'system']),
                    "team": any(team in description_lower for team in ['team', 'department', 'project', 'group']),
                    "location": any(loc in description_lower for loc in ['region', 'zone', 'datacenter', 'office'])
                }
                
                detected_patterns = [pattern for pattern, found in patterns.items() if found]
                if detected_patterns:
                    result.extend([
                        "DESCRIPTION_CONTENT_PATTERNS:",
                        f"  DETECTED_CATEGORIES: {', '.join(detected_patterns).title()}",
                        f"  ORGANIZATION_LEVEL: {'🟢 Well-structured' if len(detected_patterns) >= 2 else '🟡 Basic structure'}",
                        ""
                    ])
                
                # Response details
                request_id = response_dict.get('RequestId', 'N/A')
                result.extend([
                    "API_RESPONSE_DETAILS:",
                    f"  REQUEST_ID: {request_id}",
                    f"  STATUS: ✅ SUCCESS",
                    f"  OPERATION: Description modification completed successfully",
                    ""
                ])
                
                # Best practices and recommendations
                result.extend([
                    "DESCRIPTION_BEST_PRACTICES:",
                    "  CONTENT_GUIDELINES:",
                    "  • Include environment type (production, development, testing)",
                    "  • Specify the application or service purpose",
                    "  • Mention the team or project responsible",
                    "  • Include relevant technical details (version, configuration)",
                    "  • Use clear, concise language without abbreviations",
                    "",
                    "  FORMATTING_GUIDELINES:",
                    "  • Keep descriptions between 20-100 characters for optimal readability",
                    "  • Use title case or sentence case consistently",
                    "  • Avoid special characters and URLs",
                    "  • Include creation date or version information if relevant",
                    ""
                ])
                
                # Examples of good descriptions
                result.extend([
                    "EXAMPLE_DESCRIPTIONS:",
                    "  • 'Production MySQL cluster for e-commerce web application'",
                    "  • 'Development database for user authentication service - Team Alpha'",
                    "  • 'Staging environment for order processing system v2.1'",
                    "  • 'Analytics database cluster for business intelligence dashboard'",
                    "  • 'Customer data warehouse for CRM integration - Marketing Dept'",
                    ""
                ])
                
                # Verification steps
                result.extend([
                    "VERIFICATION_STEPS:",
                    "  1. Use polardb_describe_db_cluster to verify the description change",
                    "  2. Check cluster listing to ensure description appears correctly",
                    "  3. Verify description is visible in Alibaba Cloud console",
                    "  4. Update any documentation or inventory systems",
                    ""
                ])
                
                # Final status
                result.extend([
                    "=" * 60,
                    f"✅ DESCRIPTION MODIFICATION COMPLETED SUCCESSFULLY",
                    f"Cluster: {dbcluster_id}",
                    f"New Description: '{dbcluster_description}'",
                    f"Request ID: {request_id}",
                    "=" * 60
                ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing modify description response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"DESCRIPTION_MODIFICATION_COMPLETED: {dbcluster_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed"
                ))]
        else:
            return [TextContent(type="text", text=f"⚠️  PARTIAL_SUCCESS: Description modification completed but no response details received for cluster {dbcluster_id}")]

    except Exception as e:
        logger.error(f"Error modifying PolarDB cluster description: {str(e)}")
        
        # Provide helpful error context
        error_result = [
            f"❌ DESCRIPTION_MODIFICATION_FAILED",
            f"CLUSTER: {dbcluster_id}",
            f"ERROR: {str(e)}",
            "",
            "TROUBLESHOOTING_STEPS:",
            "• Verify cluster ID is correct and exists",
            "• Check if cluster is in a modifiable state (not during maintenance)",
            "• Ensure you have permission to modify cluster properties",
            "• Verify network connectivity to Alibaba Cloud APIs",
            "• Check description format and content requirements",
            "",
            "DESCRIPTION_REQUIREMENTS_REMINDER:",
            "• Length: 2-256 characters",
            "• Cannot start with 'http://' or 'https://'",
            "• Should be descriptive and meaningful",
            "• Avoid special characters that might cause parsing issues",
            "",
            f"PARAMETERS_USED:",
            f"• Cluster ID: {dbcluster_id}",
            f"• Description: '{dbcluster_description}'",
            f"• Description Length: {len(dbcluster_description)} characters",
        ]
        
        return [TextContent(type="text", text="\n".join(error_result))]

def polardb_describe_error_log_records(arguments: dict) -> list[TextContent]:
    """Get error log records for a specific PolarDB cluster within a time range using DAS API"""
    instance_id = arguments.get("instance_id")
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")
    node_id = arguments.get("node_id")
    page_size = arguments.get("page_size", 10)
    page_number = arguments.get("page_number", 1)

    # Validate required parameters
    if not instance_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: Instance ID is required")]
    if not start_time:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: Start time is required")]
    if not end_time:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: End time is required")]
    if not node_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: Node ID is required")]

    # Convert time formats to Unix timestamps in milliseconds
    try:
        # Handle different input formats
        if isinstance(start_time, str):
            # Parse ISO format string to Unix timestamp in milliseconds
            if 'T' in start_time:
                # ISO format like '2025-07-11T20:50Z'
                dt_start = datetime.strptime(start_time.replace('Z', '+00:00'), '%Y-%m-%dT%H:%M%z')
                start_time_ms = int(dt_start.timestamp() * 1000)
            else:
                return [TextContent(type="text", text="❌ INVALID_TIME_FORMAT: Start time must be in ISO format (e.g., '2025-07-11T20:50Z') or Unix timestamp")]
        elif isinstance(start_time, (int, float)):
            # Already a timestamp - check if it's in seconds or milliseconds
            if start_time < 10000000000:  # Less than 10 billion = seconds
                start_time_ms = int(start_time * 1000)
            else:  # Already in milliseconds
                start_time_ms = int(start_time)
        else:
            return [TextContent(type="text", text="❌ INVALID_TIME_TYPE: Start time must be string (ISO format) or number (Unix timestamp)")]

        if isinstance(end_time, str):
            # Parse ISO format string to Unix timestamp in milliseconds
            if 'T' in end_time:
                # ISO format like '2025-07-12T22:50Z'
                dt_end = datetime.strptime(end_time.replace('Z', '+00:00'), '%Y-%m-%dT%H:%M%z')
                end_time_ms = int(dt_end.timestamp() * 1000)
            else:
                return [TextContent(type="text", text="❌ INVALID_TIME_FORMAT: End time must be in ISO format (e.g., '2025-07-12T22:50Z') or Unix timestamp")]
        elif isinstance(end_time, (int, float)):
            # Already a timestamp - check if it's in seconds or milliseconds
            if end_time < 10000000000:  # Less than 10 billion = seconds
                end_time_ms = int(end_time * 1000)
            else:  # Already in milliseconds
                end_time_ms = int(end_time)
        else:
            return [TextContent(type="text", text="❌ INVALID_TIME_TYPE: End time must be string (ISO format) or number (Unix timestamp)")]

        # Validate time sequence
        if end_time_ms <= start_time_ms:
            return [TextContent(type="text", text="❌ INVALID_TIME_RANGE: End time must be after start time")]

    except Exception as e:
        return [TextContent(type="text", text=f"❌ TIME_CONVERSION_ERROR: {str(e)}")]

    client = create_das_client()
    if not client:
        return [TextContent(type="text", text="❌ CLIENT_ERROR: Failed to create DAS client. Please check your credentials.")]

    try:
        # Create request for describing error log records
        request = das20200116_models.DescribeErrorLogRecordsRequest(
            instance_id=instance_id,
            start_time=start_time_ms,  # Use converted milliseconds
            end_time=end_time_ms,      # Use converted milliseconds
            node_id=node_id            # Required parameter
        )

        # Set optional parameters if provided
        if page_size:
            request.page_size = page_size
        if page_number:
            request.page_number = page_number

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_error_log_records_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Convert to dictionary for easier access
                response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                
                result = [
                    "=== POLARDB ERROR LOG RECORDS ===",
                    f"INSTANCE_ID: {instance_id}",
                    f"NODE_ID: {node_id}",
                    f"INPUT_START_TIME: {start_time}",
                    f"INPUT_END_TIME: {end_time}",
                    f"CONVERTED_START_TIME_MS: {start_time_ms}",
                    f"CONVERTED_END_TIME_MS: {end_time_ms}",
                    f"REQUEST_ID: {response_dict.get('RequestId', 'N/A')}",
                    f"SUCCESS: {response_dict.get('Success', 'N/A')}",
                    f"MESSAGE: {response_dict.get('Message', 'N/A')}",
                    "=" * 60
                ]
                
                # Process the data section
                if 'Data' in response_dict and response_dict['Data']:
                    data = response_dict['Data']
                    
                    result.extend([
                        f"TIME_RANGE: {data.get('StartTime', 'N/A')} to {data.get('EndTime', 'N/A')}",
                        f"TOTAL_RECORDS: {data.get('TotalRecords', 'N/A')}",
                        f"PAGE_NUMBER: {data.get('PageNumbers', 'N/A')}",
                        f"MAX_RECORDS_PER_PAGE: {data.get('MaxRecordsPerPage', 'N/A')}",
                        f"ITEMS_IN_RESPONSE: {data.get('ItemsNumbers', 'N/A')}",
                        ""
                    ])
                    
                    # Process error logs
                    if 'Logs' in data and data['Logs']:
                        logs = data['Logs']
                        
                        result.append(f"ERROR_LOG_ENTRIES: {len(logs)}")
                        result.append("")
                        
                        for i, log in enumerate(logs, 1):
                            content = log.get('Content', 'N/A')
                            create_time = log.get('CreateTime', 'N/A')
                            
                            # Convert timestamp to readable format
                            readable_time = 'N/A'
                            if create_time != 'N/A':
                                try:
                                    timestamp_seconds = int(create_time) / 1000
                                    readable_time = datetime.fromtimestamp(timestamp_seconds).strftime('%Y-%m-%d %H:%M:%S UTC')
                                except (ValueError, TypeError):
                                    readable_time = str(create_time)
                            
                            result.extend([
                                f"ERROR_LOG_{i}:",
                                f"  TIME: {readable_time}",
                                f"  TIMESTAMP: {create_time}",
                                f"  CONTENT: {content}",
                                ""
                            ])
                    else:
                        result.append("NO_ERROR_LOGS_FOUND")
                        result.append("")
                    
                else:
                    result.extend([
                        "NO_DATA_SECTION_FOUND",
                        "The API response did not contain error log data"
                    ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing error log response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"ERROR_LOG_QUERY_COMPLETED: {instance_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed"
                ))]
        else:
            return [TextContent(type="text", text=f"NO_API_RESPONSE_FOR_INSTANCE: {instance_id}")]

    except Exception as e:
        logger.error(f"Error describing error log records: {str(e)}")
        return [TextContent(type="text", text=f"API_ERROR: {str(e)}")]

def polardb_describe_db_proxy_performance(arguments: dict) -> list[TextContent]:
    """Get proxy performance metrics for a specific PolarDB cluster within a time range with enhanced analysis"""
    dbcluster_id = arguments.get("dbcluster_id")
    dbnode_id = arguments.get("dbnode_id")
    key = arguments.get("key")
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")

    # Validate required parameters
    if not dbcluster_id:
        return [TextContent(type="text", text="❌ 缺少参数: 需要提供数据库集群ID")]
    if not dbnode_id:
        return [TextContent(type="text", text="❌ 缺少参数: 需要提供数据库节点ID")]
    if not key:
        return [TextContent(type="text", text="❌ 缺少参数: 需要提供性能指标key")]
    if not start_time:
        return [TextContent(type="text", text="❌ 缺少参数: 需要提供开始时间")]
    if not end_time:
        return [TextContent(type="text", text="❌ 缺少参数: 需要提供结束时间")]

    # Validate and correct proxy performance metrics (don't use defaults since key is required)
    validated_key, warnings = validate_proxy_performance_keys(key)
    
    # Convert times to Beijing time and then to UTC for API
    try:
        corrected_start_time = convert_to_beijing_time(start_time)
        corrected_end_time = convert_to_beijing_time(end_time)
        
        # Validate time sequence
        start_dt = datetime.strptime(corrected_start_time, '%Y-%m-%dT%H:%MZ')
        end_dt = datetime.strptime(corrected_end_time, '%Y-%m-%dT%H:%MZ')
        
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)
            corrected_end_time = end_dt.strftime('%Y-%m-%dT%H:%MZ')
            warnings.append(f"结束时间已调整为开始时间后1小时: {corrected_end_time}")
            
    except Exception as e:
        logger.error(f"Time conversion error: {e}")
        return [TextContent(type="text", text=f"❌ 时间格式错误: {str(e)}")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ 创建PolarDB客户端失败，请检查凭证配置")]

    try:
        # Create request
        request = polardb_20170801_models.DescribeDBProxyPerformanceRequest(
            dbcluster_id=dbcluster_id,
            key=validated_key,
            start_time=corrected_start_time,
            end_time=corrected_end_time
        )

        # Set optional dbnode_id parameter
        if dbnode_id:
            request.dbnode_id = dbnode_id

        runtime = util_models.RuntimeOptions()
        
        logger.info(f"调用代理性能API: cluster={dbcluster_id}, node={dbnode_id}, key={validated_key}, start={corrected_start_time}, end={corrected_end_time}")

        # Call the API
        response = client.describe_dbproxy_performance_with_options(request, runtime)

        # Parse and analyze response
        if hasattr(response, 'body') and response.body:
            try:
                response_dict = response.to_map()
                
                if 'body' in response_dict:
                    body = response_dict['body']
                    
                    # Build structured response with analysis
                    time_range = {
                        "start": body.get('StartTime', corrected_start_time),
                        "end": body.get('EndTime', corrected_end_time),
                        "original_start": start_time,
                        "original_end": end_time
                    }
                    
                    # Parse performance data
                    performance_data = {
                        "cluster_id": body.get('DBClusterId', dbcluster_id),
                        "db_type": body.get('DBType', 'MySQL'),
                        "db_version": body.get('DBVersion', 'Unknown'),
                        "metrics": []
                    }
                    
                    # Process metrics
                    if 'PerformanceKeys' in body:
                        perf_keys = body['PerformanceKeys']
                        performance_items = perf_keys.get('PerformanceItem', [])
                        
                        if not isinstance(performance_items, list):
                            performance_items = [performance_items]

                        for item in performance_items:
                            metric_data = {
                                "measurement": item.get('Measurement', 'Unknown'),
                                "metric_name": item.get('MetricName', 'Unknown'),
                                "points": []
                            }

                            if 'Points' in item and 'PerformanceItemValue' in item['Points']:
                                points = item['Points']['PerformanceItemValue']

                                if not isinstance(points, list):
                                    points = [points]

                                for point in points:
                                    timestamp = point.get('Timestamp', 'N/A')
                                    value = point.get('Value', 'N/A')

                                    readable_time = 'N/A'
                                    if timestamp != 'N/A':
                                        try:
                                            timestamp_seconds = int(timestamp) / 1000
                                            readable_time = datetime.fromtimestamp(timestamp_seconds).strftime('%Y-%m-%d %H:%M:%S')
                                        except (ValueError, TypeError):
                                            readable_time = str(timestamp)

                                    metric_data["points"].append({
                                        "timestamp": readable_time,
                                        "value": value
                                    })
                            
                            performance_data["metrics"].append(metric_data)
                    
                    # Perform analysis
                    analysis = analyze_proxy_performance_data(performance_data, time_range)
                    
                    # Format comprehensive response
                    formatted_response = {
                        "status": "success",
                        "cluster_info": {
                            "cluster_id": performance_data["cluster_id"],
                            "db_type": performance_data["db_type"],
                            "db_version": performance_data["db_version"]
                        },
                        "time_range": time_range,
                        "request_info": {
                            "validated_key": validated_key,
                            "original_key": key,
                            "warnings": warnings,
                            "request_id": body.get('RequestId', 'N/A')
                        },
                        "performance_analysis": analysis,
                        "raw_metrics_count": len(performance_data["metrics"]),
                        "performance_type": "proxy"
                    }

                    import json
                    return [TextContent(type="text", text=json.dumps(formatted_response, indent=2, ensure_ascii=False))]
                else:
                    return [TextContent(type="text", text="❌ API响应格式错误: 缺少body部分")]
                        
            except Exception as parse_error:
                logger.error(f"解析代理性能响应错误: {str(parse_error)}")
                return [TextContent(type="text", text=f"❌ 解析响应数据失败: {str(parse_error)}")]
        else:
            return [TextContent(type="text", text=f"❌ 未收到API响应数据，集群ID: {dbcluster_id}")]

    except Exception as e:
        logger.error(f"调用代理性能API出错: {str(e)}")
        
        # Enhanced error response with troubleshooting info
        error_details = {
            "error": str(e),
            "cluster_id": dbcluster_id,
            "node_id": dbnode_id,
            "validated_key": validated_key,
            "time_info": {
                "original_start": start_time, 
                "original_end": end_time,
                "corrected_start": corrected_start_time if 'corrected_start_time' in locals() else "conversion_failed",
                "corrected_end": corrected_end_time if 'corrected_end_time' in locals() else "conversion_failed"
            },
            "warnings": warnings,
            "troubleshooting": [
                "检查集群ID是否正确",
                "检查节点ID是否正确且属于该集群",
                "确认时间范围是否合理（建议1-24小时范围）",
                "验证网络连接和API凭证",
                "确认集群已启用代理服务",
                "确认集群处于可访问状态"
            ]
        }
        
        import json
        return [TextContent(type="text", text=f"❌ 代理性能查询失败: {json.dumps(error_details, indent=2, ensure_ascii=False)}")]


def polardb_restart_db_node(arguments: dict) -> list[TextContent]:
    """Restart a specific PolarDB database node with comprehensive validation and monitoring guidance"""
    dbnode_id = arguments.get("dbnode_id")
    db_cluster_id = arguments.get("db_cluster_id")  # Optional but recommended for validation

    # Validate required parameters
    if not dbnode_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: DB Node ID is required")]

    # Validate dbnode_id format - must start with "pi-"
    if not dbnode_id.startswith("pi-"):
        return [TextContent(type="text", text=(
            f"❌ INVALID_NODE_ID_FORMAT: DB Node ID must start with 'pi-'\n"
            f"Provided: '{dbnode_id}'\n"
            f"Expected format: 'pi-xxxxxxxxxxxxxxxxx'\n\n"
            f"COMMON_MISTAKES:\n"
            f"• Using cluster ID (pc-xxxxx) instead of node ID (pi-xxxxx)\n"
            f"• Missing 'pi-' prefix\n"
            f"• Using incorrect resource type identifier\n\n"
            f"HOW_TO_FIND_CORRECT_NODE_ID:\n"
            f"1. Use polardb_describe_db_clusters to list clusters in your region\n"
            f"2. Use polardb_extract_node_ids to get node IDs from a cluster\n"
            f"3. Use polardb_describe_db_cluster to see all nodes in a specific cluster\n\n"
            f"EXAMPLE_VALID_NODE_IDS:\n"
            f"• pi-6nnp9h5z59l323jpf\n"
            f"• pi-1udn03901ed4u2i1e\n"
            f"• pi-abc123def456ghi789"
        ))]

    # Additional validation for node ID format
    if len(dbnode_id) < 5:  # "pi-" + at least 2 characters
        return [TextContent(type="text", text=(
            f"❌ INVALID_NODE_ID_LENGTH: DB Node ID appears too short\n"
            f"Provided: '{dbnode_id}' ({len(dbnode_id)} characters)\n"
            f"Expected: 'pi-' followed by alphanumeric identifier (typically 17+ characters total)\n"
            f"Example: 'pi-6nnp9h5z59l323jpf'"
        ))]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ CLIENT_ERROR: Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for restarting DB node
        request = polardb_20170801_models.RestartDBNodeRequest(
            dbnode_id=dbnode_id
        )

        # Add cluster ID if provided for better validation
        if db_cluster_id:
            request.dbcluster_id = db_cluster_id

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.restart_dbnode_with_options(request, runtime)

        # Format the response with comprehensive details
        if hasattr(response, 'body') and response.body:
            try:
                # Convert to dictionary for easier access
                response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                
                result = [
                    "=== POLARDB DATABASE NODE RESTART INITIATED ===",
                    f"🎯 TARGET_NODE: {dbnode_id}",
                    f"🔄 OPERATION_TYPE: Database Node Restart",
                    f"📅 TIMESTAMP: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    "=" * 60,
                    ""
                ]
                
                # Operation details
                result.extend([
                    "OPERATION_DETAILS:",
                    f"  NODE_ID: {dbnode_id}",
                    f"  NODE_TYPE: Database Node (Reader/Writer)",
                    f"  OPERATION_STATUS: ✅ RESTART_INITIATED",
                    f"  VALIDATION_STATUS: ✅ NODE_ID_FORMAT_VALID",
                ])
                
                if db_cluster_id:
                    result.append(f"  CLUSTER_ID: {db_cluster_id}")
                
                result.append("")
                
                # Node ID analysis
                result.extend([
                    "NODE_ID_ANALYSIS:",
                    f"  FORMAT_CHECK: ✅ Starts with 'pi-' (correct)",
                    f"  ID_LENGTH: {len(dbnode_id)} characters",
                    f"  ID_STRUCTURE: {dbnode_id[:3]}{'*' * (len(dbnode_id) - 6)}{dbnode_id[-3:] if len(dbnode_id) > 6 else ''}",
                    ""
                ])
                
                # Response details
                request_id = response_dict.get('RequestId', 'N/A')
                result.extend([
                    "API_RESPONSE_DETAILS:",
                    f"  REQUEST_ID: {request_id}",
                    f"  STATUS: ✅ SUCCESS",
                    f"  OPERATION: Node restart request submitted successfully",
                    f"  EXECUTION_MODE: Asynchronous (restart will proceed in background)",
                    ""
                ])
                
                # Restart process explanation
                result.extend([
                    "RESTART_PROCESS_EXPLANATION:",
                    f"  PHASE_1: 🔄 Graceful shutdown of database services",
                    f"  PHASE_2: ⏳ Brief downtime period (typically 1-3 minutes)",
                    f"  PHASE_3: 🚀 Database service restart and initialization",
                    f"  PHASE_4: 🔍 Health checks and service validation",
                    f"  PHASE_5: ✅ Node returns to active status",
                    "",
                    "ESTIMATED_DURATION:",
                    f"  • Typical restart time: 2-5 minutes",
                    f"  • Maximum expected time: 10 minutes",
                    f"  • Factors affecting duration: data volume, configuration complexity",
                    ""
                ])
                
                # Impact assessment
                result.extend([
                    "IMPACT_ASSESSMENT:",
                ])
                
                # Try to determine node role from ID pattern (this is best-effort)
                if "writer" in dbnode_id.lower() or any(pattern in dbnode_id for pattern in ["w", "primary"]):
                    node_role = "Writer (Primary)"
                    impact_level = "🔴 HIGH_IMPACT"
                    impact_desc = "Write operations will be unavailable during restart"
                elif "reader" in dbnode_id.lower() or any(pattern in dbnode_id for pattern in ["r", "readonly"]):
                    node_role = "Reader (Secondary)"
                    impact_level = "🟡 MEDIUM_IMPACT"
                    impact_desc = "Read load will be redistributed to other reader nodes"
                else:
                    node_role = "Unknown (check cluster configuration)"
                    impact_level = "⚠️ UNKNOWN_IMPACT"
                    impact_desc = "Impact depends on node role in cluster"
                
                result.extend([
                    f"  ESTIMATED_NODE_ROLE: {node_role}",
                    f"  IMPACT_LEVEL: {impact_level}",
                    f"  IMPACT_DESCRIPTION: {impact_desc}",
                    ""
                ])
                
                # Monitoring recommendations
                result.extend([
                    "MONITORING_RECOMMENDATIONS:",
                    f"  IMMEDIATE_ACTIONS:",
                    f"  1. Monitor node status using polardb_describe_db_cluster",
                    f"  2. Check application connection health",
                    f"  3. Verify no critical transactions are interrupted",
                    f"  4. Monitor cluster performance metrics",
                    "",
                    f"  STATUS_CHECK_COMMANDS:",
                    f"  • polardb_describe_db_cluster (check overall cluster health)",
                    f"  • polardb_describe_db_node_performance (monitor restart progress)",
                    f"  • polardb_describe_db_cluster_access_whitelist (verify connectivity)",
                    ""
                ])
                
                # Safety recommendations
                result.extend([
                    "SAFETY_RECOMMENDATIONS:",
                    f"  BEFORE_RESTART:",
                    f"  • Ensure no critical maintenance operations are running",
                    f"  • Verify backup status is current",
                    f"  • Confirm application can handle temporary node unavailability",
                    f"  • Notify relevant teams about planned restart",
                    "",
                    f"  DURING_RESTART:",
                    f"  • Monitor application error rates",
                    f"  • Watch for connection timeout issues",
                    f"  • Avoid starting other maintenance operations",
                    f"  • Keep monitoring dashboard open",
                    "",
                    f"  AFTER_RESTART:",
                    f"  • Verify node returns to healthy status",
                    f"  • Check application connectivity is restored",
                    f"  • Monitor performance metrics for anomalies",
                    f"  • Review any error logs generated during restart",
                    ""
                ])
                
                # Troubleshooting guide
                result.extend([
                    "TROUBLESHOOTING_GUIDE:",
                    f"  IF_RESTART_TAKES_TOO_LONG (>10 minutes):",
                    f"  • Check cluster status for any error conditions",
                    f"  • Verify no conflicting operations are running",
                    f"  • Contact Alibaba Cloud support if node remains unavailable",
                    "",
                    f"  IF_APPLICATIONS_CANNOT_RECONNECT:",
                    f"  • Verify connection strings point to cluster endpoint (not node-specific)",
                    f"  • Check access whitelist configuration",
                    f"  • Restart application connection pools",
                    f"  • Verify network connectivity to database",
                    ""
                ])
                
                # Best practices
                result.extend([
                    "RESTART_BEST_PRACTICES:",
                    f"  TIMING:",
                    f"  • Schedule restarts during low-traffic periods",
                    f"  • Avoid restarting multiple nodes simultaneously",
                    f"  • Consider maintenance windows for production environments",
                    "",
                    f"  PREPARATION:",
                    f"  • Ensure recent backups are available",
                    f"  • Test restart procedures in development environment first",
                    f"  • Have rollback plans ready if issues occur",
                    f"  • Coordinate with application teams",
                    ""
                ])
                
                # Final status
                result.extend([
                    "=" * 60,
                    f"✅ DATABASE NODE RESTART SUCCESSFULLY INITIATED",
                    f"Node: {dbnode_id}",
                    f"Request ID: {request_id}",
                    f"Expected completion: 2-5 minutes",
                    f"Monitor progress with: polardb_describe_db_cluster",
                    "=" * 60
                ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing restart node response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"NODE_RESTART_INITIATED: {dbnode_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed\n"
                    f"STATUS: Restart likely successful, but detailed analysis unavailable"
                ))]
        else:
            return [TextContent(type="text", text=f"⚠️  PARTIAL_SUCCESS: Node restart initiated but no response details received for node {dbnode_id}")]

    except Exception as e:
        logger.error(f"Error restarting PolarDB node: {str(e)}")
        
        # Provide helpful error context
        error_result = [
            f"❌ NODE_RESTART_FAILED",
            f"NODE: {dbnode_id}",
            f"ERROR: {str(e)}",
            "",
            "TROUBLESHOOTING_STEPS:",
            "• Verify node ID is correct and exists",
            "• Check if node ID starts with 'pi-' (not 'pc-')",
            "• Ensure node is in a restartable state (not already restarting)",
            "• Verify you have permission to restart database nodes",
            "• Check if cluster is not in maintenance mode",
            "• Verify network connectivity to Alibaba Cloud APIs",
            "",
            "NODE_ID_VALIDATION:",
            f"• Provided ID: '{dbnode_id}'",
            f"• Format check: {'✅ Valid' if dbnode_id.startswith('pi-') else '❌ Invalid - must start with pi-'}",
            f"• Length check: {'✅ Acceptable' if len(dbnode_id) >= 5 else '❌ Too short'}",
            "",
            "HOW_TO_FIND_CORRECT_NODE_ID:",
            "1. Use polardb_describe_db_clusters to find your cluster",
            "2. Use polardb_extract_node_ids with your cluster ID",
            "3. Use the correct pi-xxxxx node ID from the results",
            "",
            f"COMMON_MISTAKES:",
            f"• Using cluster ID (pc-xxxxx) instead of node ID (pi-xxxxx)",
            f"• Typos in the node ID",
            f"• Using deleted or non-existent node IDs",
        ]
        
        if db_cluster_id:
            error_result.append(f"• Cluster ID provided: {db_cluster_id}")
        
        return [TextContent(type="text", text="\n".join(error_result))]

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available PolarDB MySQL tools."""
    logger.info("Listing tools...")
    return [
        # polardb_smart_query might be FIRST tool in the list
        Tool(
            name="polardb_smart_query",
            description="""🤖 智能查询工具 - 支持自然语言查询PolarDB资源。可以理解中文和英文的自然语言指令，自动识别用户意图并执行相应操作。

支持的查询类型:
- 重启节点: "重启节点 pi-xxxxx" 或 "restart node pi-xxxxx"
- 集群性能: "获取集群 pc-xxxxx 的性能" 或 "get performance for cluster pc-xxxxx"  
- 节点性能: "获取节点 pi-xxxxx 的性能" 或 "get performance for node pi-xxxxx"
- 集群信息: "查看集群 pc-xxxxx 信息" 或 "describe cluster pc-xxxxx"
- 白名单查看: "查看集群 pc-xxxxx 的白名单" 或 "show whitelist for cluster pc-xxxxx"
- 节点提取: "提取集群 pc-xxxxx 的节点" 或 "extract nodes from cluster pc-xxxxx"

系统会自动识别用户意图，提取相关参数，并调用适当的工具执行操作。无需手动查找集群ID或设置复杂参数。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询，例如: '重启节点pi-1udu07821xcd49u02', '获取集群pc-123的性能', 'restart node pi-123', 'get performance for cluster pc-456' 等。支持中英文混合输入。"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="polardb_describe_regions",
            description="List all available regions for Alibaba Cloud PolarDB",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="polardb_describe_db_clusters",
            description="""List all PolarDB clusters in a specific region with comprehensive cluster details.
            
            Returns detailed information including:
            - Basic cluster info (ID, description, status, engine)
            - Resource specifications (CPU cores, memory, node class, storage)
            - Network configuration (VPC, VSwitch, Zone)
            - Database node details (Writer/Reader roles, node IDs, classes)
            - Storage usage and payment information
            
            This tool provides the foundation data needed for other cluster operations.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID to list clusters from (e.g., cn-hangzhou, cn-beijing, cn-shanghai)"
                    }
                },
                "required": ["region_id"]
            }
        ),
        Tool(
            name="polardb_describe_db_cluster",
            description="Get detailed information about a specific PolarDB cluster",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster"
                    }
                },
                "required": ["region_id", "db_cluster_id"]
            }
        ),
        Tool(
            name="polardb_extract_node_ids",
            description="Extract node IDs from a PolarDB cluster by role (reader/writer). Use this when you need to get node IDs for parameter queries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster"
                    },
                    "node_type": {
                        "type": "string",
                        "description": "Type of nodes to extract: 'reader', 'writer', or 'all' (default: 'all')",
                        "enum": ["reader", "writer", "all"]
                    }
                },
                "required": ["db_cluster_id"]
            }
        ),
        Tool(
            name="polardb_describe_available_resources",
            description="List available resources for creating PolarDB clusters",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID to list available resources from (e.g., cn-hangzhou)"
                    },
                    "zone_id": {
                        "type": "string",
                        "description": "Zone ID to list available resources from"
                    },
                    "db_type": {
                        "type": "string",
                        "description": "Database type (e.g., MySQL, PostgreSQL)"
                    },
                    "db_version": {
                        "type": "string",
                        "description": "Database version (e.g., 8.0, 5.7)"
                    },
                    "pay_type": {
                        "type": "string",
                        "description": "Payment type (e.g., Prepaid, Postpaid, default: Postpaid)"
                    }
                },
                "required": []
            }
        ),
        Tool(
           name="polardb_create_cluster",
            description="Create a new PolarDB cluster",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID where to create the cluster (e.g., cn-hangzhou)"
                    },
                    "dbtype": {
                        "type": "string",
                        "description": "Database type (e.g., MySQL, PostgreSQL)"
                    },
                    "dbversion": {
                        "type": "string",
                        "description": "Database version (e.g., 8.0, 5.7)"
                    },
                    "dbnode_class": {
                        "type": "string",
                        "description": "Instance class specification (e.g., polar.mysql.g1.tiny.c)"
                    },
                    "pay_type": {
                        "type": "string",
                        "description": "Payment type (Postpaid for pay-as-you-go, Prepaid for subscription)"
                    },
                    "storage_space": {
                        "type": "integer",
                        "description": "Storage space in GB (minimum 50)"
                    },
                    "zone_id": {
                        "type": "string",
                        "description": "Zone ID where to create the cluster"
                    },
                    "vpc_id": {
                        "type": "string",
                        "description": "VPC ID for the cluster"
                    },
                    "vswitch_id": {
                        "type": "string",
                        "description": "VSwitch ID for the cluster"
                    },
                    "db_cluster_description": {
                        "type": "string",
                        "description": "Description for the PolarDB cluster"
                    },
                    "resource_group_id": {
                        "type": "string",
                        "description": "Resource group ID"
                    },
                    "period": {
                        "type": "string",
                        "description": "Period for prepaid instances (Month/Year)"
                    },
                    "used_time": {
                        "type": "integer",
                        "description": "Used time for prepaid instances"
                    },
                    "client_token": {
                        "type": "string",
                        "description": "Idempotence token"
                    }
                },
                "required": ["dbnode_class"]
            }
        ),
        Tool(
            name="polardb_describe_db_node_parameters",
            description="Get configuration parameters for a specific PolarDB database node",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbnode_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB database node"
                    },
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster"
                    }
                },
                "required": ["dbnode_id", "db_cluster_id"]
            }
        ),
        Tool(
            name="polardb_modify_db_node_parameters",
            description="Modify configuration parameters for PolarDB database nodes",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster"
                    },
                    "dbnode_ids": {
                        "type": "string",
                        "description": "The IDs of the PolarDB database nodes, separate multiple values with commas"
                    },
                    "parameters": {
                        "type": "string",
                        "description": "Parameters to modify in JSON format, e.g., {\"wait_timeout\":\"86\",\"innodb_old_blocks_time\":\"10\"}"
                    }
                },
                "required": ["db_cluster_id", "dbnode_ids", "parameters"]
            }
        ),
        Tool(
            name="polardb_describe_slow_log_records",
            description="Get slow log records for a specific PolarDB cluster within a time range",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID where the cluster is located (e.g., cn-hangzhou)"
                    },
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster"
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Start time for slow log query in ISO 8601 format (e.g., 2025-05-28T16:00Z)"
                    },
                    "end_time": {
                        "type": "string",
                        "description": "End time for slow log query in ISO 8601 format (e.g., 2025-05-29T04:00Z)"
                    },
                    "node_id": {
                        "type": "string",
                        "description": "The ID of the database node (optional)"
                    },
                    "dbname": {
                        "type": "string",
                        "description": "Database name to filter slow logs (optional)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Number of records per page (default: 30, max: 2147483647)"
                    },
                    "page_number": {
                        "type": "integer",
                        "description": "Page number for pagination (default: 1)"
                    },
                    "sqlhash": {
                        "type": "string",
                        "description": "SQL hash to filter specific slow queries (optional)"
                    }
                },
                "required": ["region_id", "db_cluster_id", "start_time", "end_time"]
            }
        ),
        Tool(
            name="polardb_describe_db_node_performance",
            description=f"""Get performance metrics for a specific PolarDB database node within a time range.
    
            IMPORTANT TIME INFORMATION:
            - Current UTC time: {datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')}
            - Current date: {datetime.utcnow().strftime('%Y-%m-%d')}
            - Yesterday: {(datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')}
    
            VALID POLARDB MYSQL PERFORMANCE METRICS:
            - PolarDBCPU (CPU使用率)
            - PolarDBMemory (内存使用率) 
            - PolarDBDiskUsage (磁盘使用情况)
            - PolarDBConnection (数据库连接数)
            - PolarDBIOSTAT (IOPS统计)
            - PolarDBNetworkTraffic (网络流量)
            - PolarDBCOMDML (DML操作统计)
            - PolarDBInnoDBBufferRatio (InnoDB缓冲池命中率)
    
            Use correct dates and ONLY valid metrics!""",
             inputSchema={
                "type": "object",
                "properties": {
                    "dbnode_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB database node (e.g., pi-1udn03901ed4u2i1e)"
                    },
                    "key": {
                        "type": "string",
                        "description": f"Performance metrics to retrieve, comma-separated. ONLY use valid metrics: {', '.join(VALID_POLARDB_MYSQL_METRICS.keys())}. Example: 'PolarDBDiskUsage, PolarDBCPU, PolarDBMemory, PolarDBConnections, PolarDBIOSTAT'"
                    },
                    "start_time": {
                        "type": "string",
                        "description": f"Start time in ISO 8601 format. Current time: {datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')}. Yesterday: {(datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')}T00:00Z"
                    },
                    "end_time": {
                        "type": "string",
                        "description": f"End time in ISO 8601 format. Current time: {datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')}. Today: {datetime.utcnow().strftime('%Y-%m-%d')}T23:59Z"
                    },
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (optional, but recommended for better API compatibility)"
                    }
                },
                "required": ["dbnode_id", "key", "start_time", "end_time"]
            }
        ),
        Tool(
            name="polardb_tag_resources",
            description="Add tags to PolarDB resources (clusters, nodes, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID where the resources are located (e.g., cn-hangzhou, cn-shanghai)"
                    },
                    "resource_type": {
                        "type": "string",
                        "description": "Type of resource to tag (e.g., 'cluster')",
                        "enum": ["cluster"]
                    },
                    "resource_ids": {
                        "type": ["string", "array"],
                        "description": "Resource ID(s) to tag. Can be a single ID string or comma-separated string, or array of IDs",
                        "items": {
                            "type": "string"
                        }
                    },
                    "tags": {
                        "type": ["array", "object"],
                        "description": "Tags to apply. Can be array of {key, value} objects or a simple key-value object",
                        "oneOf": [
                            {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "key": {"type": "string"},
                                        "value": {"type": "string"}
                                    },
                                    "required": ["key", "value"]
                                }
                            },
                            {
                                "type": "object",
                                "additionalProperties": {"type": "string"}
                            }
                        ]
                    }
                },
                "required": ["region_id", "resource_type", "resource_ids", "tags"]
            }
        ),
        Tool(
            name="polardb_create_db_endpoint_address",
            description="Create a new database endpoint address for a PolarDB cluster",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbcluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    },
                    "net_type": {
                        "type": "string",
                        "description": "Network type for the endpoint",
                        "enum": ["Public", "Private", "Inner"]
                    },
                    "dbendpoint_id": {
                        "type": "string",
                        "description": "The ID of the database endpoint (e.g., pe-6nn5trlkr263c0uce)"
                    }
                },
                "required": ["dbcluster_id", "net_type", "dbendpoint_id"]
            }
        ),
        Tool(
            name="polardb_create_account",
            description="Create a database account for a PolarDB cluster with specified privileges",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbcluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Database account name (2-16 characters, alphanumeric and underscore only)"
                    },
                    "account_password": {
                        "type": "string",
                        "description": "Account password (8-32 characters, must contain uppercase, lowercase, number, and special character)"
                    },
                    "account_type": {
                        "type": "string",
                        "description": "Account type (optional, default: 'Super')",
                        "enum": ["Normal", "Super"],
                        "default": "Super"
                    },
                    "account_description": {
                        "type": "string",
                        "description": "Description of the account (optional, max 256 characters)"
                    },
                    "db_name": {
                        "type": "string",
                        "description": "Database name to grant access to (optional, for Normal accounts)"
                    },
                    "account_privilege": {
                        "type": "string",
                        "description": "Privilege level for the specified database (optional, default: 'ReadWrite')",
                        "enum": ["ReadWrite", "ReadOnly", "DMLOnly", "DDLOnly", "ReadIndex"],
                        "default": "ReadWrite"
                    }
                },
                "required": ["dbcluster_id", "account_name", "account_password"]
            }
        ),
        Tool(
            name="polardb_describe_db_cluster_access_whitelist",
            description="Get the CURRENT ACTIVE access whitelist configuration for a PolarDB cluster. Returns structured data with explicit interpretation of each IP address. Response format prevents misinterpretation: if 0.0.0.0/0 is configured, it will explicitly state 'OPEN_TO_ALL_INTERNET'; if 127.0.0.1 is configured, it will explicitly state 'LOCALHOST_ONLY'. The response shows the actual current settings, not recommendations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbcluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    }
                },
                "required": ["dbcluster_id"]
            }
        ),
        Tool(
            name="polardb_describe_accounts",
            description="List database accounts for a PolarDB cluster, including account types, status, and database privileges",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbcluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    },
                    "account_name": {
                        "type": "string",
                        "description": "Optional: Filter by specific account name to get details for a single account"
                    }
                },
                "required": ["dbcluster_id"]
            }
        ),
        Tool(
            name="polardb_describe_databases",
            description="List databases in a specific PolarDB cluster, optionally filtered by database name",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    },
                    "db_name": {
                        "type": "string",
                        "description": "Optional: Specific database name to describe (e.g., 'information_schema', 'mysql'). If not provided, lists all databases in the cluster"
                    },
                    "page_number": {
                        "type": "integer",
                        "description": "Page number for pagination (optional, default: 1)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Number of records per page (optional, default: 30)"
                    }
                },
                "required": ["db_cluster_id"]
            }
        ),
        Tool(
            name="polardb_describe_db_cluster_endpoints",
            description="List database endpoints for a specific PolarDB cluster, including connection strings, IP addresses, and endpoint configurations",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    }
                },
                "required": ["db_cluster_id"]
            }
        ),
        Tool(
            name="polardb_describe_db_cluster_parameters",
            description="Get configuration parameters for a PolarDB cluster, organized by category with important parameters highlighted",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    }
                },
                "required": ["db_cluster_id"]
            }
        ),
        Tool(
            name="polardb_describe_db_cluster_performance",
            description=f"""获取PolarDB集群在指定时间范围内的性能指标数据，支持多种性能指标分析。

重要提示：
- 当前北京时间: {datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')}
- 系统会自动将输入时间转换为北京时间进行查询
- 每次请求最多支持5个性能指标
- 建议查询时间范围：1-24小时

可用的性能指标 (最多选择5个):
核心指标: PolarDBDiskUsage(磁盘), PolarDBCPU(CPU), PolarDBMemory(内存), PolarDBConnections(连接), PolarDBIOSTAT(IOPS)
扩展指标: PolarDBQPSTPS(查询统计), PolarDBNetworkTraffic(网络), PolarDBInnoDBBufferRatio(缓冲池), PolarDBInnoDBDataReadWrite(数据读写), PolarDBInnoDBBufferRequests(缓冲池请求), PolarDBInnoDBLogWrites(日志写入), PolarDBCOMDML(DML操作), PolarDBRowDML(行DML), PolarDBReplicaLag(副本延迟)

系统将自动进行性能分析并提供优化建议。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "PolarDB集群ID (例如: pc-1udt379icjl5032b1)"
                    },
                    "key": {
                        "type": "string", 
                        "description": f"性能指标，逗号分隔，最多5个。不提供则使用默认指标。有效指标: {', '.join(VALID_POLARDB_MYSQL_METRICS.keys())}。示例: 'PolarDBDiskUsage, PolarDBCPU, PolarDBMemory'"
                    },
                    "start_time": {
                        "type": "string",
                        "description": f"开始时间 (支持多种格式)。当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。示例: '2025-07-10 09:00:00' 或 '2025-07-10T01:00Z'"
                    },
                    "end_time": {
                        "type": "string",
                        "description": f"结束时间 (支持多种格式)。当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。示例: '2025-07-10 10:00:00' 或 '2025-07-10T02:00Z'"
                    }
                },
                "required": ["db_cluster_id", "start_time", "end_time"]
            }
        ),
        Tool(
            name="polardb_describe_global_security_ipgroup_relation",
            description="""Get global security IP group relations for a specific PolarDB cluster.
            
            Global security IP groups provide centralized IP whitelist management that can be shared 
            across multiple PolarDB clusters. This tool shows which global groups are associated 
            with a cluster and analyzes their security configurations.
            
            Returns detailed information including:
            - Global security group names and IDs
            - IP addresses configured in each global group
            - Security risk assessment for each IP range
            - Recommendations for security improvements
            - Relationship between global and local IP configurations""",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID where the cluster is located (e.g., cn-hangzhou, cn-beijing, cn-shanghai)"
                    },
                    "dbcluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-1udt379icjl5032b1)"
                    }
                },
                "required": ["region_id", "dbcluster_id"]
            }
        ),
        Tool(
            name="vpc_describe_vpcs",
            description="List all VPCs (Virtual Private Clouds) in a specific region with detailed network configuration information",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID to list VPCs from (e.g., cn-hangzhou, cn-beijing, cn-shanghai). Default: cn-hangzhou"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="vpc_describe_vswitches",
            description="List all VSwitches (Virtual Switches) in a specific region with detailed subnet configuration information",
            inputSchema={
                "type": "object",
                "properties": {
                    "region_id": {
                        "type": "string",
                        "description": "Region ID to list VSwitches from (e.g., cn-hangzhou, cn-beijing, cn-shanghai). Default: cn-hangzhou"
                    },
                    "vpc_id": {
                        "type": "string",
                        "description": "Optional: VPC ID to filter VSwitches (e.g., vpc-bp1awijx0p7r8tnhk49iy)"
                    },
                    "zone_id": {
                        "type": "string",
                        "description": "Optional: Zone ID to filter VSwitches (e.g., cn-hangzhou-j, cn-hangzhou-k)"
                    },
                    "vswitch_id": {
                        "type": "string",
                        "description": "Optional: Specific VSwitch ID to describe (e.g., vsw-bp1l2aim43gvyuozzab9o)"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="polardb_modify_db_cluster_access_whitelist",
            description="Modify the access whitelist for a PolarDB cluster to control which IP addresses can connect. Supports Cover (replace), Append (add), and Delete (remove) modes for flexible IP management.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbcluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    },
                    "white_list_type": {
                        "type": "string",
                        "description": "Type of whitelist to modify (optional, default: 'IP'). 'IP' for IP address-based access control, 'SecurityGroup' for ECS security group-based access control",
                        "enum": ["IP", "SecurityGroup"],
                        "default": "IP"
                    },
                    "security_ips": {
                        "type": "string",
                        "description": "IP addresses or CIDR blocks allowed to access the cluster. Use comma-separated values for multiple IPs. Examples: '192.168.1.1', '192.168.1.1,10.0.0.1', '192.168.1.0/24', '0.0.0.0/0' (for all IPs - not recommended)"
                    },
                    "db_cluster_iparray_name": {
                        "type": "string",
                        "description": "Name of the IP array group (optional, default is 'default'). Use different names to manage multiple IP groups"
                    },
                    "modify_mode": {
                        "type": "string",
                        "description": "How to modify the whitelist. Default: 'Cover'",
                        "enum": ["Cover", "Append", "Delete"],
                        "default": "Cover"
                    },
                    "security_group_ids": {
                        "type": "string",
                        "description": "Security group IDs for ECS-based access control (optional, comma-separated). Alternative to IP-based access control"
                    }
                },
                "required": ["dbcluster_id", "security_ips"]
            }
        ),
        Tool(
            name="polardb_modify_db_cluster_description",
            description="Modify the description of a PolarDB cluster with comprehensive validation and formatting guidelines. Helps organize and document cluster purposes with proper content validation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbcluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    },
                    "dbcluster_description": {
                        "type": "string",
                        "description": "New description for the cluster (2-256 characters). Cannot start with 'http://' or 'https://'. Should be descriptive and meaningful for cluster identification and management purposes.",
                        "minLength": 2,
                        "maxLength": 256
                    }
                },
                "required": ["dbcluster_id", "dbcluster_description"]
            }
        ),
        Tool(
            name="polardb_restart_db_node",
            description="Restart a specific PolarDB database node with comprehensive monitoring guidance and safety recommendations. Includes detailed validation and impact assessment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbnode_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB database node to restart. Must start with 'pi-' (e.g., 'pi-6nnp9h5z59l323jpf'). Do NOT use cluster IDs that start with 'pc-'. Use polardb_extract_node_ids or polardb_describe_db_cluster to find correct node IDs.",
                        "pattern": "^pi-[a-zA-Z0-9]+$"
                    },
                    "db_cluster_id": {
                        "type": "string",
                        "description": "Optional: The ID of the PolarDB cluster that contains the node (e.g., 'pc-6nnupu6o754068f16'). Recommended for additional validation and context."
                    }
                },
                "required": ["dbnode_id"]
            }
        ),
         Tool(
            name="polardb_modify_db_cluster_parameters",
            description="Modify configuration parameters for PolarDB cluster",
            inputSchema={
                "type": "object",
                "properties": {
                    "db_cluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster"
                    },
                    "parameters": {
                        "type": "string",
                        "description": "Parameters to modify in JSON format"
                    }
                },
                "required": ["db_cluster_id", "parameters"]
            }
        ),
        Tool(
            name="polardb_describe_db_cluster_connectivity",
            description="Test network connectivity to a PolarDB cluster from a specific source IP address. This tool validates whether the source IP can successfully connect to the cluster, checking network reachability and access whitelist configuration. Essential for troubleshooting connection issues and verifying security settings.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbcluster_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster to test connectivity to. Must start with 'pc-' (e.g., 'pc-1udt379icjl5032b1'). Do NOT use node IDs that start with 'pi-'. Use polardb_describe_db_clusters to find correct cluster IDs if unsure.",
                        "pattern": "^pc-[a-zA-Z0-9]+$"
                    },
                    "source_ip_address": {
                        "type": "string",
                        "description": "The source IP address to test connectivity from. Must be a valid IPv4 address format (e.g., '192.168.1.100', '10.0.0.50'). This should be the IP address of the machine or network that needs to connect to the database cluster.",
                        "pattern": "^(\\d{1,3}\\.){3}\\d{1,3}$"
                    }
                },
                "required": ["dbcluster_id", "source_ip_address"]
            }
        ),
        Tool(
            name="polardb_describe_db_proxy_performance",
            description=f"""获取PolarDB集群代理(Proxy)在指定时间范围内的性能指标数据，支持多种代理性能指标分析。

重要提示：
- 当前北京时间: {datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')}
- 系统会自动将输入时间转换为北京时间进行查询
- 每次请求最多支持5个性能指标
- 建议查询时间范围：1-24小时

可用的代理性能指标 (最多选择5个):
核心指标: PolarProxy_CurrentConns(当前连接), PolarProxy_DBConns(数据库连接), PolarProxy_DBActionOps(操作次数)
扩展指标: PolarProxy_CPU(CPU使用率), PolarProxy_Memory(内存使用率), PolarProxy_NetworkIn(输入流量), PolarProxy_NetworkOut(输出流量), PolarProxy_QPS(每秒查询), PolarProxy_TPS(每秒事务), PolarProxy_AvgResponseTime(响应时间), PolarProxy_SlowQueries(慢查询), PolarProxy_ConnectionPool(连接池), PolarProxy_ThreadPool(线程池)

系统将自动进行性能分析并提供优化建议。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "dbcluster_id": {
                        "type": "string",
                        "description": "PolarDB集群ID (例如: pc-1udt379icjl5032b1)"
                    },
                    "dbnode_id": {
                        "type": "string",
                        "description": "PolarDB数据库节点ID (例如: pi-1udt379icjl5032b1)"
                    },
                    "key": {
                        "type": "string", 
                        "description": f"代理性能指标，逗号分隔，最多5个。有效指标: {', '.join(VALID_POLARDB_PROXY_METRICS.keys())}。示例: 'PolarProxy_CurrentConns, PolarProxy_DBConns, PolarProxy_DBActionOps'"
                    },
                    "start_time": {
                        "type": "string",
                        "description": f"开始时间 (支持多种格式)。当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。示例: '2025-07-10 09:00:00' 或 '2025-07-10T01:00Z'"
                    },
                    "end_time": {
                        "type": "string",
                        "description": f"结束时间 (支持多种格式)。当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。示例: '2025-07-10 10:00:00' 或 '2025-07-10T02:00Z'"
                    }
                },
                "required": ["dbcluster_id", "dbnode_id", "start_time", "end_time"]
            }
        ),
        Tool(
            name="polardb_describe_error_log_records",
            description="Get error log records for a specific PolarDB cluster/instance within a time range using DAS API. Helps identify database errors, connection issues, and server problems.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instance_id": {
                        "type": "string",
                        "description": "The ID of the PolarDB cluster (e.g., pc-6nnupu6o754068f16)"
                    },
                    "start_time": {
                        "type": ["integer", "string"],
                        "description": "Start time for error log query. Can be Unix timestamp in seconds/milliseconds (e.g., 1752590400) or ISO format string (e.g., '2025-07-11T20:50Z')"
                    },
                    "end_time": {
                        "type": ["integer", "string"],
                        "description": "End time for error log query. Can be Unix timestamp in seconds/milliseconds (e.g., 1753309143) or ISO format string (e.g., '2025-07-12T22:50Z')"
                    },
                    "node_id": {
                        "type": "string",
                        "description": "The ID of the database node (required, e.g., pi-6nn73sf067du4tto7)"
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "Number of records per page (optional, default: 10, max: 100)"
                    },
                    "page_number": {
                        "type": "integer",
                        "description": "Page number for pagination (optional, default: 1)"
                    }
                },
                "required": ["instance_id", "start_time", "end_time", "node_id"]
            }
        )
    ]

def get_guidance_tool():
    """Get the guidance tool definition"""
    return Tool(
        name="polardb_get_guidance",
        description="Get intelligent, context-aware guidance for PolarDB operations",
        inputSchema={
            "type": "object",
            "properties": {
                "operation_type": {
                    "type": "string", 
                    "description": "Type of operation: cluster_search, performance, node_operations, region_search, cluster_creation, general"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context or specific questions about the operation"
                }
            },
            "required": []
        }
    )

def polardb_describe_regions() -> list[TextContent]:
    """List all available regions for Alibaba Cloud PolarDB"""
    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    # Create the request model for DescribeRegions
    describe_regions_request = polardb_20170801_models.DescribeRegionsRequest()
    runtime = util_models.RuntimeOptions()

    try:
        # Call the API to get the regions list
        response = client.describe_regions_with_options(describe_regions_request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'regions') and response.body.regions:
            regions_info = []
            for region in response.body.regions.region:
                # Extract zone IDs from the Zones.Zone list
                zone_ids = []
                if hasattr(region, 'zones') and region.zones and hasattr(region.zones, 'zone'):
                    for zone in region.zones.zone:
                        if hasattr(zone, 'zone_id'):
                            zone_ids.append(zone.zone_id)

                regions_info.append(f"Region ID: {region.region_id}, Zones: {', '.join(zone_ids)}")
            return [TextContent(type="text", text="\n".join(regions_info))]
        else:
            return [TextContent(type="text", text="No regions found or empty response")]

    except Exception as e:
        logger.error(f"Error describing PolarDB regions: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving regions: {str(e)}")]

def polardb_describe_db_clusters(arguments: dict) -> list[TextContent]:
    """List all PolarDB clusters in a specific region with improved parsing based on actual API response"""
    region_id = arguments.get("region_id")
    if not region_id:
        return [TextContent(type="text", text="Region ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing DB clusters
        request = polardb_20170801_models.DescribeDBClustersRequest(
            region_id=region_id
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbclusters_with_options(request, runtime)
        
        clusters_info = []
        cluster_count = 0

        # Parse the response based on the actual structure from your sample
        try:
            # The response.body should contain the data similar to your sample output
            if hasattr(response, 'body') and response.body:
                # Convert to dictionary for easier access
                response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                
                # Based on your sample output, the structure should be:
                # {'Items': {'DBCluster': [cluster1, cluster2, ...]}, 'PageNumber': 1, 'PageRecordCount': 2, ...}
                
                if 'Items' in response_dict and response_dict['Items']:
                    items = response_dict['Items']
                    
                    # Check if DBCluster exists in Items
                    if 'DBCluster' in items and items['DBCluster']:
                        clusters_data = items['DBCluster']
                        
                        # Ensure it's a list
                        if not isinstance(clusters_data, list):
                            clusters_data = [clusters_data]
                        
                        cluster_count = len(clusters_data)
                        
                        # Process each cluster
                        for i, cluster in enumerate(clusters_data, 1):
                            # Extract cluster information based on your sample structure
                            cluster_id = cluster.get('DBClusterId', 'N/A')
                            description = cluster.get('DBClusterDescription', 'N/A')
                            status = cluster.get('DBClusterStatus', 'N/A')
                            engine = cluster.get('Engine', 'N/A')
                            db_type = cluster.get('DBType', 'N/A')
                            db_version = cluster.get('DBVersion', 'N/A')
                            create_time = cluster.get('CreateTime', 'N/A')
                            category = cluster.get('Category', 'N/A')
                            sub_category = cluster.get('SubCategory', 'N/A')
                            cpu_cores = cluster.get('CpuCores', 'N/A')
                            memory_size = cluster.get('MemorySize', 'N/A')
                            db_node_class = cluster.get('DBNodeClass', 'N/A')
                            db_node_number = cluster.get('DBNodeNumber', 'N/A')
                            storage_type = cluster.get('StorageType', 'N/A')
                            storage_used = cluster.get('StorageUsed', 0)
                            pay_type = cluster.get('PayType', 'N/A')
                            vpc_id = cluster.get('VpcId', 'N/A')
                            vswitch_id = cluster.get('VswitchId', 'N/A')
                            zone_id = cluster.get('ZoneId', 'N/A')
                            region_id_cluster = cluster.get('RegionId', 'N/A')
                            
                            # Convert storage from bytes to GB for readability
                            storage_gb = round(storage_used / (1024**3), 2) if storage_used else 0
                            
                            # Extract DB Nodes information
                            db_nodes_info = []
                            if 'DBNodes' in cluster and cluster['DBNodes']:
                                db_nodes = cluster['DBNodes']
                                if 'DBNode' in db_nodes and db_nodes['DBNode']:
                                    nodes = db_nodes['DBNode']
                                    if not isinstance(nodes, list):
                                        nodes = [nodes]
                                    
                                    for node in nodes:
                                        node_id = node.get('DBNodeId', 'N/A')
                                        node_role = node.get('DBNodeRole', 'N/A')
                                        node_class = node.get('DBNodeClass', 'N/A')
                                        node_zone = node.get('ZoneId', 'N/A')
                                        hot_replica = node.get('HotReplicaMode', 'N/A')
                                        imci_switch = node.get('ImciSwitch', 'N/A')
                                        
                                        db_nodes_info.append(
                                            f"    Node ID: {node_id}\n"
                                            f"    Role: {node_role}\n"
                                            f"    Class: {node_class}\n"
                                            f"    Zone: {node_zone}\n"
                                            f"    Hot Replica: {hot_replica}\n"
                                            f"    IMCI Switch: {imci_switch}"
                                        )
                            
                            # Build comprehensive cluster information
                            cluster_info = [
                                f"CLUSTER #{i} of {cluster_count}:",
                                f"  Cluster ID: {cluster_id}",
                                f"  Description: {description}",
                                f"  Status: {status}",
                                f"  Engine: {engine} ({db_type} {db_version})",
                                f"  Created: {create_time}",
                                f"  Region: {region_id_cluster}",
                                f"  Zone: {zone_id}",
                                "",
                                f"  Category: {category} ({sub_category})",
                                f"  Node Class: {db_node_class}",
                                f"  CPU Cores: {cpu_cores}",
                                f"  Memory: {memory_size} MB",
                                f"  Nodes: {db_node_number}",
                                "",
                                f"  Storage Type: {storage_type}",
                                f"  Storage Used: {storage_gb} GB ({storage_used} bytes)",
                                f"  Payment Type: {pay_type}",
                                "",
                                f"  VPC ID: {vpc_id}",
                                f"  VSwitch ID: {vswitch_id}",
                                ""
                            ]
                            
                            # Add node details if available
                            if db_nodes_info:
                                cluster_info.extend([
                                    f"  Database Nodes ({len(db_nodes_info)}):",
                                    *db_nodes_info,
                                    ""
                                ])
                            
                            cluster_info.append("=" * 60)
                            clusters_info.extend(cluster_info)
                
                # Add pagination and summary information
                page_number = response_dict.get('PageNumber', 'N/A')
                page_record_count = response_dict.get('PageRecordCount', 'N/A')
                total_record_count = response_dict.get('TotalRecordCount', 'N/A')
                request_id = response_dict.get('RequestId', 'N/A')

        except Exception as parse_error:
            logger.error(f"Error parsing response for {region_id}: {str(parse_error)}")
            return [TextContent(type="text", text=f"❌ Error parsing response: {str(parse_error)}")]

        # Build the final response
        if clusters_info and cluster_count > 0:
            # Create summary header
            summary_header = [
                f"📊 POLARDB CLUSTERS IN {region_id.upper()}:",
                f"Total clusters found: {cluster_count}",
                f"Page: {page_number}, Records on page: {page_record_count}",
                f"Total records: {total_record_count}",
                f"Request ID: {request_id}",
                "=" * 70,
                ""
            ]
            
            # Create footer with cluster IDs
            cluster_ids = []
            for info in clusters_info:
                if "Cluster ID:" in info:
                    cluster_id = info.split("Cluster ID:")[1].strip()
                    cluster_ids.append(cluster_id)
            
            summary_footer = [
                "",
                "=" * 70,
                f"✅ SUMMARY: {cluster_count} PolarDB clusters in {region_id}",
                f"Cluster IDs: {', '.join(cluster_ids)}" if cluster_ids else "No cluster IDs extracted"
            ]
            
            full_response = "\n".join(summary_header + clusters_info + summary_footer)
            return [TextContent(type="text", text=full_response)]
        else:
            # No clusters found - provide detailed debugging info
            debug_info = [
                f"❌ NO CLUSTERS FOUND in {region_id}",
                "",
                "🔍 RESPONSE ANALYSIS:"
            ]
            
            try:
                # Add response structure for debugging
                if hasattr(response, 'body') and response.body:
                    response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                    
                    debug_info.extend([
                        f"Response keys: {list(response_dict.keys())}",
                        f"Items exists: {'Items' in response_dict}",
                        f"Page info: Page {response_dict.get('PageNumber', 'N/A')}, "
                        f"Records {response_dict.get('PageRecordCount', 'N/A')}/{response_dict.get('TotalRecordCount', 'N/A')}",
                        f"Request ID: {response_dict.get('RequestId', 'N/A')}"
                    ])
                    
                    if 'Items' in response_dict:
                        items = response_dict['Items']
                        debug_info.append(f"Items structure: {list(items.keys()) if isinstance(items, dict) else type(items)}")
                        
                        if isinstance(items, dict) and 'DBCluster' in items:
                            debug_info.append(f"DBCluster type: {type(items['DBCluster'])}")
                            debug_info.append(f"DBCluster length: {len(items['DBCluster']) if items['DBCluster'] else 0}")
                else:
                    debug_info.append("No response body received")
                    
            except Exception as debug_error:
                debug_info.append(f"Debug error: {str(debug_error)}")
            
            return [TextContent(type="text", text="\n".join(debug_info))]

    except Exception as e:
        logger.error(f"Error retrieving clusters from {region_id}: {str(e)}")
        return [TextContent(type="text", text=f"❌ ERROR retrieving clusters from {region_id}: {str(e)}")]

def enhanced_polardb_describe_db_clusters_with_explicit_count(arguments: dict) -> list[TextContent]:
    """Enhanced version with priority guidance and explicit counting using updated parsing"""
    
    region_id = arguments.get("region_id")
    priority_regions = {"cn-hangzhou": 3, "cn-beijing": 1, "cn-shanghai": 2}
    is_priority = region_id in priority_regions
    
    # Call the updated function
    result = polardb_describe_db_clusters(arguments)
    
    if result and len(result) > 0:
        original_text = result[0].text
        
        # Extract cluster count from the updated response format
        cluster_count = original_text.count("CLUSTER #")  # Updated counting method
        expected_count = priority_regions.get(region_id, 0)
        
        # Build enhanced response with priority context
        if cluster_count > 0:
            if is_priority:
                count_summary = (
                    f"🎯 PRIORITY REGION: {region_id.upper()}\n"
                    f"📊 EXPLICIT COUNT: Found {cluster_count} clusters\n"
                    f"Expected: {expected_count}\n"
                    f"Status: {'✅ CORRECT' if cluster_count == expected_count else '⚠️ MISMATCH'}\n"
                    f"Priority ranking: {'1st' if region_id == 'cn-hangzhou' else '2nd' if region_id == 'cn-shanghai' else '3rd'}\n"
                    f"{'='*70}\n\n"
                )
            else:
                count_summary = (
                    f"📍 STANDARD REGION: {region_id.upper()}\n"
                    f"📊 EXPLICIT COUNT: Found {cluster_count} clusters\n"
                    f"{'='*70}\n\n"
                )
                
            enhanced_text = count_summary + original_text
            
            # Add priority-specific guidance
            if is_priority:
                priority_footer = (
                    f"\n{'='*70}\n"
                    f"✅ PRIORITY REGION COMPLETED: {region_id}\n"
                    f"Clusters confirmed: {cluster_count}/{expected_count}\n"
                    f"Next priority regions to check: {get_remaining_priority_regions(region_id)}\n"
                )
                enhanced_text += priority_footer
                
        else:
            # No clusters found
            if is_priority:
                enhanced_text = (
                    f"❌ CRITICAL: NO CLUSTERS in PRIORITY REGION {region_id.upper()}\n"
                    f"Expected: {expected_count} clusters\n"
                    f"This indicates a parsing issue since clusters should exist here!\n"
                    f"{'='*70}\n\n" + original_text
                )
            else:
                enhanced_text = f"📍 No clusters in {region_id.upper()}\n\n" + original_text
                
        return [TextContent(type="text", text=enhanced_text)]
    
    return result

def get_remaining_priority_regions(current_region: str) -> str:
    """Get list of remaining priority regions to check"""
    priority_order = ["cn-hangzhou", "cn-shanghai", "cn-beijing"]
    
    try:
        current_index = priority_order.index(current_region)
        remaining = priority_order[current_index + 1:]
        return ", ".join(remaining) if remaining else "All priority regions checked"
    except ValueError:
        return "cn-hangzhou, cn-shanghai, cn-beijing"

# Enhanced guidance system that promotes priority search
class PrioritySearchGuidance:
    def __init__(self):
        self.priority_regions = ["cn-hangzhou", "cn-shanghai", "cn-beijing"]
        self.expected_counts = {"cn-hangzhou": 3, "cn-shanghai": 2, "cn-beijing": 1}
        self.regions_checked = []
        self.clusters_found = {}
    
    def add_region_result(self, region_id: str, cluster_count: int):
        """Track region search results"""
        self.regions_checked.append(region_id)
        self.clusters_found[region_id] = cluster_count
    
    def get_next_priority_region(self) -> str:
        """Get the next priority region to check"""
        for region in self.priority_regions:
            if region not in self.regions_checked:
                return region
        return None
    
    def generate_search_guidance(self, current_region: str = None) -> str:
        """Generate guidance for systematic priority search"""
        
        if not current_region:
            return (
                "🎯 PRIORITY SEARCH STRATEGY:\n"
                "Search these regions in order:\n"
                "1. cn-hangzhou (expect 3 clusters)\n"
                "2. cn-shanghai (expect 2 clusters)\n"
                "3. cn-beijing (expect 1 cluster)\n"
                "Total expected: 6 clusters\n"
            )
        
        guidance = [f"📍 Current region: {current_region}"]
        
        if current_region in self.priority_regions:
            remaining = self.get_remaining_priority_regions(current_region)
            guidance.append(f"🎯 Priority region status: {remaining}")
        
        # Show progress
        if self.regions_checked:
            total_found = sum(self.clusters_found.values())
            guidance.append(f"📊 Progress: {total_found} clusters found so far")
        
        return "\n".join(guidance)

# Global guidance instance
priority_guidance = PrioritySearchGuidance()


def polardb_describe_db_cluster(arguments: dict) -> list[TextContent]:
    """Get detailed information about a specific PolarDB cluster - minimal version focused on node IDs"""
    db_cluster_id = arguments.get("db_cluster_id")
    if not db_cluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing a specific DB cluster
        request = polardb_20170801_models.DescribeDBClusterAttributeRequest(
            dbcluster_id=db_cluster_id
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbcluster_attribute_with_options(request, runtime)
        
        # Use to_map() to get the response as a dictionary
        response_dict = response.to_map()
        
        if not response_dict or 'body' not in response_dict:
            return [TextContent(type="text", text=f"No response received for cluster {db_cluster_id}")]
        
        body = response_dict['body']
        
        # Extract and categorize nodes first
        db_nodes = body.get('DBNodes', [])
        writer_nodes = []
        reader_nodes = []
        
        for node in db_nodes:
            role = node.get('DBNodeRole', '').lower()
            if 'writer' in role:
                writer_nodes.append(node)
            elif 'reader' in role:
                reader_nodes.append(node)
        
        # ULTRA MINIMAL RESPONSE - ONLY CRITICAL INFO
        cluster_info = []
        
        # Get the actual node IDs
        reader_id = reader_nodes[0].get('DBNodeId') if reader_nodes else None
        writer_id = writer_nodes[0].get('DBNodeId') if writer_nodes else None
        
        cluster_info.extend([
            f"CLUSTER: {db_cluster_id}",
            f"STATUS: {body.get('DBClusterStatus', 'N/A')}",
            f"NODES: {len(db_nodes)} total",
            ""
        ])
        
        if reader_id:
            cluster_info.extend([
                f"READER_NODE_ID: {reader_id}",
                f"READER_STATUS: {reader_nodes[0].get('DBNodeStatus', 'N/A')}",
                ""
            ])
        
        if writer_id:
            cluster_info.extend([
                f"WRITER_NODE_ID: {writer_id}",
                f"WRITER_STATUS: {writer_nodes[0].get('DBNodeStatus', 'N/A')}",
                ""
            ])
        
        # CRITICAL INSTRUCTIONS - VERY SHORT
        cluster_info.extend([
            f"TO_GET_READER_PARAMETERS:",
            f"  polardb_describe_db_node_parameters",
            f"  db_cluster_id: {db_cluster_id}",
            f"  dbnode_id: {reader_id}" if reader_id else "  NO_READER_NODES",
            ""
        ])
        
        # Add minimal additional details that were requested
        cluster_info.extend([
            f"DETAILS:",
            f"Engine: {body.get('Engine', 'N/A')} {body.get('DBVersion', 'N/A')}",
            f"Region: {body.get('RegionId', 'N/A')}",
            f"Created: {body.get('CreationTime', 'N/A')}",
            f"VPC: {body.get('VPCId', 'N/A')}",
            f"Storage_Used_GB: {float(body.get('StorageUsed', 0)) / (1024**3):.2f}" if body.get('StorageUsed') else "Storage_Used_GB: 0",
            ""
        ])
        
        # Node details - very concise
        if reader_nodes:
            cluster_info.extend([
                f"READER_DETAILS:",
                f"  ID: {reader_id}",
                f"  Role: {reader_nodes[0].get('DBNodeRole', 'N/A')}",
                f"  Class: {reader_nodes[0].get('DBNodeClass', 'N/A')}",
                f"  CPU: {reader_nodes[0].get('CpuCores', 'N/A')}",
                f"  Memory_MB: {reader_nodes[0].get('MemorySize', 'N/A')}",
                f"  Zone: {reader_nodes[0].get('ZoneId', 'N/A')}",
                f"  Hot_Replica: {reader_nodes[0].get('HotReplicaMode', 'N/A')}",
                ""
            ])
        
        if writer_nodes:
            cluster_info.extend([
                f"WRITER_DETAILS:",
                f"  ID: {writer_id}",
                f"  Role: {writer_nodes[0].get('DBNodeRole', 'N/A')}",
                f"  Class: {writer_nodes[0].get('DBNodeClass', 'N/A')}",
                f"  CPU: {writer_nodes[0].get('CpuCores', 'N/A')}",
                f"  Memory_MB: {writer_nodes[0].get('MemorySize', 'N/A')}",
                f"  Zone: {writer_nodes[0].get('ZoneId', 'N/A')}",
                ""
            ])
        
        # Essential system info
        cluster_info.extend([
            f"PERFORMANCE:",
            f"  Proxy_Status: {body.get('ProxyStatus', 'N/A')}",
            f"  Proxy_Type: {body.get('ProxyType', 'N/A')}",
            f"  DB_Version_Status: {body.get('DBVersionStatus', 'N/A')}",
            "",
            f"STORAGE:",
            f"  Type: {body.get('StorageType', 'N/A')}",
            f"  Max_GB: {float(body.get('StorageMax', 0)) / (1024**3):.2f}" if body.get('StorageMax') else "Max_GB: 0",
            "",
            f"BACKUP:",
            f"  Size_MB: {float(body.get('DataLevel1BackupChainSize', 0)) / (1024**2):.2f}" if body.get('DataLevel1BackupChainSize') else "Size_MB: 0",
            f"  Compress_Mode: {body.get('CompressStorageMode', 'N/A')}",
            "",
            f"RESOURCES:",
            f"  Inodes_Used: {body.get('InodeUsed', 'N/A')}/{body.get('InodeTotal', 'N/A')}",
            f"  Blktags_Used: {body.get('BlktagUsed', 'N/A')}/{body.get('BlktagTotal', 'N/A')}",
            "",
            f"SUCCESS: Request_ID {body.get('RequestId', 'N/A')}"
        ])

        return [TextContent(type="text", text="\n".join(cluster_info))]

    except Exception as e:
        logger.error(f"Error describing PolarDB cluster {db_cluster_id}: {str(e)}")
        return [TextContent(type="text", text=f"ERROR: {db_cluster_id} - {str(e)}")]



def polardb_describe_available_resources(arguments: dict = None) -> list[TextContent]:
    """List available resources for creating PolarDB clusters"""
    arguments = arguments or {}

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing available resources
        request = polardb_20170801_models.DescribeDBClusterAvailableResourcesRequest()

        # Set default PayType if not provided
        request.pay_type = arguments.get("pay_type", "Postpaid")

        # Set optional parameters if provided
        if "region_id" in arguments and arguments["region_id"]:
            request.region_id = arguments["region_id"]
        if "zone_id" in arguments and arguments["zone_id"]:
            request.zone_id = arguments["zone_id"]
        if "db_type" in arguments and arguments["db_type"]:
            request.db_type = arguments["db_type"]
        if "db_version" in arguments and arguments["db_version"]:
            request.db_version = arguments["db_version"]

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbcluster_available_resources_with_options(request, runtime)

        # Format the response
        if response.body and hasattr(response.body, 'available_zones') and response.body.available_zones:
            zones_info = []

            for zone in response.body.available_zones:
                zone_info = [f"Zone: {zone.zone_id}, Region: {zone.region_id}"]

                if hasattr(zone, 'supported_engines') and zone.supported_engines:
                    for engine in zone.supported_engines:
                        engine_info = [f"  Engine: {engine.engine}"]

                        if hasattr(engine, 'available_resources') and engine.available_resources:
                            resources = []
                            for resource in engine.available_resources:
                                resources.append(f"    {resource.category}: {resource.dbnode_class}")

                            if resources:
                                engine_info.append("\n".join(resources))
                        else:
                            engine_info.append("    No available resources")

                        zone_info.append("\n".join(engine_info))
                else:
                    zone_info.append("  No supported engines")

                zones_info.append("\n".join(zone_info))
                zones_info.append("----------------------------------")

            return [TextContent(type="text", text="\n".join(zones_info))]
        else:
            msg = "No PolarDB available resources found"
            if "region_id" in arguments and arguments["region_id"]:
                msg += f" in region {arguments['region_id']}"
            if "zone_id" in arguments and arguments["zone_id"]:
                msg += f" for zone {arguments['zone_id']}"
            if "db_type" in arguments and arguments["db_type"]:
                msg += f" for DB type {arguments['db_type']}"
            return [TextContent(type="text", text=msg)]

    except Exception as e:
        logger.error(f"Error describing PolarDB available resources: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving available resources: {str(e)}")]

# Add this function to your server.py

def polardb_describe_global_security_ipgroup_relation(arguments: dict) -> list[TextContent]:
    """Get global security IP group relations for a specific PolarDB cluster"""
    region_id = arguments.get("region_id")
    dbcluster_id = arguments.get("dbcluster_id")

    # Validate required parameters
    if not region_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: Region ID is required")]
    if not dbcluster_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ CLIENT_ERROR: Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing global security IP group relation
        request = polardb_20170801_models.DescribeGlobalSecurityIPGroupRelationRequest(
            region_id=region_id,
            dbcluster_id=dbcluster_id
        )

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_global_security_ipgroup_relation_with_options(request, runtime)

        # Format the response based on actual API structure
        if hasattr(response, 'body') and response.body:
            try:
                # Use to_map() for structured access
                response_dict = response.to_map()
                body = response_dict.get('body', {})
                
                # Build comprehensive response
                result = [
                    "=== POLARDB GLOBAL SECURITY IP GROUP RELATIONS ===",
                    f"CLUSTER_ID: {dbcluster_id}",
                    f"REGION_ID: {region_id}",
                    f"REQUEST_ID: {body.get('RequestId', 'N/A')}",
                    f"QUERY_TIME: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    "=" * 60
                ]
                
                # Extract the cluster ID from response (should match input)
                response_cluster_id = body.get('DBClusterId', 'N/A')
                if response_cluster_id != dbcluster_id:
                    result.append(f"⚠️  WARNING: Response cluster ID ({response_cluster_id}) differs from request ({dbcluster_id})")
                    result.append("")
                
                # Process Global Security IP Group Relations
                global_relations = body.get('GlobalSecurityIPGroupRel', [])
                
                if global_relations and len(global_relations) > 0:
                    result.extend([
                        f"TOTAL_GLOBAL_SECURITY_GROUPS: {len(global_relations)}",
                        ""
                    ])
                    
                    for i, relation in enumerate(global_relations, 1):
                        # Extract relation details
                        global_ip_group_name = relation.get('GlobalIgName', 'N/A')
                        region_id_rel = relation.get('RegionId', 'N/A')
                        global_ip_group_id = relation.get('GlobalIgId', 'N/A')
                        gip_list = relation.get('GIpList', 'N/A')
                        white_group_ids = relation.get('WhiteGroupIds', 'N/A')
                        
                        result.extend([
                            f"GLOBAL_SECURITY_GROUP_{i}:",
                            f"  GROUP_NAME: {global_ip_group_name}",
                            f"  GROUP_ID: {global_ip_group_id}",
                            f"  REGION: {region_id_rel}",
                            f"  IP_LIST: {gip_list}",
                            f"  WHITE_GROUP_IDS: {white_group_ids}",
                            ""
                        ])
                        
                        # Analyze IP list if available
                        if gip_list and gip_list != 'N/A':
                            result.append("  IP_ANALYSIS:")
                            
                            # Split and analyze IPs
                            if isinstance(gip_list, str):
                                ip_addresses = [ip.strip() for ip in gip_list.split(',') if ip.strip()]
                            elif isinstance(gip_list, list):
                                ip_addresses = gip_list
                            else:
                                ip_addresses = [str(gip_list)]
                            
                            for j, ip in enumerate(ip_addresses, 1):
                                # Analyze IP security level
                                if ip == '0.0.0.0/0':
                                    security_level = "🔴 CRITICAL_RISK"
                                    description = "Allows access from any IP worldwide"
                                elif ip.startswith('127.'):
                                    security_level = "🟢 MINIMAL_RISK"
                                    description = "Localhost access only"
                                elif ip.startswith(('192.168.', '10.', '172.')):
                                    security_level = "🟡 LOW_RISK"
                                    description = "Private network access"
                                elif '/' in ip:
                                    try:
                                        network_size = int(ip.split('/')[-1])
                                        if network_size <= 16:
                                            security_level = "🟠 HIGH_RISK"
                                            description = f"Large network range (/{network_size})"
                                        else:
                                            security_level = "🟡 MEDIUM_RISK"
                                            description = f"Network range (/{network_size})"
                                    except:
                                        security_level = "❓ UNKNOWN_RISK"
                                        description = "Invalid CIDR format"
                                else:
                                    security_level = "🟢 LOW_RISK"
                                    description = "Specific IP address"
                                
                                result.extend([
                                    f"    IP_{j}: {ip}",
                                    f"    SECURITY_LEVEL: {security_level}",
                                    f"    DESCRIPTION: {description}",
                                    ""
                                ])
                        
                        result.append("-" * 50)
                        result.append("")
                else:
                    result.extend([
                        "TOTAL_GLOBAL_SECURITY_GROUPS: 0",
                        "",
                        "📋 STATUS: No global security IP groups are associated with this cluster",
                        "",
                        "ℹ️  INFORMATION:",
                        "  • Global security IP groups allow centralized IP whitelist management",
                        "  • They can be shared across multiple PolarDB clusters",
                        "  • If no global groups are configured, the cluster uses local IP arrays only",
                        ""
                    ])
                
                # Add security assessment
                result.extend([
                    "=== SECURITY ASSESSMENT ===",
                    ""
                ])
                
                if global_relations:
                    # Analyze overall security posture
                    has_open_access = False
                    has_private_access = False
                    total_ips = 0
                    
                    for relation in global_relations:
                        gip_list = relation.get('GIpList', '')
                        if gip_list:
                            if '0.0.0.0/0' in str(gip_list):
                                has_open_access = True
                            if any(ip_prefix in str(gip_list) for ip_prefix in ['192.168.', '10.', '172.']):
                                has_private_access = True
                            
                            # Count IPs
                            if isinstance(gip_list, str):
                                total_ips += len([ip for ip in gip_list.split(',') if ip.strip()])
                            elif isinstance(gip_list, list):
                                total_ips += len(gip_list)
                    
                    if has_open_access:
                        result.extend([
                            "🔴 CRITICAL_SECURITY_ALERT: GLOBAL_OPEN_INTERNET_ACCESS",
                            "RISK_LEVEL: MAXIMUM",
                            "IMPACT: Cluster accessible from any IP address worldwide via global groups",
                            "IMMEDIATE_ACTION_REQUIRED: Remove 0.0.0.0/0 from global security groups",
                            ""
                        ])
                    
                    if has_private_access:
                        result.extend([
                            "🟡 PRIVATE_NETWORK_ACCESS: INTERNAL_NETWORKS_VIA_GLOBAL_GROUPS",
                            "RISK_LEVEL: LOW_TO_MEDIUM",
                            "IMPACT: Access from internal networks configured via global groups",
                            "RECOMMENDATION: Verify global group network security policies",
                            ""
                        ])
                    
                    result.extend([
                        f"GLOBAL_SECURITY_SUMMARY:",
                        f"  • Global Security Groups: {len(global_relations)}",
                        f"  • Total IP Addresses: {total_ips}",
                        f"  • Open Internet Access: {'YES - CRITICAL' if has_open_access else 'NO'}",
                        f"  • Private Network Access: {'YES' if has_private_access else 'NO'}",
                        ""
                    ])
                else:
                    result.extend([
                        "🔵 NO_GLOBAL_SECURITY_GROUPS_CONFIGURED",
                        "RISK_LEVEL: DEPENDENT_ON_LOCAL_CONFIGURATION",
                        "IMPACT: Cluster access controlled by local IP arrays only",
                        "RECOMMENDATION: Check local whitelist with polardb_describe_db_cluster_access_whitelist",
                        ""
                    ])
                
                # Final recommendations
                result.extend([
                    "=== RECOMMENDATIONS ===",
                    "",
                    "GLOBAL_SECURITY_GROUP_MANAGEMENT:",
                    "  • Use global security groups for centralized IP management across clusters",
                    "  • Avoid duplicate IP configurations between global and local arrays",
                    "  • Regularly audit global group memberships and IP ranges",
                    "  • Consider separate global groups for different environments (dev/prod)",
                    "",
                    "RELATED_OPERATIONS:",
                    "  • Use polardb_describe_db_cluster_access_whitelist to check local IP arrays",
                    "  • Use polardb_modify_db_cluster_access_whitelist to update local arrays",
                    "  • Global groups are managed through separate Alibaba Cloud console/API",
                    "",
                    "NEXT_STEPS:",
                    f"  • Review global security group configurations in Alibaba Cloud console",
                    f"  • Verify that global + local IP configurations meet security requirements",
                    f"  • Test connectivity from intended source IP addresses"
                ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing global security relation response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"GLOBAL_SECURITY_QUERY_COMPLETED: {dbcluster_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed\n"
                    f"RAW_DATA_SAMPLE: {str(response_dict)[:500]}..."
                ))]
        else:
            return [TextContent(type="text", text=f"NO_API_RESPONSE_FOR_CLUSTER: {dbcluster_id}")]

    except Exception as e:
        logger.error(f"Error describing PolarDB global security IP group relation: {str(e)}")
        return [TextContent(type="text", text=f"API_ERROR: {str(e)}")]

def polardb_describe_db_node_parameters(arguments: dict) -> list[TextContent]:
    """Get configuration parameters for a specific PolarDB database node"""
    dbnode_id = arguments.get("dbnode_id")
    db_cluster_id = arguments.get("db_cluster_id")

    if not dbnode_id:
        return [TextContent(type="text", text="Database node ID is required")]

    if not db_cluster_id:
        return [TextContent(type="text", text="DB cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing DB node parameters
        request = polardb_20170801_models.DescribeDBNodesParametersRequest(
            dbnode_ids=dbnode_id,
            dbcluster_id=db_cluster_id
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbnodes_parameters_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Try to parse the response as JSON for better formatting
                import json
                formatted_response = json.dumps(response.body.to_map(), indent=2)
                return [TextContent(type="text", text=f"Parameters for DB node {dbnode_id}:\n{formatted_response}")]
            except Exception:
                # Fallback to string representation if JSON conversion fails
                return [TextContent(type="text", text=f"Parameters for DB node {dbnode_id}:\n{str(response.body)}")]
        else:
            return [TextContent(type="text", text=f"No parameters found for DB node {dbnode_id} in cluster {db_cluster_id}")]

    except Exception as e:
        logger.error(f"Error describing PolarDB node parameters: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving parameters: {str(e)}")]

def polardb_modify_db_cluster_parameters(arguments: dict) -> list[TextContent]:
    """Modify configuration parameters for PolarDB cluster"""
    db_cluster_id = arguments.get("db_cluster_id")
    parameters = arguments.get("parameters")

    if not db_cluster_id:
        return [TextContent(type="text", text="DB cluster ID is required")]
    if not parameters:
        return [TextContent(type="text", text="Parameters are required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client")]

    try:
        request = polardb_20170801_models.ModifyDBClusterParametersRequest(
            dbcluster_id=db_cluster_id,
            parameters=parameters
        )
        runtime = util_models.RuntimeOptions()
        response = client.modify_dbcluster_parameters_with_options(request, runtime)

        if hasattr(response, 'body') and response.body:
            result = f"Parameters modified successfully for cluster {db_cluster_id}.\n"
            result += f"Request ID: {getattr(response.body, 'RequestId', 'N/A')}"
            
            task_id = getattr(response.body, 'TaskId', None)
            if task_id:
                result += f"\nTask ID: {task_id}"

            return [TextContent(type="text", text=result)]
        else:
            return [TextContent(type="text", text="No response received from the API")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error modifying parameters: {str(e)}")]

def polardb_modify_db_node_parameters(arguments: dict) -> list[TextContent]:
    """Modify configuration parameters for PolarDB database nodes"""
    db_cluster_id = arguments.get("db_cluster_id")
    dbnode_ids = arguments.get("dbnode_ids")
    parameters = arguments.get("parameters")

    if not db_cluster_id:
        return [TextContent(type="text", text="DB cluster ID is required")]
    if not dbnode_ids:
        return [TextContent(type="text", text="Database node IDs are required")]
    if not parameters:
        return [TextContent(type="text", text="Parameters are required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for modifying DB node parameters
        request = polardb_20170801_models.ModifyDBNodesParametersRequest(
            parameters=parameters,
            dbcluster_id=db_cluster_id,
            dbnode_ids=dbnode_ids
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.modify_dbnodes_parameters_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            result = f"Parameters modified successfully for nodes {dbnode_ids} in cluster {db_cluster_id}.\n"
            result += f"Request ID: {getattr(response.body, 'RequestId', 'N/A')}"

            # Check if there's a TaskId in the response
            task_id = getattr(response.body, 'TaskId', None)
            if task_id:
                result += f"\nTask ID: {task_id}"

            return [TextContent(type="text", text=result)]
        else:
            return [TextContent(type="text", text=f"No response received from the API. The operation may have failed.")]

    except Exception as e:
        logger.error(f"Error modifying PolarDB node parameters: {str(e)}")
        return [TextContent(type="text", text=f"Error modifying parameters: {str(e)}")]

# Add this function to your code to handle creating PolarDB clusters
def polardb_create_cluster(arguments: dict) -> list[TextContent]:
    """Create a new PolarDB cluster"""
    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for creating a new PolarDB cluster
        request = polardb_20170801_models.CreateDBClusterRequest()

        # Required parameters
        request.region_id = arguments.get("region_id", "cn-hangzhou")
        request.dbtype = arguments.get("dbtype", "MySQL")
        request.dbversion = arguments.get("dbversion", "8.0")
        request.dbnode_class = arguments.get("dbnode_class", "polar.mysql.g2.medium")
        request.pay_type = arguments.get("pay_type", "Postpaid")

        # StorageSpace parameter (required to avoid the error you encountered)
        storage_space = arguments.get("storage_space", 50)
        # Convert to int if it's a string
        if isinstance(storage_space, str) and storage_space.isdigit():
            storage_space = int(storage_space)
        request.storage_space = storage_space

        # Optional parameters
        if "zone_id" in arguments:
            request.zone_id = arguments["zone_id"]
        if "vpc_id" in arguments:
            request.vpcid = arguments["vpc_id"]
        if "vswitch_id" in arguments:
            request.vswitch_id = arguments["vswitch_id"]
        if "tde_status" in arguments:
            request.tde_status = arguments["tde_status"]
        if "db_cluster_description" in arguments:
            request.db_cluster_description = arguments["db_cluster_description"]
        if "resource_group_id" in arguments:
            request.resource_group_id = arguments["resource_group_id"]
        if "period" in arguments:
            request.period = arguments["period"]
        if "used_time" in arguments:
            request.used_time = arguments["used_time"]
        if "client_token" in arguments:
            request.client_token = arguments["client_token"]

        # Add runtime options
        runtime = util_models.RuntimeOptions()

        # Call the API to create the cluster
        response = client.create_dbcluster_with_options(request, runtime)

        # Format and return the successful response
        if response.body:
            result = (
                f"PolarDB cluster created successfully!\n"
                f"Cluster ID: {getattr(response.body, 'DBClusterId', 'N/A')}\n"
                f"Order ID: {getattr(response.body, 'OrderId', 'N/A')}\n"
                f"Request ID: {getattr(response.body, 'RequestId', 'N/A')}\n"
                f"Resource Group ID: {getattr(response.body, 'ResourceGroupId', 'N/A')}"
            )
            return [TextContent(type="text", text=result)]
        else:
            return [TextContent(type="text", text="Cluster creation response was empty. Please check the console to verify creation.")]

    except Exception as e:
        logger.error(f"Error creating PolarDB cluster: {str(e)}")
        return [TextContent(type="text", text=f"Error creating PolarDB cluster: {str(e)}")]

def polardb_describe_slow_log_records(arguments: dict) -> list[TextContent]:
    """Get slow log records for a specific PolarDB cluster within a time range"""
    region_id = arguments.get("region_id")
    db_cluster_id = arguments.get("db_cluster_id")
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")

    # Validate required parameters
    if not region_id:
        return [TextContent(type="text", text="Region ID is required")]
    if not db_cluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]
    if not start_time:
        return [TextContent(type="text", text="Start time is required")]
    if not end_time:
        return [TextContent(type="text", text="End time is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing slow log records
        request = polardb_20170801_models.DescribeSlowLogRecordsRequest(
            region_id=region_id,
            dbcluster_id=db_cluster_id,
            start_time=start_time,
            end_time=end_time
        )

        # Set optional parameters if provided
        if "node_id" in arguments and arguments["node_id"]:
            request.node_id = arguments["node_id"]
        if "dbname" in arguments and arguments["dbname"]:
            request.dbname = arguments["dbname"]
        if "page_size" in arguments and arguments["page_size"]:
            request.page_size = arguments["page_size"]
        if "page_number" in arguments and arguments["page_number"]:
            request.page_number = arguments["page_number"]
        if "sqlhash" in arguments and arguments["sqlhash"]:
            request.sqlhash = arguments["sqlhash"]

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_slow_log_records_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Use to_map() directly to get structured data
                response_dict = response.to_map()
                
                if 'body' in response_dict:
                    body = response_dict['body']

                    # Format header information
                    result_lines = [
                        f"SLOW_LOG_ANALYSIS_START",
                        f"Cluster: {db_cluster_id}",
                        f"Region: {region_id}",
                        f"TimeRange: {start_time} to {end_time}",
                        f"TotalRecords: {body.get('TotalRecordCount', 'N/A')}",
                        f"PageNumber: {body.get('PageNumber', 'N/A')}",
                        f"PageSize: {body.get('PageRecordCount', 'N/A')}",
                        f"RequestId: {body.get('RequestId', 'N/A')}",
                        "=" * 80
                    ]

                    # Parse slow log items
                    if 'Items' in body and 'SQLSlowRecord' in body['Items']:
                        slow_logs = body['Items']['SQLSlowRecord']

                        # Handle case where slow_logs might not be a list
                        if not isinstance(slow_logs, list):
                            slow_logs = [slow_logs]

                        result_lines.append(f"Found {len(slow_logs)} slow query records:")
                        result_lines.append("")

                        for i, log in enumerate(slow_logs, 1):
                            # Format timestamp
                            exec_time = log.get('ExecutionStartTime', 'N/A')
                            query_time_ms = log.get('QueryTimeMS', 0)
                            query_time_sec = round(float(query_time_ms) / 1000, 2) if query_time_ms else 0
                            
                            # Get SQL text and truncate if too long
                            sql_text = log.get('SQLText', 'N/A')
                            if len(sql_text) > 200:
                                sql_preview = sql_text[:200] + "..."
                            else:
                                sql_preview = sql_text
                            
                            log_info = [
                                f"SLOW_QUERY_{i}:",
                                f"  Time: {exec_time}",
                                f"  Duration: {query_time_sec} seconds ({query_time_ms} ms)",
                                f"  Database: {log.get('DBName', 'N/A')}",
                                f"  Node: {log.get('DBNodeId', 'N/A')}",
                                f"  Host: {log.get('HostAddress', 'N/A')}",
                                f"  Rows Processed: {log.get('ParseRowCounts', 'N/A')}",
                                f"  Rows Returned: {log.get('ReturnRowCounts', 'N/A')}",
                                f"  Lock Time: {log.get('LockTimes', 'N/A')} ms",
                                f"  SQL Hash: {log.get('SQLHash', 'N/A')}",
                                f"  SQL Preview: {sql_preview}",
                                ""
                            ]
                            result_lines.extend(log_info)

                        result_lines.append("SLOW_LOG_ANALYSIS_END")
                        return [TextContent(type="text", text="\n".join(result_lines))]
                    else:
                        result_lines.extend([
                            "No slow log records found in the specified time range.",
                            "SLOW_LOG_ANALYSIS_END"
                        ])
                        return [TextContent(type="text", text="\n".join(result_lines))]
                        
            except Exception as parse_error:
                logger.error(f"Error parsing slow log response: {str(parse_error)}")
                # Fallback to basic info
                return [TextContent(type="text", text=(
                    f"SLOW_LOG_ERROR\n"
                    f"Cluster: {db_cluster_id}\n"
                    f"ParseError: {str(parse_error)}\n"
                    f"RawResponse: Available but parsing failed"
                ))]
        else:
            return [TextContent(type="text", text=f"No slow log records found for cluster {db_cluster_id} in the specified time range.")]

    except Exception as e:
        logger.error(f"Error describing slow log records: {str(e)}")
        error_msg = f"Error retrieving slow log records: {str(e)}"
        return [TextContent(type="text", text=error_msg)]



def analyze_cluster_performance_data(performance_data: dict, time_range: dict) -> dict:
    """Analyze cluster performance data and provide insights"""
    analysis = {
        "summary": {
            "cluster_id": performance_data.get("cluster_id", "Unknown"),
            "time_range": f"{time_range.get('start', 'Unknown')} to {time_range.get('end', 'Unknown')}",
            "total_metrics": 0,
            "analysis_time": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        },
        "metrics_analysis": {},
        "performance_insights": [],
        "recommendations": [],
        "alerts": []
    }
    
    try:
        metrics = performance_data.get("metrics", [])
        analysis["summary"]["total_metrics"] = len(metrics)
        
        # Analyze each metric
        for metric in metrics:
            measurement = metric.get("measurement", "")
            metric_name = metric.get("metric_name", "")
            points = metric.get("points", [])
            
            if not points:
                continue
                
            # Extract numeric values
            values = []
            for point in points:
                try:
                    value = float(point.get("value", 0))
                    values.append(value)
                except (ValueError, TypeError):
                    continue
            
            if not values:
                continue
                
            # Statistical analysis
            metric_stats = {
                "measurement": measurement,
                "metric_name": metric_name,
                "data_points": len(values),
                "average": round(sum(values) / len(values), 2),
                "minimum": round(min(values), 2),
                "maximum": round(max(values), 2),
                "latest": round(values[-1], 2),
                "trend": analyze_trend_direction(values),
                "variation": round((max(values) - min(values)), 2),
                "stability": "stable" if (max(values) - min(values)) / max(max(values), 1) < 0.1 else "variable"
            }
            
            # Add metric-specific analysis
            friendly_name = get_cluster_metric_friendly_name(measurement, metric_name)
            analysis["metrics_analysis"][friendly_name] = metric_stats
            
            # Generate specific insights
            insights = generate_metric_insights(measurement, metric_name, metric_stats)
            analysis["performance_insights"].extend(insights)
            
            # Generate alerts if needed
            alerts = generate_metric_alerts(measurement, metric_name, metric_stats)
            analysis["alerts"].extend(alerts)
        
        # Generate overall recommendations
        analysis["recommendations"] = generate_cluster_recommendations(analysis["metrics_analysis"])
        
        return analysis
        
    except Exception as e:
        logger.error(f"Error analyzing cluster performance data: {e}")
        analysis["error"] = f"Analysis failed: {str(e)}"
        return analysis

def get_cluster_metric_friendly_name(measurement: str, metric_name: str) -> str:
    """Get friendly names for cluster metrics"""
    name_mapping = {
        # Disk Usage
        ("PolarDBDiskUsage", "mean_data_size"): "数据存储使用量(MB)",
        ("PolarDBDiskUsage", "mean_log_size"): "日志存储使用量(MB)",
        ("PolarDBDiskUsage", "mean_sys_dir_size"): "系统目录大小(MB)",
        ("PolarDBDiskUsage", "mean_tmp_dir_size"): "临时目录大小(MB)",
        ("PolarDBDiskUsage", "mean_redolog_size"): "重做日志大小(MB)",
        ("PolarDBDiskUsage", "mean_binlog_size"): "二进制日志大小(MB)",
        ("PolarDBDiskUsage", "mean_undolog_size"): "撤销日志大小(MB)",
        ("PolarDBDiskUsage", "mean_other_log_size"): "其他日志大小(MB)",
        
        # CPU and Memory
        ("PolarDBCPU", "cpu_ratio"): "CPU使用率(%)",
        ("PolarDBMemory", "mem_ratio"): "内存使用率(%)",
        
        # Connections
        ("PolarDBConnections", "mean_active_session"): "活跃会话数",
        ("PolarDBConnections", "mean_total_session"): "总会话数",
        ("PolarDBConnections", "mean_tp_thread_count"): "线程池线程数",
        ("PolarDBConnections", "mean_thread_pool_running_threads"): "运行中线程数",
        
        # IOPS
        ("PolarDBIOSTAT", "mean_iops_r"): "读IOPS",
        ("PolarDBIOSTAT", "mean_iops_w"): "写IOPS",
        ("PolarDBIOSTAT", "mean_iops"): "总IOPS",
        ("PolarDBIOSTAT", "mean_io_throughput_r"): "读吞吐量(MB/s)",
        ("PolarDBIOSTAT", "mean_io_throughput_w"): "写吞吐量(MB/s)",
        ("PolarDBIOSTAT", "mean_io_throughput"): "总吞吐量(MB/s)",
        ("PolarDBIOSTAT", "mean_iops_usage"): "IOPS使用率(%)",
    }
    
    return name_mapping.get((measurement, metric_name), f"{measurement}-{metric_name}")

def analyze_trend_direction(values: list) -> str:
    """Analyze trend direction of performance values"""
    if len(values) < 2:
        return "insufficient_data"
    
    # Compare first and last quartiles
    quarter_size = max(1, len(values) // 4)
    first_quarter = values[:quarter_size]
    last_quarter = values[-quarter_size:]
    
    first_avg = sum(first_quarter) / len(first_quarter)
    last_avg = sum(last_quarter) / len(last_quarter)
    
    if first_avg == 0:
        return "increasing" if last_avg > 0 else "stable"
    
    change_percent = ((last_avg - first_avg) / first_avg) * 100
    
    if abs(change_percent) < 5:
        return "stable"
    elif change_percent > 0:
        return "increasing"
    else:
        return "decreasing"

def generate_metric_insights(measurement: str, metric_name: str, stats: dict) -> list:
    """Generate insights for specific metrics"""
    insights = []
    
    try:
        avg = stats["average"]
        max_val = stats["maximum"]
        trend = stats["trend"]
        
        # CPU insights
        if measurement == "PolarDBCPU" and metric_name == "cpu_ratio":
            if avg > 80:
                insights.append(f"🔴 CPU使用率过高: 平均 {avg}%，最高 {max_val}%")
            elif avg > 60:
                insights.append(f"🟡 CPU使用率偏高: 平均 {avg}%")
            else:
                insights.append(f"🟢 CPU使用率正常: 平均 {avg}%")
                
            if trend == "increasing":
                insights.append("📈 CPU使用率呈上升趋势，需要关注")
        
        # Memory insights
        elif measurement == "PolarDBMemory" and metric_name == "mem_ratio":
            if avg > 85:
                insights.append(f"🔴 内存使用率过高: 平均 {avg}%")
            elif avg > 70:
                insights.append(f"🟡 内存使用率偏高: 平均 {avg}%")
            else:
                insights.append(f"🟢 内存使用率正常: 平均 {avg}%")
        
        # IOPS insights
        elif measurement == "PolarDBIOSTAT":
            if metric_name == "mean_iops":
                if avg > 1000:
                    insights.append(f"📊 高IOPS负载: 平均 {avg} IOPS")
                elif avg < 10:
                    insights.append(f"📊 低IOPS负载: 平均 {avg} IOPS")
            elif metric_name == "mean_iops_usage" and avg > 80:
                insights.append(f"⚠️ IOPS使用率过高: 平均 {avg}%")
        
        # Storage insights
        elif measurement == "PolarDBDiskUsage":
            if metric_name == "mean_log_size" and avg > 2000:
                insights.append(f"📁 日志文件较大: 平均 {avg} MB，建议进行日志清理")
            elif metric_name == "mean_data_size" and trend == "increasing":
                insights.append(f"📈 数据大小持续增长: 当前 {stats['latest']} MB")
        
    except Exception as e:
        logger.warning(f"Error generating insights for {measurement}-{metric_name}: {e}")
    
    return insights

def generate_metric_alerts(measurement: str, metric_name: str, stats: dict) -> list:
    """Generate alerts for critical metrics"""
    alerts = []
    
    try:
        avg = stats["average"]
        max_val = stats["maximum"]
        
        # Critical CPU alert
        if measurement == "PolarDBCPU" and metric_name == "cpu_ratio":
            if max_val > 95:
                alerts.append({
                    "level": "critical",
                    "metric": "CPU使用率",
                    "message": f"CPU使用率峰值达到 {max_val}%，可能影响性能",
                    "recommendation": "考虑扩容或优化查询"
                })
        
        # Critical memory alert
        elif measurement == "PolarDBMemory" and metric_name == "mem_ratio":
            if max_val > 90:
                alerts.append({
                    "level": "critical", 
                    "metric": "内存使用率",
                    "message": f"内存使用率峰值达到 {max_val}%",
                    "recommendation": "考虑增加内存或优化缓存配置"
                })
        
        # IOPS usage alert
        elif measurement == "PolarDBIOSTAT" and metric_name == "mean_iops_usage":
            if avg > 85:
                alerts.append({
                    "level": "warning",
                    "metric": "IOPS使用率", 
                    "message": f"IOPS使用率平均 {avg}%，接近上限",
                    "recommendation": "监控I/O性能，考虑优化查询或扩容"
                })
                
    except Exception as e:
        logger.warning(f"Error generating alerts for {measurement}-{metric_name}: {e}")
    
    return alerts

def generate_cluster_recommendations(metrics_analysis: dict) -> list:
    """Generate overall cluster recommendations"""
    recommendations = []
    
    try:
        # Check for high resource usage
        high_cpu = any("CPU使用率" in k and v["average"] > 70 for k, v in metrics_analysis.items())
        high_memory = any("内存使用率" in k and v["average"] > 75 for k, v in metrics_analysis.items())
        high_iops = any("IOPS使用率" in k and v["average"] > 70 for k, v in metrics_analysis.items())
        
        if high_cpu and high_memory:
            recommendations.append("🔧 建议进行集群扩容：CPU和内存使用率都偏高")
        elif high_cpu:
            recommendations.append("🔧 建议优化查询性能或增加CPU资源")
        elif high_memory:
            recommendations.append("🔧 建议增加内存资源或优化缓存配置")
        
        if high_iops:
            recommendations.append("💾 建议优化存储I/O或考虑使用更高性能的存储")
        
        # Check for storage growth
        log_size_metrics = [v for k, v in metrics_analysis.items() if "日志" in k]
        if log_size_metrics and any(m["trend"] == "increasing" for m in log_size_metrics):
            recommendations.append("📁 建议配置日志轮转和清理策略")
        
        # General recommendations
        if len(recommendations) == 0:
            recommendations.append("✅ 集群性能指标正常，继续监控")
        else:
            recommendations.append("📊 建议定期监控性能趋势，制定容量规划")
            
    except Exception as e:
        logger.warning(f"Error generating recommendations: {e}")
        recommendations.append("📊 建议定期监控集群性能指标")
    
    return recommendations

def polardb_describe_db_cluster_performance(arguments: dict) -> list[TextContent]:
    """Get performance metrics for a specific PolarDB cluster within a time range with enhanced analysis"""
    db_cluster_id = arguments.get("db_cluster_id")
    key = arguments.get("key")
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")

    # Validate required parameters
    if not db_cluster_id:
        return [TextContent(type="text", text="❌ 缺少参数: 需要提供数据库集群ID")]
    if not start_time:
        return [TextContent(type="text", text="❌ 缺少参数: 需要提供开始时间")]
    if not end_time:
        return [TextContent(type="text", text="❌ 缺少参数: 需要提供结束时间")]

    # Validate and correct performance metrics
    validated_key, warnings = validate_cluster_performance_keys(key)
    
    # Convert times to Beijing time and then to UTC for API
    try:
        corrected_start_time = convert_to_beijing_time(start_time)
        corrected_end_time = convert_to_beijing_time(end_time)
        
        # Validate time sequence
        start_dt = datetime.strptime(corrected_start_time, '%Y-%m-%dT%H:%MZ')
        end_dt = datetime.strptime(corrected_end_time, '%Y-%m-%dT%H:%MZ')
        
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)
            corrected_end_time = end_dt.strftime('%Y-%m-%dT%H:%MZ')
            warnings.append(f"结束时间已调整为开始时间后1小时: {corrected_end_time}")
            
    except Exception as e:
        logger.error(f"Time conversion error: {e}")
        return [TextContent(type="text", text=f"❌ 时间格式错误: {str(e)}")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ 创建PolarDB客户端失败，请检查凭证配置")]

    try:
        # Create request
        request = polardb_20170801_models.DescribeDBClusterPerformanceRequest(
            dbcluster_id=db_cluster_id,
            key=validated_key,
            start_time=corrected_start_time,
            end_time=corrected_end_time
        )

        runtime = util_models.RuntimeOptions()
        
        logger.info(f"调用集群性能API: cluster={db_cluster_id}, key={validated_key}, start={corrected_start_time}, end={corrected_end_time}")

        # Call the API
        response = client.describe_dbcluster_performance_with_options(request, runtime)

        # Parse and analyze response
        if hasattr(response, 'body') and response.body:
            try:
                response_dict = response.to_map()
                
                if 'body' in response_dict:
                    body = response_dict['body']
                    
                    # Build structured response with analysis
                    time_range = {
                        "start": body.get('StartTime', corrected_start_time),
                        "end": body.get('EndTime', corrected_end_time),
                        "original_start": start_time,
                        "original_end": end_time
                    }
                    
                    # Parse performance data
                    performance_data = {
                        "cluster_id": body.get('DBClusterId', db_cluster_id),
                        "db_type": body.get('DBType', 'MySQL'),
                        "db_version": body.get('DBVersion', 'Unknown'),
                        "metrics": []
                    }
                    
                    # Process metrics
                    if 'PerformanceKeys' in body:
                        perf_keys = body['PerformanceKeys']
                        performance_items = perf_keys.get('PerformanceItem', [])
                        
                        if not isinstance(performance_items, list):
                            performance_items = [performance_items]

                        for item in performance_items:
                            metric_data = {
                                "measurement": item.get('Measurement', 'Unknown'),
                                "metric_name": item.get('MetricName', 'Unknown'),
                                "points": []
                            }

                            if 'Points' in item and 'PerformanceItemValue' in item['Points']:
                                points = item['Points']['PerformanceItemValue']

                                if not isinstance(points, list):
                                    points = [points]

                                for point in points:
                                    timestamp = point.get('Timestamp', 'N/A')
                                    value = point.get('Value', 'N/A')

                                    readable_time = 'N/A'
                                    if timestamp != 'N/A':
                                        try:
                                            timestamp_seconds = int(timestamp) / 1000
                                            readable_time = datetime.fromtimestamp(timestamp_seconds).strftime('%Y-%m-%d %H:%M:%S')
                                        except (ValueError, TypeError):
                                            readable_time = str(timestamp)

                                    metric_data["points"].append({
                                        "timestamp": readable_time,
                                        "value": value
                                    })
                            
                            performance_data["metrics"].append(metric_data)
                    
                    # Perform analysis
                    analysis = analyze_cluster_performance_data(performance_data, time_range)
                    
                    # Format comprehensive response
                    formatted_response = {
                        "status": "success",
                        "cluster_info": {
                            "cluster_id": performance_data["cluster_id"],
                            "db_type": performance_data["db_type"],
                            "db_version": performance_data["db_version"]
                        },
                        "time_range": time_range,
                        "request_info": {
                            "validated_key": validated_key,
                            "original_key": key,
                            "warnings": warnings,
                            "request_id": body.get('RequestId', 'N/A')
                        },
                        "performance_analysis": analysis,
                        "raw_metrics_count": len(performance_data["metrics"])
                    }

                    import json
                    return [TextContent(type="text", text=json.dumps(formatted_response, indent=2, ensure_ascii=False))]
                else:
                    return [TextContent(type="text", text="❌ API响应格式错误: 缺少body部分")]
                        
            except Exception as parse_error:
                logger.error(f"解析集群性能响应错误: {str(parse_error)}")
                return [TextContent(type="text", text=f"❌ 解析响应数据失败: {str(parse_error)}")]
        else:
            return [TextContent(type="text", text=f"❌ 未收到API响应数据，集群ID: {db_cluster_id}")]

    except Exception as e:
        logger.error(f"调用集群性能API出错: {str(e)}")
        
        # Enhanced error response with troubleshooting info
        error_details = {
            "error": str(e),
            "cluster_id": db_cluster_id,
            "validated_key": validated_key,
            "time_info": {
                "original_start": start_time, 
                "original_end": end_time,
                "corrected_start": corrected_start_time if 'corrected_start_time' in locals() else "conversion_failed",
                "corrected_end": corrected_end_time if 'corrected_end_time' in locals() else "conversion_failed"
            },
            "warnings": warnings,
            "troubleshooting": [
                "检查集群ID是否正确",
                "确认时间范围是否合理（建议1-24小时范围）",
                "验证网络连接和API凭证",
                "确认集群处于可访问状态"
            ]
        }
        
        import json
        return [TextContent(type="text", text=f"❌ 集群性能查询失败: {json.dumps(error_details, indent=2, ensure_ascii=False)}")]

def polardb_describe_db_node_performance(arguments: dict) -> list[TextContent]:
    """Get performance metrics for a specific PolarDB database node within a time range"""
    dbnode_id = arguments.get("dbnode_id")
    key = arguments.get("key")
    start_time = arguments.get("start_time")
    end_time = arguments.get("end_time")
    db_cluster_id = arguments.get("db_cluster_id")

    # Validate required parameters
    if not dbnode_id:
        return [TextContent(type="text", text="Database node ID is required")]
    if not start_time:
        return [TextContent(type="text", text="Start time is required")]
    if not end_time:
        return [TextContent(type="text", text="End time is required")]

    # 验证并修正性能指标参数
    validated_key, warnings = validate_node_performance_keys(key)

    time_format_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$'


    if not re.match(time_format_pattern, start_time):
        return [TextContent(type="text", text=f"Invalid start_time format. Expected: YYYY-MM-DDTHH:MMZ, got: {start_time}")]

    if not re.match(time_format_pattern, end_time):
        return [TextContent(type="text", text=f"Invalid end_time format. Expected: YYYY-MM-DDTHH:MMZ, got: {end_time}")]


    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client")]

    try:
        # Create request for describing DB node performance
        request = polardb_20170801_models.DescribeDBNodePerformanceRequest(
            dbnode_id=dbnode_id,
            key=validated_key,  # 使用验证过的指标
            start_time=start_time,
            end_time=end_time
        )

        # Add cluster ID if provided
        if db_cluster_id:
            try:
                request.db_cluster_id = db_cluster_id
            except AttributeError:
                # Ignore if the parameter is not supported in this API version
                pass

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbnode_performance_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Use to_map() directly instead of JSON conversion
                response_dict = response.to_map()

                if 'body' in response_dict:
                    body = response_dict['body']

                    # Parse performance data
                    if 'PerformanceKeys' in body:
                        perf_keys = body['PerformanceKeys']
                        
                        if isinstance(perf_keys, dict) and 'PerformanceItem' in perf_keys:
                            performance_items = perf_keys['PerformanceItem']
                        else:
                            performance_items = perf_keys

                        # Check if we have any performance data
                        if performance_items and len(performance_items) > 0:
                            metrics_data = []
                            
                            if not isinstance(performance_items, list):
                                performance_items = [performance_items]

                            for item in performance_items:
                                metric_name = item.get('MetricName', 'N/A')
                                measurement = item.get('Measurement', 'N/A')
                                
                                metric_info = {
                                    'metric_name': metric_name,
                                    'measurement': measurement,
                                    'points': []
                                }

                                if 'Points' in item and 'PerformanceItemValue' in item['Points']:
                                    points = item['Points']['PerformanceItemValue']

                                    if not isinstance(points, list):
                                        points = [points]

                                    try:
                                        points_sorted = sorted(points, key=lambda x: x.get('Timestamp', 0))
                                    except (TypeError, KeyError):
                                        points_sorted = points

                                    for point in points_sorted:
                                        timestamp = point.get('Timestamp', 'N/A')
                                        value = point.get('Value', 'N/A')

                                        readable_time = 'N/A'
                                        if timestamp != 'N/A':
                                            try:
                                                timestamp_seconds = int(timestamp) / 1000
                                                readable_time = datetime.fromtimestamp(timestamp_seconds).strftime('%Y-%m-%d %H:%M:%S UTC')
                                            except (ValueError, TypeError):
                                                readable_time = str(timestamp)

                                        metric_info['points'].append({
                                            'timestamp': readable_time,
                                            'value': value
                                        })
                                
                                metrics_data.append(metric_info)
                            
                            # Build response with warnings if any
                            formatted_response = {
                                "status": "success",
                                "node_id": body.get('DBNodeId', dbnode_id),
                                "cluster_id": db_cluster_id if db_cluster_id else "N/A",
                                "db_type": body.get('DBType', 'N/A'),
                                "db_version": body.get('DBVersion', 'N/A'),
                                "time_range": {
                                    "start": body.get('StartTime', start_time),
                                    "end": body.get('EndTime', end_time)
                                },
                                "request_id": body.get('RequestId', 'N/A'),
                                "metrics": metrics_data,
                                "validated_key": validated_key,
                                "warnings": warnings if warnings else []
                            }

                            import json
                            return [TextContent(type="text", text=json.dumps(formatted_response, indent=2))]
                        else:
                            # No performance data found
                            no_data_response = {
                                "status": "no_data",
                                "node_id": body.get('DBNodeId', dbnode_id),
                                "cluster_id": db_cluster_id if db_cluster_id else "N/A",
                                "db_type": body.get('DBType', 'N/A'),
                                "db_version": body.get('DBVersion', 'N/A'),
                                "time_range": {
                                    "start": body.get('StartTime', start_time),
                                    "end": body.get('EndTime', end_time)
                                },
                                "request_id": body.get('RequestId', 'N/A'),
                                "validated_key": validated_key,
                                "warnings": warnings if warnings else [],
                                "message": "No performance data available for the specified time range"
                            }
                            
                            import json
                            return [TextContent(type="text", text=json.dumps(no_data_response, indent=2))]
                    else:
                        return [TextContent(type="text", text=f"ERROR: No PerformanceKeys found in API response")]
                        
            except Exception as parse_error:
                logger.error(f"Error parsing node performance response: {str(parse_error)}")
                return [TextContent(type="text", text=f"PARSE_ERROR: {str(parse_error)}")]
        else:
            return [TextContent(type="text", text=f"API_ERROR: No response body received for node {dbnode_id}")]

    except Exception as e:
        logger.error(f"Error describing DB node performance: {str(e)}")
        return [TextContent(type="text", text=f"REQUEST_ERROR: {str(e)}")]



# Modified helper functions with prioritized region search

async def get_all_polardb_clusters() -> str:
    """Get all PolarDB clusters across all regions, prioritizing key regions first"""
    
    # Priority regions where clusters are known to exist
    priority_regions = ["cn-hangzhou", "cn-beijing", "cn-shanghai"]
    
    # First get all available regions
    regions_text = await get_polardb_regions()
    all_regions = []
    
    for line in regions_text.split("\n"):
        if line and ":" in line:
            region_id = line.split(":")[0].strip()
            all_regions.append(region_id)
    
    if not all_regions:
        return "No regions found"
    
    # Organize regions: priority first, then others
    remaining_regions = [r for r in all_regions if r not in priority_regions]
    ordered_regions = priority_regions + remaining_regions
    
    # Get clusters for each region in prioritized order
    all_clusters = []
    clusters_found_count = 0
    
    for region_id in ordered_regions:
        # Only check priority regions first, or all if no clusters found yet
        if region_id in priority_regions or clusters_found_count == 0:
            clusters = await get_polardb_clusters(region_id)
            if clusters and "No PolarDB clusters found" not in clusters:
                all_clusters.append(f"=== Region: {region_id} ===")
                all_clusters.append(clusters)
                # Count clusters found (rough estimate)
                clusters_found_count += clusters.count("Cluster ID:")
                
        # If we found clusters in priority regions, we can stop or continue based on needs
        if clusters_found_count > 0 and region_id == priority_regions[-1]:
            # Found clusters in priority regions, but continue to check remaining regions
            pass
    
    if not all_clusters:
        return "No PolarDB clusters found across all regions"
    
    result_header = f"Found {clusters_found_count} PolarDB clusters (searched priority regions first: {', '.join(priority_regions)})\n\n"
    return result_header + "\n".join(all_clusters)

def polardb_tag_resources(arguments: dict) -> list[TextContent]:
    """Add tags to PolarDB resources (clusters, nodes, etc.)"""
    region_id = arguments.get("region_id")
    resource_type = arguments.get("resource_type")
    resource_ids = arguments.get("resource_ids")
    tags = arguments.get("tags")

    # Validate required parameters
    if not region_id:
        return [TextContent(type="text", text="Region ID is required")]
    if not resource_type:
        return [TextContent(type="text", text="Resource type is required (e.g., 'cluster')")]
    if not resource_ids:
        return [TextContent(type="text", text="Resource IDs are required")]
    if not tags:
        return [TextContent(type="text", text="Tags are required")]

    # Convert resource_ids to list if it's a string
    if isinstance(resource_ids, str):
        resource_ids = [id.strip() for id in resource_ids.split(',')]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create tag objects from the tags parameter
        tag_objects = []
        
        # Handle different tag input formats
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, dict) and 'key' in tag and 'value' in tag:
                    tag_obj = polardb_20170801_models.TagResourcesRequestTag(
                        key=tag['key'],
                        value=tag['value']
                    )
                    tag_objects.append(tag_obj)
                else:
                    return [TextContent(type="text", text="Invalid tag format. Each tag must have 'key' and 'value' fields.")]
        elif isinstance(tags, dict):
            # If tags is a dict, convert each key-value pair to a tag
            for key, value in tags.items():
                tag_obj = polardb_20170801_models.TagResourcesRequestTag(
                    key=str(key),
                    value=str(value)
                )
                tag_objects.append(tag_obj)
        else:
            return [TextContent(type="text", text="Tags must be either a list of {key, value} objects or a dictionary.")]

        if not tag_objects:
            return [TextContent(type="text", text="No valid tags provided.")]

        # Create request for tagging resources
        request = polardb_20170801_models.TagResourcesRequest(
            region_id=region_id,
            resource_type=resource_type,
            resource_id=resource_ids,
            tag=tag_objects
        )
        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.tag_resources_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            result = [
                f"Successfully tagged {len(resource_ids)} resource(s)",
                f"Region: {region_id}",
                f"Resource Type: {resource_type}",
                f"Resource IDs: {', '.join(resource_ids)}",
                f"Tags Applied: {len(tag_objects)} tag(s)",
                ""
            ]
            
            # List the tags that were applied
            for i, tag_obj in enumerate(tag_objects, 1):
                result.append(f"Tag {i}: {tag_obj.key} = {tag_obj.value}")
            
            result.extend([
                "",
                f"Request ID: {getattr(response.body, 'RequestId', 'N/A')}"
            ])
            
            return [TextContent(type="text", text="\n".join(result))]
        else:
            return [TextContent(type="text", text="Tagging operation completed, but no response body received.")]

    except Exception as e:
        logger.error(f"Error tagging PolarDB resources: {str(e)}")
        return [TextContent(type="text", text=f"Error tagging resources: {str(e)}")]

def polardb_create_db_endpoint_address(arguments: dict) -> list[TextContent]:
    """Create a new database endpoint address for a PolarDB cluster"""
    dbcluster_id = arguments.get("dbcluster_id")
    net_type = arguments.get("net_type")
    dbendpoint_id = arguments.get("dbendpoint_id")

    # Validate required parameters
    if not dbcluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]
    if not net_type:
        return [TextContent(type="text", text="Network type is required (Public, Private, or Inner)")]
    if not dbendpoint_id:
        return [TextContent(type="text", text="DB Endpoint ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for creating DB endpoint address
        request = polardb_20170801_models.CreateDBEndpointAddressRequest(
            dbcluster_id=dbcluster_id,
            net_type=net_type,
            dbendpoint_id=dbendpoint_id
        )

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.create_dbendpoint_address_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            result = [
                f"Successfully created DB endpoint address",
                f"Cluster ID: {dbcluster_id}",
                f"Endpoint ID: {dbendpoint_id}",
                f"Network Type: {net_type}",
                ""
            ]
            
            # Add connection string if available in response
            if hasattr(response.body, 'ConnectionString'):
                result.append(f"Connection String: {response.body.ConnectionString}")
            
            # Add other response details
            if hasattr(response.body, 'RequestId'):
                result.append(f"Request ID: {response.body.RequestId}")
            
            return [TextContent(type="text", text="\n".join(result))]
        else:
            return [TextContent(type="text", text="Endpoint address creation completed, but no response body received.")]

    except Exception as e:
        logger.error(f"Error creating PolarDB endpoint address: {str(e)}")
        return [TextContent(type="text", text=f"Error creating endpoint address: {str(e)}")]

def polardb_create_account(arguments: dict) -> list[TextContent]:
    """Create a database account for a PolarDB cluster"""
    dbcluster_id = arguments.get("dbcluster_id")
    account_name = arguments.get("account_name")
    account_password = arguments.get("account_password")
    account_type = arguments.get("account_type")
    account_description = arguments.get("account_description")
    db_name = arguments.get("db_name")
    account_privilege = arguments.get("account_privilege")

    # Validate required parameters
    if not dbcluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]
    if not account_name:
        return [TextContent(type="text", text="Account name is required")]
    if not account_password:
        return [TextContent(type="text", text="Account password is required")]

    # Validate account name format
    if len(account_name) < 2 or len(account_name) > 16:
        return [TextContent(type="text", text="Account name must be 2-16 characters long")]

    # Validate password strength
    if len(account_password) < 8 or len(account_password) > 32:
        return [TextContent(type="text", text="Account password must be 8-32 characters long")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for creating account
        request = polardb_20170801_models.CreateAccountRequest(
            dbcluster_id=dbcluster_id,
            account_name=account_name,
            account_password=account_password
        )

        # Set optional parameters if provided
        if account_type:
            request.account_type = account_type
        if account_description:
            request.account_description = account_description
        if db_name:
            request.db_name = db_name
        if account_privilege:
            request.account_privilege = account_privilege

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.create_account_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            result = [
                f"Successfully created database account",
                f"Cluster ID: {dbcluster_id}",
                f"Account Name: {account_name}",
                ""
            ]
            
            # Add optional parameters that were used
            if account_type:
                result.append(f"Account Type: {account_type}")
            if account_description:
                result.append(f"Description: {account_description}")
            if db_name:
                result.append(f"Database: {db_name}")
            if account_privilege:
                result.append(f"Privilege: {account_privilege}")
            
            result.append("")
            
            # Add response details
            if hasattr(response.body, 'RequestId'):
                result.append(f"Request ID: {response.body.RequestId}")
            
            # Security note
            result.extend([
                "",
                "🔒 SECURITY REMINDER:",
                "- Store the password securely",
                "- Consider changing the password after first login",
                "- Grant only necessary privileges to the account"
            ])
            
            return [TextContent(type="text", text="\n".join(result))]
        else:
            return [TextContent(type="text", text="Account creation completed, but no response body received.")]

    except Exception as e:
        logger.error(f"Error creating PolarDB account: {str(e)}")
        # Don't include the password in error messages for security
        return [TextContent(type="text", text=f"Error creating account '{account_name}': {str(e)}")]

def polardb_describe_accounts(arguments: dict) -> list[TextContent]:
    """List database accounts for a PolarDB cluster"""
    dbcluster_id = arguments.get("dbcluster_id")
    account_name = arguments.get("account_name")

    # Validate required parameters
    if not dbcluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing accounts
        request = polardb_20170801_models.DescribeAccountsRequest(
            dbcluster_id=dbcluster_id
        )

        # Set optional account name filter if provided
        if account_name:
            request.account_name = account_name

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_accounts_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Use to_map() for structured access
                response_dict = response.to_map()
                body = response_dict.get('body', {})
                
                # Look for accounts in the response - correct structure based on your example
                if 'Accounts' in body and body['Accounts']:
                    accounts = body['Accounts']
                    
                    # The accounts should already be a list based on your example
                    if not isinstance(accounts, list):
                        accounts = [accounts]
                    
                    result = [
                        f"Database Accounts for Cluster: {dbcluster_id}",
                        "=" * 60,
                        f"Total Accounts Found: {len(accounts)}",
                        ""
                    ]
                    
                    for i, account in enumerate(accounts, 1):
                        account_name = account.get('AccountName', 'N/A')
                        account_type = account.get('AccountType', 'N/A')
                        account_status = account.get('AccountStatus', 'N/A')
                        account_description = account.get('AccountDescription', 'No description')
                        account_lock_state = account.get('AccountLockState', 'N/A')
                        privilege_exceeded = account.get('PrivilegeExceeded', 'N/A')
                        password_valid_time = account.get('AccountPasswordValidTime', 'N/A')
                        database_privileges = account.get('DatabasePrivileges', [])
                        
                        # Handle empty description
                        if not account_description or account_description.strip() == "":
                            account_description = "No description provided"
                        
                        result.extend([
                            f"Account #{i}:",
                            f"  Name: {account_name}",
                            f"  Type: {account_type}",
                            f"  Status: {account_status}",
                            f"  Lock State: {account_lock_state}",
                            f"  Description: {account_description}",
                            f"  Privilege Exceeded: {privilege_exceeded}",
                            f"  Password Valid Time: {password_valid_time}",
                            ""
                        ])
                        
                        # Show database privileges if available
                        if database_privileges and len(database_privileges) > 0:
                            result.append("  Database Privileges:")
                            
                            # Handle both single privilege and list of privileges
                            if not isinstance(database_privileges, list):
                                database_privileges = [database_privileges]
                            
                            for priv in database_privileges:
                                if isinstance(priv, dict):
                                    db_name = priv.get('DBName', 'N/A')
                                    privilege = priv.get('AccountPrivilege', 'N/A')
                                    result.append(f"    • {db_name}: {privilege}")
                                else:
                                    result.append(f"    • {str(priv)}")
                            result.append("")
                        else:
                            result.append("  Database Privileges: None configured")
                            result.append("")
                    
                    # Add request ID
                    request_id = body.get('RequestId', 'N/A')
                    result.extend([
                        f"Request ID: {request_id}",
                        "",
                        "🔐 ACCOUNT MANAGEMENT NOTES:",
                        "• Super accounts have full cluster access",
                        "• Normal accounts can be restricted to specific databases",
                        "• UnLock state means account is accessible",
                        "• Use polardb_create_account to add new accounts"
                    ])
                    
                    return [TextContent(type="text", text="\n".join(result))]
                    
                else:
                    return [TextContent(type="text", text=f"No database accounts found for cluster {dbcluster_id}")]
                    
            except Exception as parse_error:
                logger.error(f"Error parsing accounts response: {str(parse_error)}")
                # Fallback to basic info with more details for debugging
                return [TextContent(type="text", text=(
                    f"Accounts query completed for cluster {dbcluster_id}\n"
                    f"Parse error: {str(parse_error)}\n"
                    f"Raw response keys: {list(response_dict.get('body', {}).keys()) if response_dict else 'No response_dict'}\n"
                    f"Response sample: {str(response_dict)[:500]}..."
                ))]
        else:
            return [TextContent(type="text", text=f"No response received for cluster {dbcluster_id}")]

    except Exception as e:
        logger.error(f"Error describing PolarDB accounts: {str(e)}")
        return [TextContent(type="text", text=f"Error retrieving accounts: {str(e)}")]


def polardb_describe_databases(arguments: dict) -> list[TextContent]:
    """List databases in a specific PolarDB cluster"""
    db_cluster_id = arguments.get("db_cluster_id")
    db_name = arguments.get("db_name")
    page_number = arguments.get("page_number", 1)
    page_size = arguments.get("page_size", 30)

    # Validate required parameters
    if not db_cluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing databases
        request = polardb_20170801_models.DescribeDatabasesRequest(
            dbcluster_id=db_cluster_id
        )

        # Set optional parameters if provided
        if db_name:
            request.dbname = db_name
        if page_number:
            request.page_number = page_number
        if page_size:
            request.page_size = page_size

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_databases_with_options(request, runtime)

        # Format the response
        if hasattr(response, 'body') and response.body:
            try:
                # Use to_map() for structured access
                response_dict = response.to_map()
                body = response_dict.get('body', {})
                
                # Build structured response
                result = [
                    f"DATABASE_LISTING_FOR_CLUSTER: {db_cluster_id}",
                    f"PAGE_NUMBER: {body.get('PageNumber', 'N/A')}",
                    f"PAGE_RECORD_COUNT: {body.get('PageRecordCount', 'N/A')}",
                    f"REQUEST_ID: {body.get('RequestId', 'N/A')}",
                    "=" * 60
                ]
                
                # Process databases
                if 'Databases' in body and 'Database' in body['Databases']:
                    databases = body['Databases']['Database']
                    
                    # Handle both single database and list of databases
                    if not isinstance(databases, list):
                        databases = [databases]
                    
                    result.append(f"TOTAL_DATABASES_FOUND: {len(databases)}")
                    result.append("")
                    
                    for i, database in enumerate(databases, 1):
                        db_name = database.get('DBName', 'N/A')
                        db_status = database.get('DBStatus', 'N/A')
                        db_description = database.get('DBDescription', 'No description')
                        character_set = database.get('CharacterSetName', 'N/A')
                        engine = database.get('Engine', 'N/A')
                        
                        # Handle empty description
                        if not db_description or db_description.strip() == "":
                            db_description = "No description provided"
                        
                        result.extend([
                            f"DATABASE_{i}:",
                            f"  NAME: {db_name}",
                            f"  STATUS: {db_status}",
                            f"  ENGINE: {engine}",
                            f"  CHARACTER_SET: {character_set}",
                            f"  DESCRIPTION: {db_description}",
                            ""
                        ])
                        
                        # Process accounts if available
                        if 'Accounts' in database and 'Account' in database['Accounts']:
                            accounts = database['Accounts']['Account']
                            
                            if accounts and len(accounts) > 0:
                                result.append(f"  ASSOCIATED_ACCOUNTS: {len(accounts)}")
                                
                                # Handle both single account and list of accounts
                                if not isinstance(accounts, list):
                                    accounts = [accounts]
                                
                                for j, account in enumerate(accounts, 1):
                                    account_name = account.get('AccountName', 'N/A')
                                    account_privilege = account.get('AccountPrivilege', 'N/A')
                                    result.append(f"    ACCOUNT_{j}: {account_name} ({account_privilege})")
                                result.append("")
                            else:
                                result.append(f"  ASSOCIATED_ACCOUNTS: None")
                                result.append("")
                        
                        result.append("-" * 40)
                        result.append("")
                    
                    # Add summary
                    result.extend([
                        "SUMMARY:",
                        f"  • Found {len(databases)} database(s) in cluster {db_cluster_id}",
                        f"  • Filter applied: {db_name if db_name else 'None (showing all databases)'}",
                        f"  • Page: {body.get('PageNumber', 'N/A')} (showing {body.get('PageRecordCount', 'N/A')} records)"
                    ])
                    
                else:
                    result.extend([
                        "NO_DATABASES_FOUND",
                        f"Cluster {db_cluster_id} has no databases or no access permissions",
                        f"Filter applied: {db_name if db_name else 'None'}"
                    ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing databases response: {str(parse_error)}")
                # Fallback to basic info
                return [TextContent(type="text", text=(
                    f"DATABASES_QUERY_COMPLETED: {db_cluster_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed"
                ))]
        else:
            return [TextContent(type="text", text=f"NO_RESPONSE_RECEIVED_FOR_CLUSTER: {db_cluster_id}")]

    except Exception as e:
        logger.error(f"Error describing PolarDB databases: {str(e)}")
        return [TextContent(type="text", text=f"ERROR_RETRIEVING_DATABASES: {str(e)}")]

def polardb_describe_db_cluster_access_whitelist(arguments: dict) -> list[TextContent]:
    """Describe the access whitelist configuration for a PolarDB cluster - Updated for actual API response"""
    dbcluster_id = arguments.get("dbcluster_id")

    # Validate required parameters
    if not dbcluster_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ CLIENT_ERROR: Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing DB cluster access whitelist
        request = polardb_20170801_models.DescribeDBClusterAccessWhitelistRequest(
            dbcluster_id=dbcluster_id
        )

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbcluster_access_whitelist_with_options(request, runtime)

        # Format the response based on actual API structure
        if hasattr(response, 'body') and response.body:
            try:
                response_dict = response.to_map()
                body = response_dict.get('body', {})
                
                # Build comprehensive response
                result = [
                    "=== POLARDB ACCESS WHITELIST CONFIGURATION ===",
                    f"CLUSTER_ID: {dbcluster_id}",
                    f"REQUEST_ID: {body.get('RequestId', 'N/A')}",
                    f"QUERY_TIME: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    "=" * 60
                ]
                
                # Process IP Arrays (main whitelist configuration)
                if 'Items' in body and 'DBClusterIPArray' in body['Items']:
                    ip_arrays = body['Items']['DBClusterIPArray']
                    
                    # Handle both single item and list of items
                    if not isinstance(ip_arrays, list):
                        ip_arrays = [ip_arrays]
                    
                    result.append(f"TOTAL_IP_ARRAYS: {len(ip_arrays)}")
                    result.append("")
                    
                    # Process each IP array
                    for i, ip_array in enumerate(ip_arrays, 1):
                        array_name = ip_array.get('DBClusterIPArrayName', 'Unknown')
                        security_ips = ip_array.get('SecurityIps', 'None')
                        array_attribute = ip_array.get('DBClusterIPArrayAttribute', '')
                        
                        # Handle empty attribute
                        if not array_attribute:
                            array_attribute = 'default'
                        
                        result.extend([
                            f"IP_ARRAY_{i}:",
                            f"  ARRAY_NAME: {array_name}",
                            f"  ARRAY_ATTRIBUTE: {array_attribute}",
                            f"  CONFIGURED_IPS: {security_ips}",
                            ""
                        ])
                        
                        # Detailed IP analysis
                        if security_ips and security_ips != 'None':
                            result.append("  IP_ANALYSIS:")
                            
                            ip_list = [ip.strip() for ip in security_ips.split(',') if ip.strip()]
                            for j, ip in enumerate(ip_list, 1):
                                # Handle different IP patterns based on your sample
                                if ip == '0.0.0.0' or ip == '0.0.0.0/0':
                                    result.extend([
                                        f"    IP_{j}: {ip}",
                                        f"    TYPE: OPEN_TO_ALL_INTERNET",
                                        f"    SECURITY_RISK: MAXIMUM_RISK",
                                        f"    DESCRIPTION: Allows access from any IP address worldwide",
                                        f"    RECOMMENDATION: ⚠️ CRITICAL - Restrict to specific IP ranges immediately",
                                        ""
                                    ])
                                elif ip.startswith('127.'):
                                    result.extend([
                                        f"    IP_{j}: {ip}",
                                        f"    TYPE: LOCALHOST_ONLY",
                                        f"    SECURITY_RISK: MINIMAL_RISK", 
                                        f"    DESCRIPTION: Local machine access only",
                                        f"    RECOMMENDATION: ✅ Suitable for development/testing",
                                        ""
                                    ])
                                elif ip.startswith('192.168.') or ip.startswith('10.') or ip.startswith('172.'):
                                    result.extend([
                                        f"    IP_{j}: {ip}",
                                        f"    TYPE: PRIVATE_NETWORK",
                                        f"    SECURITY_RISK: LOW_RISK",
                                        f"    DESCRIPTION: Internal network IP address",
                                        f"    RECOMMENDATION: ✅ Good for internal applications",
                                        ""
                                    ])
                                elif ip.startswith('100.104.'):
                                    # Alibaba Cloud internal IPs (based on your sample)
                                    result.extend([
                                        f"    IP_{j}: {ip}",
                                        f"    TYPE: ALIBABA_CLOUD_INTERNAL",
                                        f"    SECURITY_RISK: LOW_RISK",
                                        f"    DESCRIPTION: Alibaba Cloud internal service IP",
                                        f"    RECOMMENDATION: ✅ Required for cloud services",
                                        ""
                                    ])
                                elif '/' in ip:
                                    # CIDR notation
                                    try:
                                        network_size = int(ip.split('/')[-1])
                                        if network_size <= 16:
                                            risk_level = "HIGH_RISK"
                                            recommendation = "⚠️ Large network range - verify necessity"
                                        elif network_size <= 24:
                                            risk_level = "MEDIUM_RISK"
                                            recommendation = "🔍 Medium network range - review periodically"
                                        else:
                                            risk_level = "LOW_RISK"
                                            recommendation = "✅ Small network range - appropriate"
                                    except:
                                        risk_level = "UNKNOWN_RISK"
                                        recommendation = "❓ Invalid CIDR format - check configuration"
                                    
                                    result.extend([
                                        f"    IP_{j}: {ip}",
                                        f"    TYPE: SUBNET_RANGE",
                                        f"    SECURITY_RISK: {risk_level}",
                                        f"    DESCRIPTION: Network range access (/{ip.split('/')[-1]} subnet)",
                                        f"    RECOMMENDATION: {recommendation}",
                                        ""
                                    ])
                                else:
                                    result.extend([
                                        f"    IP_{j}: {ip}",
                                        f"    TYPE: SPECIFIC_IP",
                                        f"    SECURITY_RISK: LOW_RISK",
                                        f"    DESCRIPTION: Single IP address access",
                                        f"    RECOMMENDATION: ✅ Most secure option for known sources",
                                        ""
                                    ])
                        else:
                            result.extend([
                                "  IP_ANALYSIS: No IPs configured in this array",
                                ""
                            ])
                        
                        result.append("-" * 50)
                        result.append("")
                
                # Process Security Groups (if any)
                if 'DBClusterSecurityGroups' in body and 'DBClusterSecurityGroup' in body['DBClusterSecurityGroups']:
                    security_groups = body['DBClusterSecurityGroups']['DBClusterSecurityGroup']
                    
                    result.extend([
                        "=== SECURITY GROUPS CONFIGURATION ===",
                        ""
                    ])
                    
                    if security_groups and len(security_groups) > 0:
                        if not isinstance(security_groups, list):
                            security_groups = [security_groups]
                        
                        result.append(f"TOTAL_SECURITY_GROUPS: {len(security_groups)}")
                        result.append("")
                        
                        for i, sg in enumerate(security_groups, 1):
                            sg_id = sg.get('SecurityGroupId', 'N/A')
                            sg_name = sg.get('SecurityGroupName', 'N/A')
                            result.extend([
                                f"SECURITY_GROUP_{i}:",
                                f"  GROUP_ID: {sg_id}",
                                f"  GROUP_NAME: {sg_name}",
                                ""
                            ])
                    else:
                        result.extend([
                            "TOTAL_SECURITY_GROUPS: 0",
                            "STATUS: No security groups configured",
                            ""
                        ])
                
                # Overall security assessment based on actual data
                all_ips = []
                hidden_arrays = 0
                default_arrays = 0
                
                if 'Items' in body and 'DBClusterIPArray' in body['Items']:
                    for ip_array in body['Items']['DBClusterIPArray']:
                        security_ips = ip_array.get('SecurityIps', '')
                        array_attribute = ip_array.get('DBClusterIPArrayAttribute', '')
                        
                        if security_ips:
                            all_ips.extend([ip.strip() for ip in security_ips.split(',') if ip.strip()])
                        
                        if array_attribute == 'hidden':
                            hidden_arrays += 1
                        else:
                            default_arrays += 1
                
                result.extend([
                    "=== SECURITY ASSESSMENT ===",
                    ""
                ])
                
                has_open_access = any(ip in ['0.0.0.0', '0.0.0.0/0'] for ip in all_ips)
                has_cloud_internal = any(ip.startswith('100.104.') for ip in all_ips)
                has_private_network = any(ip.startswith(('192.168.', '10.', '172.')) for ip in all_ips)
                has_specific_ips = any('/' not in ip and not ip.startswith(('0.0.0.0', '127.', '100.104.')) for ip in all_ips)
                
                if has_open_access:
                    result.extend([
                        "🔴 CRITICAL_SECURITY_ALERT: OPEN_INTERNET_ACCESS",
                        "RISK_LEVEL: MAXIMUM",
                        "IMPACT: Database accessible from anywhere on the internet",
                        "IMMEDIATE_ACTION_REQUIRED: Restrict access to specific IP ranges",
                        ""
                    ])
                
                if has_cloud_internal:
                    result.extend([
                        "🔵 CLOUD_SERVICE_ACCESS: ALIBABA_CLOUD_INTERNAL",
                        "RISK_LEVEL: LOW",
                        "IMPACT: Required for Alibaba Cloud internal services",
                        "STATUS: Normal cloud service configuration",
                        ""
                    ])
                
                if has_private_network:
                    result.extend([
                        "🟡 PRIVATE_NETWORK_ACCESS: INTERNAL_NETWORKS",
                        "RISK_LEVEL: LOW_TO_MEDIUM",
                        "IMPACT: Access from internal networks configured",
                        "RECOMMENDATION: Verify network security policies",
                        ""
                    ])
                
                if has_specific_ips:
                    result.extend([
                        "🟢 SPECIFIC_IP_ACCESS: RESTRICTED_ACCESS",
                        "RISK_LEVEL: LOW",
                        "IMPACT: Access limited to specific IP addresses",
                        "STATUS: Good security practice",
                        ""
                    ])
                
                # Final summary
                result.extend([
                    "=== CONFIGURATION SUMMARY ===",
                    f"CLUSTER: {dbcluster_id}",
                    f"TOTAL_IP_ARRAYS: {default_arrays + hidden_arrays}",
                    f"  • Default Arrays: {default_arrays}",
                    f"  • Hidden Arrays: {hidden_arrays} (system managed)",
                    f"TOTAL_CONFIGURED_IPS: {len(all_ips)}",
                    f"CONFIGURED_IP_LIST: {', '.join(all_ips) if all_ips else 'None'}",
                    "",
                    "SECURITY_STATUS_SUMMARY:",
                    f"  ❌ Open Internet Access: {'YES - CRITICAL RISK' if has_open_access else 'NO'}",
                    f"  🔵 Cloud Internal Access: {'YES' if has_cloud_internal else 'NO'}",
                    f"  🟡 Private Network Access: {'YES' if has_private_network else 'NO'}",
                    f"  ✅ Specific IP Access: {'YES' if has_specific_ips else 'NO'}",
                    "",
                    "NEXT_STEPS:",
                    "  • Use polardb_modify_db_cluster_access_whitelist to update IPs",
                    "  • Regular security reviews recommended",
                    "  • Monitor access logs for unusual activity"
                ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing whitelist response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"WHITELIST_QUERY_COMPLETED: {dbcluster_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed\n"
                    f"RAW_DATA_SAMPLE: {str(response_dict)[:500]}..."
                ))]
            
        else:
            return [TextContent(type="text", text=f"NO_API_RESPONSE_FOR_CLUSTER: {dbcluster_id}")]

    except Exception as e:
        logger.error(f"Error describing PolarDB cluster access whitelist: {str(e)}")
        return [TextContent(type="text", text=f"API_ERROR: {str(e)}")]

def polardb_describe_db_cluster_connectivity(arguments: dict) -> list[TextContent]:
    """Test connectivity to a PolarDB cluster from a specific source IP address with comprehensive validation and detailed analysis"""
    dbcluster_id = arguments.get("dbcluster_id")
    source_ip_address = arguments.get("source_ip_address")

    # Validate required parameters
    if not dbcluster_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: DB Cluster ID is required")]
    
    if not source_ip_address:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: Source IP address is required")]

    # Validate dbcluster_id format - must start with "pc-"
    if not dbcluster_id.startswith("pc-"):
        return [TextContent(type="text", text=(
            f"❌ INVALID_CLUSTER_ID_FORMAT: DB Cluster ID must start with 'pc-'\n"
            f"Provided: '{dbcluster_id}'\n"
            f"Expected format: 'pc-xxxxxxxxxxxxxxxxx'\n\n"
            f"COMMON_MISTAKES:\n"
            f"• Using node ID (pi-xxxxx) instead of cluster ID (pc-xxxxx)\n"
            f"• Missing 'pc-' prefix\n"
            f"• Using incorrect resource type identifier\n\n"
            f"HOW_TO_FIND_CORRECT_CLUSTER_ID:\n"
            f"1. Use polardb_describe_db_clusters to list clusters in your region\n"
            f"2. Use polardb_describe_db_cluster to get specific cluster details\n"
            f"3. Check cluster endpoints with polardb_describe_db_cluster_endpoints\n\n"
            f"EXAMPLE_VALID_CLUSTER_IDS:\n"
            f"• pc-1udt379icjl5032b1\n"
            f"• pc-dj19438m571u1f41d\n"
            f"• pc-abc123def456ghi789"
        ))]

    # Additional validation for cluster ID length
    if len(dbcluster_id) < 5:  # "pc-" + at least 2 characters
        return [TextContent(type="text", text=(
            f"❌ INVALID_CLUSTER_ID_LENGTH: DB Cluster ID appears too short\n"
            f"Provided: '{dbcluster_id}' ({len(dbcluster_id)} characters)\n"
            f"Expected: 'pc-' followed by alphanumeric identifier (typically 17+ characters total)\n"
            f"Example: 'pc-1udt379icjl5032b1'"
        ))]

    # Validate IP address format
    import re
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(ip_pattern, source_ip_address):
        return [TextContent(type="text", text=(
            f"❌ INVALID_IP_FORMAT: Source IP address format is invalid\n"
            f"Provided: '{source_ip_address}'\n"
            f"Expected format: 'xxx.xxx.xxx.xxx' (IPv4 address)\n"
            f"Examples: '192.168.1.100', '10.0.0.50', '172.16.0.10'"
        ))]

    # Validate IP address ranges
    try:
        ip_parts = [int(part) for part in source_ip_address.split('.')]
        if any(part < 0 or part > 255 for part in ip_parts):
            return [TextContent(type="text", text=(
                f"❌ INVALID_IP_RANGE: IP address octets must be between 0-255\n"
                f"Provided: '{source_ip_address}'\n"
                f"Invalid octets: {[part for part in ip_parts if part < 0 or part > 255]}"
            ))]
    except ValueError:
        return [TextContent(type="text", text=(
            f"❌ INVALID_IP_CONTENT: IP address contains non-numeric values\n"
            f"Provided: '{source_ip_address}'"
        ))]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ CLIENT_ERROR: Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for testing DB cluster connectivity
        request = polardb_20170801_models.DescribeDBClusterConnectivityRequest(
            dbcluster_id=dbcluster_id,
            source_ip_address=source_ip_address
        )

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbcluster_connectivity_with_options(request, runtime)

        # Format the response with comprehensive details
        if hasattr(response, 'body') and response.body:
            try:
                # Convert to dictionary for easier access
                response_dict = response.body.to_map() if hasattr(response.body, 'to_map') else response.body.__dict__
                
                result = [
                    "=== POLARDB CLUSTER CONNECTIVITY TEST RESULT ===",
                    f"🎯 TARGET_CLUSTER: {dbcluster_id}",
                    f"🌐 SOURCE_IP: {source_ip_address}",
                    f"🔧 OPERATION_TYPE: Connectivity Test",
                    f"📅 TIMESTAMP: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    "=" * 60,
                    ""
                ]
                
                # Extract connectivity test results
                conn_check_result = response_dict.get('ConnCheckResult', 'Unknown')
                cluster_id_response = response_dict.get('DBClusterId', 'Unknown')
                request_id = response_dict.get('RequestId', 'N/A')
                
                # Check for connectivity errors
                error_code = response_dict.get('ConnCheckErrorCode')
                error_message = response_dict.get('ConnCheckErrorMessage')
                
                # Determine test result and provide detailed analysis
                if conn_check_result == 'Success':
                    result.extend([
                        "CONNECTIVITY_TEST_RESULT:",
                        f"  STATUS: ✅ SUCCESS",
                        f"  RESULT: {conn_check_result}",
                        f"  CLUSTER_CONFIRMED: {cluster_id_response}",
                        f"  SOURCE_IP_VERIFIED: {source_ip_address}",
                        ""
                    ])
                    
                    # Success analysis
                    result.extend([
                        "SUCCESS_ANALYSIS:",
                        f"  🟢 NETWORK_CONNECTIVITY: Established successfully",
                        f"  🟢 IP_WHITELIST_STATUS: Source IP is allowed in cluster whitelist",
                        f"  🟢 CLUSTER_ACCESSIBILITY: Cluster is reachable from source IP",
                        f"  🟢 SECURITY_CONFIGURATION: Access permissions properly configured",
                        ""
                    ])
                    
                elif conn_check_result == 'Failed':
                    result.extend([
                        "CONNECTIVITY_TEST_RESULT:",
                        f"  STATUS: ❌ FAILED",
                        f"  RESULT: {conn_check_result}",
                        f"  CLUSTER_ID: {cluster_id_response}",
                        f"  SOURCE_IP_TESTED: {source_ip_address}",
                        ""
                    ])
                    
                    # Error details
                    if error_code and error_message:
                        result.extend([
                            "FAILURE_DETAILS:",
                            f"  ERROR_CODE: {error_code}",
                            f"  ERROR_MESSAGE: {error_message}",
                            ""
                        ])
                        
                        # Specific error analysis and solutions
                        if error_code == 'SRC_IP_NOT_IN_USER_WHITELIST':
                            result.extend([
                                "IMMEDIATE_SOLUTION:",
                                f"  🔧 ADD_TO_WHITELIST: Use polardb_modify_db_cluster_access_whitelist",
                                f"  📋 REQUIRED_PARAMETERS:",
                                f"    • dbcluster_id: {dbcluster_id}",
                                f"    • security_ips: '{source_ip_address}' (or appropriate CIDR range)",
                                f"    • modify_mode: 'Append' (to add without removing existing IPs)",
                                ""
                            ])
                
                # Final status
                result.extend([
                    "=" * 60,
                    f"{'✅ CONNECTIVITY TEST SUCCESSFUL' if conn_check_result == 'Success' else '❌ CONNECTIVITY TEST FAILED'}",
                    f"Cluster: {dbcluster_id}",
                    f"Source IP: {source_ip_address}",
                    f"Result: {conn_check_result}",
                    f"Request ID: {request_id}",
                    "=" * 60
                ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing connectivity test response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"CONNECTIVITY_TEST_COMPLETED: {dbcluster_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed"
                ))]
        else:
            return [TextContent(type="text", text=f"⚠️  PARTIAL_SUCCESS: Connectivity test completed but no response details received for cluster {dbcluster_id}")]

    except Exception as e:
        logger.error(f"Error testing PolarDB cluster connectivity: {str(e)}")
        return [TextContent(type="text", text=f"❌ CONNECTIVITY_TEST_FAILED: {str(e)}")]

def polardb_describe_db_cluster_endpoints(arguments: dict) -> list[TextContent]:
    """List database endpoints for a specific PolarDB cluster"""
    db_cluster_id = arguments.get("db_cluster_id")

    # Validate required parameters
    if not db_cluster_id:
        return [TextContent(type="text", text="❌ MISSING_PARAMETER: DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="❌ CLIENT_ERROR: Failed to create PolarDB client. Please check your credentials.")]

    try:
        # Create request for describing DB cluster endpoints
        request = polardb_20170801_models.DescribeDBClusterEndpointsRequest(
            dbcluster_id=db_cluster_id
        )

        runtime = util_models.RuntimeOptions()

        # Call the API
        response = client.describe_dbcluster_endpoints_with_options(request, runtime)

        # Format the response based on actual API structure
        if hasattr(response, 'body') and response.body:
            try:
                # Use to_map() for structured access
                response_dict = response.to_map()
                body = response_dict.get('body', {})
                
                # Build comprehensive response
                result = [
                    "=== POLARDB CLUSTER ENDPOINTS CONFIGURATION ===",
                    f"CLUSTER_ID: {db_cluster_id}",
                    f"REQUEST_ID: {body.get('RequestId', 'N/A')}",
                    f"QUERY_TIME: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    "=" * 60
                ]
                
                # Process endpoints
                if 'Items' in body and body['Items']:
                    endpoints = body['Items']
                    
                    # Handle both single endpoint and list of endpoints
                    if not isinstance(endpoints, list):
                        endpoints = [endpoints]
                    
                    result.append(f"TOTAL_ENDPOINTS: {len(endpoints)}")
                    result.append("")
                    
                    for i, endpoint in enumerate(endpoints, 1):
                        endpoint_id = endpoint.get('DBEndpointId', 'N/A')
                        endpoint_type = endpoint.get('EndpointType', 'N/A')
                        read_write_mode = endpoint.get('ReadWriteMode', 'N/A')
                        auto_add_nodes = endpoint.get('AutoAddNewNodes', 'N/A')
                        nodes = endpoint.get('Nodes', 'N/A')
                        endpoint_config = endpoint.get('EndpointConfig', '{}')
                        
                        result.extend([
                            f"ENDPOINT_{i}:",
                            f"  ENDPOINT_ID: {endpoint_id}",
                            f"  ENDPOINT_TYPE: {endpoint_type}",
                            f"  READ_WRITE_MODE: {read_write_mode}",
                            f"  AUTO_ADD_NEW_NODES: {auto_add_nodes}",
                            f"  ASSOCIATED_NODES: {nodes}",
                            ""
                        ])
                        
                        # Parse and display endpoint configuration
                        if endpoint_config and endpoint_config != '{}':
                            result.append("  ENDPOINT_CONFIGURATION:")
                            try:
                                import json
                                config_dict = json.loads(endpoint_config)
                                
                                # Group configurations by category for better readability
                                connection_configs = {}
                                performance_configs = {}
                                security_configs = {}
                                other_configs = {}
                                
                                for key, value in config_dict.items():
                                    key_lower = key.lower()
                                    if any(term in key_lower for term in ['connect', 'persist', 'pool', 'timeout']):
                                        connection_configs[key] = value
                                    elif any(term in key_lower for term in ['parallel', 'balance', 'throttle', 'performance']):
                                        performance_configs[key] = value
                                    elif any(term in key_lower for term in ['strict', 'security', 'auth']):
                                        security_configs[key] = value
                                    else:
                                        other_configs[key] = value
                                
                                if connection_configs:
                                    result.append("    CONNECTION_SETTINGS:")
                                    for key, value in connection_configs.items():
                                        result.append(f"      {key}: {value}")
                                    result.append("")
                                
                                if performance_configs:
                                    result.append("    PERFORMANCE_SETTINGS:")
                                    for key, value in performance_configs.items():
                                        result.append(f"      {key}: {value}")
                                    result.append("")
                                
                                if security_configs:
                                    result.append("    SECURITY_SETTINGS:")
                                    for key, value in security_configs.items():
                                        result.append(f"      {key}: {value}")
                                    result.append("")
                                
                                if other_configs:
                                    result.append("    OTHER_SETTINGS:")
                                    for key, value in other_configs.items():
                                        result.append(f"      {key}: {value}")
                                    result.append("")
                                
                            except json.JSONDecodeError:
                                result.append(f"    RAW_CONFIG: {endpoint_config}")
                                result.append("")
                        else:
                            result.append("  ENDPOINT_CONFIGURATION: Default (no custom settings)")
                            result.append("")
                        
                        # Process address items (connection details)
                        if 'AddressItems' in endpoint and endpoint['AddressItems']:
                            address_items = endpoint['AddressItems']
                            
                            if not isinstance(address_items, list):
                                address_items = [address_items]
                            
                            result.append(f"  CONNECTION_ADDRESSES: {len(address_items)}")
                            result.append("")
                            
                            for j, address in enumerate(address_items, 1):
                                connection_string = address.get('ConnectionString', 'N/A')
                                ip_address = address.get('IPAddress', 'N/A')
                                net_type = address.get('NetType', 'N/A')
                                port = address.get('Port', 'N/A')
                                vpc_id = address.get('VPCId', 'N/A')
                                vswitch_id = address.get('VSwitchId', 'N/A')
                                vpc_instance_id = address.get('VpcInstanceId', 'N/A')
                                
                                # Determine network type description
                                if net_type == 'Private':
                                    net_desc = "Internal VPC network (secure)"
                                elif net_type == 'Public':
                                    net_desc = "Public internet (external access)"
                                else:
                                    net_desc = "Unknown network type"
                                
                                result.extend([
                                    f"    ADDRESS_{j}:",
                                    f"      CONNECTION_STRING: {connection_string}",
                                    f"      IP_ADDRESS: {ip_address}",
                                    f"      NETWORK_TYPE: {net_type} ({net_desc})",
                                    f"      PORT: {port}",
                                    ""
                                ])
                                
                                # Add VPC details if available
                                if vpc_id and vpc_id != '':
                                    result.extend([
                                        f"      VPC_DETAILS:",
                                        f"        VPC_ID: {vpc_id}",
                                        f"        VSWITCH_ID: {vswitch_id}",
                                        f"        VPC_INSTANCE_ID: {vpc_instance_id}",
                                        ""
                                    ])
                                else:
                                    result.append("      VPC_DETAILS: Not applicable (public network)")
                                    result.append("")
                        else:
                            result.append("  CONNECTION_ADDRESSES: None configured")
                            result.append("")
                        
                        result.append("-" * 50)
                        result.append("")
                    
                    # Summary and analysis
                    result.extend([
                        "=== ENDPOINT ANALYSIS ===",
                        ""
                    ])
                    
                    # Analyze endpoint types
                    cluster_endpoints = [e for e in endpoints if e.get('EndpointType') == 'Cluster']
                    primary_endpoints = [e for e in endpoints if e.get('EndpointType') == 'Primary']
                    custom_endpoints = [e for e in endpoints if e.get('EndpointType') not in ['Cluster', 'Primary']]
                    
                    # Analyze network access
                    public_endpoints = []
                    private_endpoints = []
                    
                    for endpoint in endpoints:
                        if 'AddressItems' in endpoint:
                            for address in endpoint['AddressItems']:
                                if address.get('NetType') == 'Public':
                                    public_endpoints.append(endpoint.get('DBEndpointId', 'Unknown'))
                                elif address.get('NetType') == 'Private':
                                    private_endpoints.append(endpoint.get('DBEndpointId', 'Unknown'))
                    
                    result.extend([
                        "ENDPOINT_TYPE_SUMMARY:",
                        f"  • Cluster Endpoints: {len(cluster_endpoints)} (load-balanced read/write)",
                        f"  • Primary Endpoints: {len(primary_endpoints)} (direct primary access)",
                        f"  • Custom Endpoints: {len(custom_endpoints)} (user-defined)",
                        "",
                        "NETWORK_ACCESS_SUMMARY:",
                        f"  • Public Internet Access: {len(set(public_endpoints))} endpoint(s)",
                        f"  • Private VPC Access: {len(set(private_endpoints))} endpoint(s)",
                        ""
                    ])
                    
                    if public_endpoints:
                        result.extend([
                            "🔴 SECURITY_NOTICE: Public endpoints detected",
                            f"Endpoints with public access: {', '.join(set(public_endpoints))}",
                            "Recommendation: Ensure proper access whitelist configuration",
                            ""
                        ])
                    
                    # Final summary
                    result.extend([
                        "=== CONNECTION SUMMARY ===",
                        f"CLUSTER: {db_cluster_id}",
                        f"TOTAL_ENDPOINTS: {len(endpoints)}",
                        f"ENDPOINTS_WITH_PUBLIC_ACCESS: {len(set(public_endpoints))}",
                        f"ENDPOINTS_WITH_PRIVATE_ACCESS: {len(set(private_endpoints))}",
                        "",
                        "USAGE_RECOMMENDATIONS:",
                        "  • Use Cluster endpoints for load-balanced applications",
                        "  • Use Primary endpoints for admin tasks requiring write access",
                        "  • Configure access whitelist for public endpoints",
                        "  • Monitor endpoint performance and connection usage",
                        "",
                        "RELATED_TOOLS:",
                        "  • Use polardb_describe_db_cluster_access_whitelist to check IP restrictions",
                        "  • Use polardb_modify_db_cluster_access_whitelist to update access rules",
                        "  • Use polardb_create_db_endpoint_address to add new endpoint addresses"
                    ])
                    
                else:
                    result.extend([
                        "NO_ENDPOINTS_FOUND",
                        f"Cluster {db_cluster_id} has no configured endpoints",
                        "This may indicate a configuration issue or cluster setup problem"
                    ])
                
                return [TextContent(type="text", text="\n".join(result))]
                
            except Exception as parse_error:
                logger.error(f"Error parsing endpoints response: {str(parse_error)}")
                return [TextContent(type="text", text=(
                    f"ENDPOINTS_QUERY_COMPLETED: {db_cluster_id}\n"
                    f"PARSE_ERROR: {str(parse_error)}\n"
                    f"RAW_RESPONSE: Available but parsing failed\n"
                    f"RAW_DATA_SAMPLE: {str(response_dict)[:500]}..."
                ))]
        else:
            return [TextContent(type="text", text=f"NO_API_RESPONSE_FOR_CLUSTER: {db_cluster_id}")]

    except Exception as e:
        logger.error(f"Error describing PolarDB cluster endpoints: {str(e)}")
        return [TextContent(type="text", text=f"API_ERROR: {str(e)}")]    

def polardb_describe_db_cluster_parameters(arguments: dict) -> list[TextContent]:
    """Get PolarDB cluster parameters"""
    db_cluster_id = arguments.get("db_cluster_id")
    
    if not db_cluster_id:
        return [TextContent(type="text", text="DB Cluster ID is required")]

    client = create_client()
    if not client:
        return [TextContent(type="text", text="Failed to create PolarDB client. Please check your credentials.")]

    try:
        request = polardb_20170801_models.DescribeDBClusterParametersRequest(
            dbcluster_id=db_cluster_id
        )
        runtime = util_models.RuntimeOptions()
        
        response = client.describe_dbcluster_parameters_with_options(request, runtime)
        
        # Parse the response to get parameters
        running_parameters = response.body.running_parameters
        parameters = []
        
        if running_parameters and hasattr(running_parameters, 'parameter'):
            parameters = running_parameters.parameter
        
        # Categorize parameters for better organization
        categorized_params = _categorize_parameters(parameters)
        
        # Build response
        result = [
            f"=== POLARDB CLUSTER PARAMETERS ===",
            f"CLUSTER_ID: {db_cluster_id}",
            f"DB_TYPE: {response.body.dbtype}",
            f"DB_VERSION: {response.body.dbversion}",
            f"ENGINE: {response.body.engine}",
            f"REQUEST_ID: {response.body.request_id}",
            f"TOTAL_PARAMETERS: {len(parameters)}",
            "=" * 60,
            ""
        ]
        
        # Show important parameters from each category
        for category, params in categorized_params.items():
            if params:
                result.append(f"📁 {category.upper()} ({len(params)} parameters):")
                
                # Show top 3-5 most important parameters in each category
                important_params = params[:5]  # Limit to first 5 to avoid overwhelming output
                
                for param in important_params:
                    param_name = param.parameter_name
                    param_value = param.parameter_value
                    default_value = param.default_parameter_value
                    description = param.parameter_description[:100] + "..." if len(param.parameter_description or "") > 100 else param.parameter_description or "No description"
                    is_modifiable = "✅" if param.is_modifiable else "❌"
                    force_restart = "🔄" if param.force_restart else "⚡"
                    
                    result.extend([
                        f"  PARAMETER: {param_name}",
                        f"    VALUE: {param_value}",
                        f"    DEFAULT: {default_value}",
                        f"    MODIFIABLE: {is_modifiable} RESTART_REQUIRED: {force_restart}",
                        f"    DESCRIPTION: {description}",
                        ""
                    ])
                
                if len(params) > 5:
                    result.append(f"    ... and {len(params) - 5} more parameters in this category")
                    result.append("")
        
        # Add summary
        result.extend([
            "=" * 60,
            "PARAMETER_SUMMARY:",
            f"  • Total parameters: {len(parameters)}",
            f"  • Modifiable parameters: {sum(1 for p in parameters if p.is_modifiable)}",
            f"  • Parameters requiring restart: {sum(1 for p in parameters if p.force_restart)}",
            "",
            "USAGE_NOTES:",
            "  • Use polardb_modify_db_node_parameters to change modifiable parameters",
            "  • Parameters marked 🔄 require database restart to take effect",
            "  • Parameters marked ⚡ take effect immediately",
            "  • Only parameters marked ✅ can be modified"
        ])
        
        return [TextContent(type="text", text="\n".join(result))]
        
    except Exception as e:
        logger.error(f"Error describing DB cluster parameters: {str(e)}")
        return [TextContent(type="text", text=f"ERROR: {str(e)}")]

def _categorize_parameters(parameters):
    """Categorize parameters by their function"""
    categories = {
        "Memory & Performance": [],
        "Connection & Security": [],
        "Logging & Monitoring": [],
        "Storage & I/O": [],
        "Replication & Clustering": [],
        "Engine Specific": [],
        "Other": []
    }
    
    memory_keywords = ['memory', 'buffer', 'cache', 'heap', 'sort']
    connection_keywords = ['connection', 'timeout', 'user', 'password', 'ssl', 'auth', 'max_connections']
    logging_keywords = ['log', 'slow', 'audit', 'trace', 'monitor']
    storage_keywords = ['storage', 'file', 'disk', 'io', 'flush', 'sync']
    replication_keywords = ['replica', 'slave', 'master', 'cluster', 'sync', 'standby']
    engine_keywords = ['innodb', 'xengine', 'imci', 'myisam']
    
    for param in parameters:
        param_name = param.parameter_name.lower()
        param_desc = (param.parameter_description or "").lower()
        
        categorized = False
        
        # Check each category
        if any(keyword in param_name or keyword in param_desc for keyword in memory_keywords):
            categories["Memory & Performance"].append(param)
            categorized = True
        elif any(keyword in param_name or keyword in param_desc for keyword in connection_keywords):
            categories["Connection & Security"].append(param)
            categorized = True
        elif any(keyword in param_name or keyword in param_desc for keyword in logging_keywords):
            categories["Logging & Monitoring"].append(param)
            categorized = True
        elif any(keyword in param_name or keyword in param_desc for keyword in storage_keywords):
            categories["Storage & I/O"].append(param)
            categorized = True
        elif any(keyword in param_name or keyword in param_desc for keyword in replication_keywords):
            categories["Replication & Clustering"].append(param)
            categorized = True
        elif any(keyword in param_name or keyword in param_desc for keyword in engine_keywords):
            categories["Engine Specific"].append(param)
            categorized = True
        
        if not categorized:
            categories["Other"].append(param)
    
    return categories

# ADD this helper function to create structured responses for other tools:

def create_anti_hallucination_response(data_type: str, cluster_id: str, key_data: dict) -> str:
    """Create a structured response that prevents LLM hallucination"""
    
    lines = [
        f"=== POLARDB {data_type.upper()} QUERY RESULT ===",
        f"CLUSTER_ID: {cluster_id}",
        f"DATA_TYPE: {data_type}",
        ""
    ]
    
    # Add structured data
    for key, value in key_data.items():
        lines.extend([
            f"{key.upper()}: {value}",
            f"{key.upper()}_CONFIRMED: YES",
            ""
        ])
    
    lines.extend([
        f"=== END {data_type.upper()} RESULT ===",
        f"THE_ABOVE_IS_THE_ACTUAL_CURRENT_DATA_FOR: {cluster_id}",
        "USE_THE_EXACT_VALUES_SHOWN_ABOVE_IN_YOUR_RESPONSE"
    ])
    
    return "\n".join(lines)

# Enhanced prompt manager guidance for region search strategy
def update_prompt_manager_for_prioritized_search():
    """Update the prompt manager to include prioritized search guidance"""
    
    prioritized_search_guidance = """
PRIORITIZED REGION SEARCH STRATEGY:
1. Always search priority regions FIRST: cn-hangzhou, cn-beijing, cn-shanghai
2. These regions are known to contain PolarDB clusters
3. Search systematically through priority regions before checking others
4. Report findings from priority regions immediately
5. Continue with remaining regions only if needed for comprehensive search
"""
    
    # Add to prompt manager sections
    prompt_manager.sections["prioritized_search"] = prioritized_search_guidance

# Enhanced polardb_describe_db_clusters with better error handling and region awareness
def enhanced_polardb_describe_db_clusters_with_priority(arguments: dict) -> list[TextContent]:
    """Enhanced version that provides better feedback for priority regions"""
    
    region_id = arguments.get("region_id")
    if not region_id:
        return [TextContent(type="text", text="Region ID is required")]
    
    # Check if this is a priority region
    priority_regions = ["cn-hangzhou", "cn-beijing", "cn-shanghai"]
    is_priority = region_id in priority_regions
    
    # Call the original function
    result = polardb_describe_db_clusters(arguments)
    
    # Enhance the result with priority region context
    if result and len(result) > 0:
        original_text = result[0].text
        
        # Add priority region context
        if is_priority:
            if "No PolarDB clusters found" in original_text:
                enhanced_text = f"⚠️  PRIORITY REGION {region_id}: {original_text}\n\nNote: This is a priority region where clusters are expected. Please verify credentials and region access."
            else:
                enhanced_text = f"🎯 PRIORITY REGION {region_id}: Clusters found!\n\n{original_text}"
        else:
            enhanced_text = f"📍 Region {region_id}:\n{original_text}"
        
        return [TextContent(type="text", text=enhanced_text)]
    
    return result

# Updated guidance for region search operations
def generate_priority_region_guidance(tool_name: str, arguments: dict) -> str:
    """Generate guidance that emphasizes priority region search"""
    
    if "describe_db_clusters" in tool_name.lower():
        region_id = arguments.get("region_id", "")
        priority_regions = ["cn-hangzhou", "cn-beijing", "cn-shanghai"]
        
        if region_id in priority_regions:
            return f"""
🎯 PRIORITY REGION SEARCH: {region_id}
This is a high-priority region where PolarDB clusters are known to exist.

CRITICAL PARSING INSTRUCTIONS:
1. Look for response.body.Items.DBCluster or response.body.items.dbcluster
2. Handle both single cluster and list of clusters
3. Check multiple attribute name variations (DBClusterId, db_cluster_id, etc.)
4. If no clusters found, this indicates a parsing issue, not absence of clusters

EXPECTED: This region should contain PolarDB clusters based on user confirmation.
"""
        else:
            return f"""
📍 STANDARD REGION SEARCH: {region_id}
This is a standard region check after priority regions.

SEARCH STRATEGY:
1. Priority regions (cn-hangzhou, cn-beijing, cn-shanghai) should be checked first
2. Use same careful parsing as priority regions
3. Empty results in non-priority regions are expected
"""
    
    return ""

# Update the enhanced_tool_call decorator to use priority guidance
def enhanced_tool_call_with_priority(tool_func):
    """Enhanced decorator that includes priority region guidance"""
    def wrapper(arguments: dict = None) -> List[TextContent]:
        arguments = arguments or {}
        tool_name = tool_func.__name__
        
        try:
            # Execute the original tool
            result = tool_func(arguments)
            
            # Update conversation context
            prompt_manager.update_conversation_context(tool_name, arguments, result)
            
            # Generate priority-aware guidance
            if "describe_db_clusters" in tool_name:
                priority_guidance = generate_priority_region_guidance(tool_name, arguments)
                if priority_guidance:
                    enhanced_result = result + [
                        TextContent(
                            type="text", 
                            text=f"\n\n💡 PRIORITY SEARCH GUIDANCE:\n{priority_guidance}"
                        )
                    ]
                    return enhanced_result
            
            return result
            
        except Exception as e:
            # Track error with priority context
            prompt_manager.add_error(str(e), tool_name)
            
            region_id = arguments.get("region_id", "unknown")
            priority_regions = ["cn-hangzhou", "cn-beijing", "cn-shanghai"]
            is_priority = region_id in priority_regions
            
            error_context = f"🚨 ERROR in {'PRIORITY' if is_priority else 'STANDARD'} region {region_id}: {str(e)}"
            
            if is_priority:
                error_context += f"\n\nThis is critical - {region_id} is a priority region where clusters should exist."
            
            return [TextContent(type="text", text=error_context)]
    
    return wrapper

# Apply enhanced decorator to the clusters function
@enhanced_tool_call_with_priority  
def priority_aware_polardb_describe_db_clusters(arguments: dict) -> List[TextContent]:
    """Priority-aware version of describe_db_clusters"""
    return enhanced_polardb_describe_db_clusters_with_priority(arguments)

# Update the tool call handler to use priority guidance
@app.call_tool()
async def enhanced_call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info(f"Calling enhanced tool: {name} with arguments: {arguments}")

    if name == "polardb_smart_query":
        return polardb_smart_query(arguments)

    elif name == "polardb_describe_regions":
        result = polardb_describe_regions()
        
        # Add priority search guidance
        guidance_text = priority_guidance.generate_search_guidance()
        priority_guidance_content = TextContent(
            type="text", 
            text=f"\n\n{guidance_text}\n"
                 "⚠️ IMPORTANT: Search priority regions FIRST before checking others!\n"
                 "Count each cluster carefully - the API returns complete lists."
        )
        return result + [priority_guidance_content]
        
    elif name == "polardb_describe_db_clusters":
        region_id = arguments.get("region_id")
        
        # Use the updated polardb_describe_db_clusters function
        result = polardb_describe_db_clusters(arguments)
        
        # Track the result for guidance (updated to work with new response format)
        if result and len(result) > 0:
            response_text = result[0].text
            
            # Count clusters from the improved response format
            cluster_count = response_text.count("CLUSTER #")  # Updated to match new format
            priority_guidance.add_region_result(region_id, cluster_count)
            
            # Enhanced guidance based on priority regions
            priority_regions = ["cn-hangzhou", "cn-beijing", "cn-shanghai"]
            is_priority = region_id in priority_regions
            
            if is_priority:
                expected_count = priority_guidance.expected_counts.get(region_id, 0)
                if cluster_count != expected_count:
                    warning_guidance = TextContent(
                        type="text",
                        text=f"\n⚠️ PRIORITY REGION NOTICE: Expected {expected_count} clusters in {region_id}, "
                             f"but found {cluster_count}. This may indicate parsing issues or cluster changes."
                    )
                    result = result + [warning_guidance]
            
            # Add next-step guidance
            next_region = priority_guidance.get_next_priority_region()
            if next_region:
                next_step_guidance = TextContent(
                    type="text",
                    text=f"\n💡 NEXT PRIORITY REGION: Check '{next_region}' "
                         f"(expect {priority_guidance.expected_counts.get(next_region, '?')} clusters)"
                )
                return result + [next_step_guidance]
            else:
                # All priority regions checked
                total_found = sum(priority_guidance.clusters_found.values())
                summary_guidance = TextContent(
                    type="text",
                    text=f"\n🎉 ALL PRIORITY REGIONS COMPLETED!\n"
                         f"Total clusters found: {total_found}/6 expected\n"
                         f"Region breakdown: {dict(priority_guidance.clusters_found)}\n"
                         f"You can now search other regions if needed, or use the cluster IDs found for further operations."
                )
                return result + [summary_guidance]
        
        return result        

    elif name == "polardb_describe_db_cluster":
        return polardb_describe_db_cluster(arguments)

    elif name == "polardb_extract_node_ids":
        return polardb_extract_node_ids(arguments)  # New tool handler

    elif name == "polardb_describe_available_resources":
        return polardb_describe_available_resources(arguments)
        
    elif name == "polardb_create_cluster":
        return enhanced_polardb_create_cluster(arguments)
        
    elif name == "polardb_describe_db_node_parameters":
        return polardb_describe_db_node_parameters(arguments)

    elif name == "polardb_modify_db_cluster_parameters":
        return polardb_modify_db_cluster_parameters(arguments)

    elif name == "polardb_modify_db_node_parameters":
        return polardb_modify_db_node_parameters(arguments)
        
    elif name == "polardb_describe_slow_log_records":
        return polardb_describe_slow_log_records(arguments)
        
    elif name == "polardb_describe_db_node_performance":
        return enhanced_polardb_describe_db_node_performance(arguments)
        
    elif name == "polardb_describe_db_cluster_performance":
        return polardb_describe_db_cluster_performance(arguments)
        
    elif name == "polardb_get_guidance":
        return polardb_get_guidance(arguments)
    
    elif name == "polardb_tag_resources":
        return polardb_tag_resources(arguments)

    elif name == "polardb_create_db_endpoint_address":
        return polardb_create_db_endpoint_address(arguments)

    elif name == "polardb_create_account":
        return polardb_create_account(arguments)

    elif name == "polardb_describe_db_cluster_access_whitelist":
        return polardb_describe_db_cluster_access_whitelist(arguments)

    elif name == "polardb_describe_accounts":
        return polardb_describe_accounts(arguments)

    elif name == "polardb_describe_databases":
        return polardb_describe_databases(arguments)

    elif name == "polardb_describe_db_cluster_endpoints":
        return polardb_describe_db_cluster_endpoints(arguments)

    elif name == "polardb_describe_db_cluster_parameters":
        return polardb_describe_db_cluster_parameters(arguments)

    elif name == "polardb_describe_global_security_ipgroup_relation":
        return polardb_describe_global_security_ipgroup_relation(arguments)

    elif name == "vpc_describe_vswitches":
        return vpc_describe_vswitches(arguments)

    elif name == "vpc_describe_vpcs":
        return vpc_describe_vpcs(arguments)

    elif name == "polardb_modify_db_cluster_access_whitelist":
        return polardb_modify_db_cluster_access_whitelist_enhanced(arguments)

    elif name == "polardb_modify_db_cluster_description":
        return polardb_modify_db_cluster_description(arguments)

    elif name == "polardb_restart_db_node":
        return polardb_restart_db_node(arguments)

    elif name == "polardb_describe_db_cluster_connectivity":
        return polardb_describe_db_cluster_connectivity(arguments)

    elif name == "polardb_describe_db_proxy_performance":
        return polardb_describe_db_proxy_performance(arguments)

    elif name == "polardb_describe_error_log_records":
        return polardb_describe_error_log_records(arguments)

    else:
        raise ValueError(f"Unknown tool: {name}")

def create_starlette_app(app: Server, *, debug: bool = False) -> Starlette:
    """Create a Starlette application that can server the provied mcp server with SSE."""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


def sse_main(bind_host: str="127.0.0.1", bind_port: int = 8080):
    # Bind SSE request handling to MCP server
    starlette_app = create_starlette_app(app, debug=True)
    logger.info(f"Starting MCP SSE server on {bind_host}:{bind_port}/sse")
    uvicorn.run(starlette_app, host=bind_host, port=bind_port)

async def stdio_main():
    """Main entry point to run the MCP server."""
    from mcp.server.stdio import stdio_server

    logger.info("Starting PolarDB OpenAPI MCP server with stdio mode...") 
    async with stdio_server() as (read_stream, write_stream):
        try:
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
        except Exception as e:
            logger.error(f"Server error: {str(e)}", exc_info=True)
            raise

def main():
    load_dotenv()

    if os.getenv("RUN_MODE") == "stdio":
        asyncio.run(stdio_main())
    elif os.getenv("RUN_MODE") == "sse":
        bind_host = os.getenv("SSE_BIND_HOST", "127.0.0.1")
        bind_port = int(os.getenv("SSE_BIND_PORT", "8080"))
        sse_main(bind_host, bind_port)
    else:
        # Default to stdio mode if RUN_MODE is not set or invalid
        asyncio.run(stdio_main())

if __name__ == "__main__":
    main()
