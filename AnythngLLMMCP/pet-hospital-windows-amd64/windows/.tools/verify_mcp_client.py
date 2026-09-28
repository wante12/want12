import asyncio
import json
from mcp import Client

async def main():
    async with Client("http://127.0.0.1:8000/mcp") as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "list_pets",
            {
                "species": "犬",
                "min": 1000,
                "sortBy": "totalCost",
                "order": "desc",
                "page": 1,
                "pageSize": 2,
            },
        )
        print(json.dumps({
            "protocol_version": client.protocol_version,
            "tool_names": [tool.name for tool in tools.tools],
            "is_error": result.is_error,
            "total": result.structured_content["total"],
            "item_count": len(result.structured_content["items"]),
            "page": result.structured_content["page"],
            "page_size": result.structured_content["pageSize"],
        }, ensure_ascii=False))

asyncio.run(main())
