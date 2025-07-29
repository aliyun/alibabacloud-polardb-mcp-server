import pytest
import asyncio
from unittest.mock import Mock, patch
from mcp.types import TextContent

# Import the server module
import server

class TestSmartQueryFunctionality:
    """Test the smart query dispatcher which is the core functionality"""
    
    def test_smart_query_restart_node_chinese(self):
        """Test smart query for node restart in Chinese"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("重启节点 pi-test123")
        
        assert result is not None
        assert result["intent"] == "restart_node"
        assert result["tool_name"] == "polardb_restart_db_node"
        assert result["arguments"]["dbnode_id"] == "pi-test123"
        assert result["confidence"] == "high"
    
    def test_smart_query_restart_node_english(self):
        """Test smart query for node restart in English"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("restart node pi-test456")
        
        assert result is not None
        assert result["intent"] == "restart_node"
        assert result["tool_name"] == "polardb_restart_db_node"
        assert result["arguments"]["dbnode_id"] == "pi-test456"
        assert result["confidence"] == "high"
    
    def test_smart_query_cluster_performance_chinese(self):
        """Test smart query for cluster performance in Chinese"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("获取集群 pc-test789 的性能")
        
        assert result is not None
        assert result["intent"] == "cluster_performance"
        assert result["tool_name"] == "polardb_describe_db_cluster_performance"
        assert result["arguments"]["db_cluster_id"] == "pc-test789"
        assert "start_time" in result["arguments"]
        assert "end_time" in result["arguments"]
        assert "key" in result["arguments"]
    
    def test_smart_query_cluster_performance_english(self):
        """Test smart query for cluster performance in English"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("get performance for cluster pc-test456")
        
        assert result is not None
        assert result["intent"] == "cluster_performance"
        assert result["tool_name"] == "polardb_describe_db_cluster_performance"
        assert result["arguments"]["db_cluster_id"] == "pc-test456"
    
    def test_smart_query_node_performance_chinese(self):
        """Test smart query for node performance in Chinese"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("获取节点 pi-test999 的性能")
        
        assert result is not None
        assert result["intent"] == "node_performance"
        assert result["tool_name"] == "polardb_describe_db_node_performance"
        assert result["arguments"]["dbnode_id"] == "pi-test999"
    
    def test_smart_query_node_performance_english(self):
        """Test smart query for node performance in English"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("get performance for node pi-test888")
        
        assert result is not None
        assert result["intent"] == "node_performance"
        assert result["tool_name"] == "polardb_describe_db_node_performance"
        assert result["arguments"]["dbnode_id"] == "pi-test888"
    
    def test_smart_query_cluster_info_chinese(self):
        """Test smart query for cluster information in Chinese"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("查看集群 pc-test111 信息")
        
        assert result is not None
        assert result["intent"] == "cluster_info"
        assert result["tool_name"] == "polardb_describe_db_cluster"
        assert result["arguments"]["db_cluster_id"] == "pc-test111"
    
    def test_smart_query_cluster_info_english(self):
        """Test smart query for cluster information in English"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("describe cluster pc-test222")
        
        assert result is not None
        assert result["intent"] == "cluster_info"
        assert result["tool_name"] == "polardb_describe_db_cluster"
        assert result["arguments"]["db_cluster_id"] == "pc-test222"
    
    def test_smart_query_whitelist_chinese(self):
        """Test smart query for whitelist viewing in Chinese"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("查看集群 pc-test333 的白名单")
        
        assert result is not None
        assert result["intent"] == "view_whitelist"
        assert result["tool_name"] == "polardb_describe_db_cluster_access_whitelist"
        assert result["arguments"]["dbcluster_id"] == "pc-test333"
    
    def test_smart_query_whitelist_english(self):
        """Test smart query for whitelist viewing in English"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("show whitelist for cluster pc-test444")
        
        assert result is not None
        assert result["intent"] == "view_whitelist"
        assert result["tool_name"] == "polardb_describe_db_cluster_access_whitelist"
        assert result["arguments"]["dbcluster_id"] == "pc-test444"
    
    def test_smart_query_extract_nodes_chinese(self):
        """Test smart query for node extraction in Chinese"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("提取集群 pc-test555 的节点")
        
        assert result is not None
        assert result["intent"] == "extract_nodes"
        assert result["tool_name"] == "polardb_extract_node_ids"
        assert result["arguments"]["db_cluster_id"] == "pc-test555"
    
    def test_smart_query_extract_nodes_english(self):
        """Test smart query for node extraction in English"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("extract nodes from cluster pc-test666")
        
        assert result is not None
        assert result["intent"] == "extract_nodes"
        assert result["tool_name"] == "polardb_extract_node_ids"
        assert result["arguments"]["db_cluster_id"] == "pc-test666"
    
    def test_smart_query_no_match(self):
        """Test smart query with no pattern match"""
        dispatcher = server.SmartMCPDispatcher()
        
        result = dispatcher.parse_user_intent("random query with no patterns")
        
        assert result is None
    
    def test_smart_query_partial_match(self):
        """Test smart query with partial/invalid cluster IDs"""
        dispatcher = server.SmartMCPDispatcher()
        
        # Should not match - invalid cluster ID format
        result = dispatcher.parse_user_intent("重启节点 invalid-id")
        assert result is None
        
        # Should not match - missing cluster ID
        result = dispatcher.parse_user_intent("获取集群的性能")
        assert result is None

