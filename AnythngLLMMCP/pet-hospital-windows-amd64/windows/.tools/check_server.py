import asyncio
import httpx
from pet_hospital_mcp.config import AppSettings
from pet_hospital_mcp.rest_client import PetHospitalRestClient
from pet_hospital_mcp.server import create_server

async def main():
    settings = AppSettings(base_url='http://127.0.0.1:8080', max_attempts=1, retry_backoff_seconds=0)
    rest = PetHospitalRestClient(settings, transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    server = create_server(settings, rest_client=rest)
    tools = await server.list_tools()
    tool = tools[0]
    print('name', tool.name)
    print('input', tool.input_schema)
    print('output', tool.output_schema)
    await rest.aclose()
    print('closed')

asyncio.run(main())
