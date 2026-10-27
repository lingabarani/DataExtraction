"""
OneExtraction US B2B MCP Server - Stdio Mode
Implements the Model Context Protocol (MCP) for stdio communication.
Allows AI agents (Claude Desktop, Antigravity, ChatGPT) to query the B2B database.
"""

import sys
import json
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

# Setup logging to stderr (stdout reserved for MCP protocol)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

try:
    from .mcp_server import (
        search_companies_tool,
        get_company_details_tool,
        get_csuite_executives_tool,
        enrich_domain_rdap_tool,
        enrich_wikipedia_summary_tool,
    )
except ImportError as e:
    logger.error(f"Failed to import MCP tools: {e}")
    sys.exit(1)


class MCPStdioServer:
    """Implements MCP protocol over stdio."""
    
    def __init__(self):
        self.tools = {
            "search_companies": {
                "description": "Search canonical US companies by name, industry, or state",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Company name search (partial match)"},
                        "industry": {"type": "string", "description": "Industry filter (e.g., 'software', 'healthcare')"},
                        "state": {"type": "string", "description": "US state code (e.g., 'CA', 'NY')"},
                        "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10}
                    },
                    "required": []
                },
                "handler": search_companies_tool
            },
            "get_company_details": {
                "description": "Get full company profile by company_id, EIN, or CIK with executives",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "company_id": {"type": "string", "description": "Company ID, EIN, or CIK number"}
                    },
                    "required": ["company_id"]
                },
                "handler": get_company_details_tool
            },
            "get_csuite_executives": {
                "description": "Get C-suite executives for a company (CEO, CFO, COO, CTO, etc.)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "company_id": {"type": "string", "description": "Company ID"}
                    },
                    "required": ["company_id"]
                },
                "handler": get_csuite_executives_tool
            },
            "enrich_domain_rdap": {
                "description": "Live ICANN RDAP WHOIS lookup for domain registrant ownership",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Domain name (e.g., 'nvidia.com')"}
                    },
                    "required": ["domain"]
                },
                "handler": enrich_domain_rdap_tool
            },
            "enrich_wikipedia_summary": {
                "description": "Fetch corporate history and summary from Wikipedia",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "company_name": {"type": "string", "description": "Company name (e.g., 'NVIDIA')"}
                    },
                    "required": ["company_name"]
                },
                "handler": enrich_wikipedia_summary_tool
            }
        }
    
    def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialization request."""
        logger.debug("Received initialize request")
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {
                "name": "OneExtraction B2B MCP Server",
                "version": "1.0.0"
            }
        }
    
    def handle_list_tools(self) -> Dict[str, Any]:
        """List available tools."""
        logger.debug(f"Listing {len(self.tools)} tools")
        tools_list = []
        for name, config in self.tools.items():
            tools_list.append({
                "name": name,
                "description": config["description"],
                "inputSchema": config["inputSchema"]
            })
        return {
            "tools": tools_list
        }
    
    def handle_call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool."""
        logger.debug(f"Calling tool: {name} with args: {arguments}")
        
        if name not in self.tools:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Tool '{name}' not found"
                }],
                "isError": True
            }
        
        try:
            handler = self.tools[name]["handler"]
            
            # Call the appropriate handler based on tool name
            if name == "search_companies":
                result = handler(
                    query=arguments.get("query", ""),
                    industry=arguments.get("industry", ""),
                    state=arguments.get("state", ""),
                    limit=arguments.get("limit", 10)
                )
            elif name == "get_company_details":
                result = handler(company_id=arguments.get("company_id"))
            elif name == "get_csuite_executives":
                result = handler(company_id=arguments.get("company_id"))
            elif name == "enrich_domain_rdap":
                result = handler(domain=arguments.get("domain"))
            elif name == "enrich_wikipedia_summary":
                result = handler(company_name=arguments.get("company_name"))
            else:
                result = None
            
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(result, indent=2, default=str)
                }]
            }
        
        except Exception as e:
            logger.exception(f"Error calling tool {name}")
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: {str(e)}"
                }],
                "isError": True
            }
    
    def process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process incoming MCP request."""
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id", None)
        
        logger.debug(f"Processing request: method={method}, id={request_id}")
        
        try:
            if method == "initialize":
                result = self.handle_initialize(params)
            elif method == "tools/list":
                result = self.handle_list_tools()
            elif method == "tools/call":
                tool_name = params.get("name", "")
                tool_args = params.get("arguments", {})
                result = self.handle_call_tool(tool_name, tool_args)
            else:
                result = {"error": f"Unknown method: {method}"}
            
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            return response
        
        except Exception as e:
            logger.exception(f"Error processing request")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e)
                }
            }
    
    def run(self):
        """Main server loop - read requests from stdin, write responses to stdout."""
        logger.info("OneExtraction MCP Server started (stdio mode)")
        
        try:
            while True:
                try:
                    # Read one line from stdin
                    line = sys.stdin.readline()
                    if not line:
                        logger.info("EOF received, shutting down")
                        break
                    
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Parse JSON request
                    request = json.loads(line)
                    logger.debug(f"Received: {request}")
                    
                    # Process request
                    response = self.process_request(request)
                    
                    # Send response to stdout
                    print(json.dumps(response))
                    sys.stdout.flush()
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": "Parse error"
                        }
                    }
                    print(json.dumps(error_response))
                    sys.stdout.flush()
                
                except Exception as e:
                    logger.exception(f"Error in main loop")
        
        except KeyboardInterrupt:
            logger.info("Server interrupted by user")
        except Exception as e:
            logger.exception(f"Fatal error in server loop")
            sys.exit(1)


def main():
    """Entry point for MCP stdio server."""
    server = MCPStdioServer()
    server.run()


if __name__ == "__main__":
    main()