class TestMCPToolsExistence:
    """Test that all expected MCP tools are properly defined"""
    
    def test_list_tools_function_exists(self):
        """Test that list_tools function exists"""
        # The server should have a way to list tools
        assert hasattr(server, 'app') or hasattr(server, 'list_tools')
    
    def test_smart_query_function_exists(self):
        """Test that smart query function exists"""
        assert hasattr(server, 'polardb_smart_query')
        assert callable(server.polardb_smart_query)
    
    def test_dispatcher_exists(self):
        """Test that SmartMCPDispatcher class exists"""
        assert hasattr(server, 'SmartMCPDispatcher')
        assert callable(server.SmartMCPDispatcher)
    
    def test_client_creation_functions_exist(self):
        """Test that client creation functions exist"""
        assert hasattr(server, 'create_client')
        assert callable(server.create_client)
        
        assert hasattr(server, 'create_vpc_client')
        assert callable(server.create_vpc_client)

class TestParameterExtraction:
    """Test parameter extraction methods in the dispatcher"""
    
    def test_cluster_performance_params_with_time_range(self):
        """Test cluster performance parameter extraction includes time ranges"""
        dispatcher = server.SmartMCPDispatcher()
        
        import re
        match = re.search(r"获取集群\s*(pc-[a-zA-Z0-9]+)\s*的?性能", "获取集群 pc-test123 的性能")
        result = dispatcher._extract_cluster_performance_params(match, "获取集群 pc-test123 的性能")
        
        assert result["db_cluster_id"] == "pc-test123"
        assert "start_time" in result
        assert "end_time" in result
        assert "key" in result
        assert "PolarDBCPU" in result["key"]
    
    def test_node_performance_params_with_time_range(self):
        """Test node performance parameter extraction includes time ranges"""
        dispatcher = server.SmartMCPDispatcher()
        
        import re
        match = re.search(r"获取节点\s*(pi-[a-zA-Z0-9]+)\s*的?性能", "获取节点 pi-test123 的性能")
        result = dispatcher._extract_node_performance_params(match, "获取节点 pi-test123 的性能")
        
        assert result["dbnode_id"] == "pi-test123"
        assert "start_time" in result
        assert "end_time" in result
        assert "key" in result
        assert "PolarDBCPU" in result["key"]

class TestMCPIntegrationBasic:
    """Basic integration tests that don't require complex mocking"""
    
    @pytest.mark.asyncio
    async def test_smart_query_integration(self):
        """Test smart query through the MCP interface"""
        with patch.dict('os.environ', {
            'ALIBABA_CLOUD_ACCESS_KEY_ID': 'test_key',
            'ALIBABA_CLOUD_ACCESS_KEY_SECRET': 'test_secret'
        }):
            arguments = {"query": "restart node pi-test123"}
            
            result = await server.enhanced_call_tool("polardb_smart_query", arguments)
            
            assert result is not None
            assert len(result) > 0
            assert isinstance(result[0], TextContent)
            # Should mention the restart operation or tool call
            text_content = result[0].text.lower()
            assert "restart" in text_content or "重启" in text_content or "polardb_restart_db_node" in text_content
    
    @pytest.mark.asyncio
    async def test_enhanced_call_tool_error_handling(self):
        """Test error handling in enhanced_call_tool"""
        with patch.dict('os.environ', {
            'ALIBABA_CLOUD_ACCESS_KEY_ID': 'test_key',
            'ALIBABA_CLOUD_ACCESS_KEY_SECRET': 'test_secret'
        }):
            # Test with an unsupported tool name
            try:
                result = await server.enhanced_call_tool("nonexistent_tool", {})
                # If it doesn't raise an exception, it should return an error message
                assert result is not None
                assert isinstance(result[0], TextContent)
                assert "error" in result[0].text.lower() or "unknown" in result[0].text.lower()
            except ValueError as e:
                # This is also acceptable - the function raises an exception for unknown tools
                assert "unknown tool" in str(e).lower()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])