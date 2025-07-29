# MCP Tools Test Suite

This directory contains comprehensive unit tests for the PolarDB OpenAPI MCP Server.

## Test Files

### `test_mcp_simple.py` (Complete Test Suite)
- **22 test cases** covering all MCP tool functionality
- Tests smart query dispatcher with Chinese/English patterns
- Validates parameter extraction and tool mapping
- Tests MCP integration and error handling
- **All tests passing ✅**

### Test Categories

#### 1. Smart Query Functionality (14 tests)
Tests the intelligent dispatcher that recognizes user intent:
- ✅ Node restart: `"重启节点 pi-xxx"` / `"restart node pi-xxx"`
- ✅ Cluster performance: `"获取集群 pc-xxx 的性能"` / `"get performance for cluster pc-xxx"`
- ✅ Node performance: `"获取节点 pi-xxx 的性能"` / `"get performance for node pi-xxx"`
- ✅ Cluster info: `"查看集群 pc-xxx 信息"` / `"describe cluster pc-xxx"`
- ✅ Whitelist: `"查看集群 pc-xxx 的白名单"` / `"show whitelist for cluster pc-xxx"`
- ✅ Node extraction: `"提取集群 pc-xxx 的节点"` / `"extract nodes from cluster pc-xxx"`
- ✅ Pattern validation and error cases

#### 2. MCP Tools Existence (4 tests)
Verifies all expected functions and classes exist:
- ✅ Core MCP infrastructure
- ✅ Smart query function
- ✅ Dispatcher class
- ✅ Client creation functions

#### 3. Parameter Extraction (2 tests)
Tests automatic parameter generation:
- ✅ Time range calculation (last hour default)
- ✅ Performance metrics keys
- ✅ Resource ID extraction

#### 4. Basic Integration (2 tests)
Tests actual MCP interface:
- ✅ Smart query through `enhanced_call_tool`
- ✅ Error handling for invalid tools

## Running Tests

### Quick Run
```bash
./run_tests.sh
```

### Manual Run
```bash
source .venv/bin/activate
python -m pytest test_mcp_simple.py -v
```

### Test Output
```
======================== 22 passed, 7 warnings in 2.01s ========================

=== Test Summary ===
✅ Smart Query Functionality: All pattern matching tests passed
✅ MCP Tools Existence: All expected functions and classes found  
✅ Parameter Extraction: Time ranges and IDs extracted correctly
✅ Basic Integration: Smart query works through MCP interface
✅ Error Handling: Invalid tool names handled properly

🎉 All 22 tests passed! MCP tools are working correctly.
```

## Test Dependencies

- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `pytest-mock` - Mocking utilities
- `unittest.mock` - Python built-in mocking

## Tool Coverage

The tests validate the core functionality of **31 MCP tools**:

### PolarDB Tools (28 tools)
- Cluster management (create, describe, modify)
- Performance monitoring (cluster & node level)
- Account & database management
- Parameter configuration
- Node operations (restart, extract)
- Slow log analysis
- Whitelist management
- Tagging and metadata

### VPC Tools (2 tools)
- VPC listing and configuration
- VSwitch management

### Smart Query (1 tool)
- Natural language processing
- Pattern matching (Chinese/English)
- Automatic parameter extraction

## Design Philosophy

The test suite focuses on:

1. **Core Functionality**: Smart query dispatcher is the most critical feature
2. **Real-world Usage**: Tests actual user commands in both languages
3. **Reliability**: No external API dependencies in tests
4. **Maintainability**: Simple, focused tests that are easy to understand
5. **Coverage**: All major user flows and error cases

## Future Enhancements

Potential test improvements:
- Mock-based API integration tests
- Performance benchmarking
- End-to-end workflow testing
- Load testing for concurrent requests