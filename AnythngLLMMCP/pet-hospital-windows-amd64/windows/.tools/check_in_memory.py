import asyncio
import httpx
from mcp import Client
from pet_hospital_mcp.config import AppSettings
from pet_hospital_mcp.rest_client import PetHospitalRestClient
from pet_hospital_mcp.server import create_server

async def main():
    settings = AppSettings(base_url='http://backend.test')
    rest = PetHospitalRestClient(settings, transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    server = create_server(settings, rest_client=rest)
    async with Client(server) as client:
        result = await client.call_tool('list_pets', {'unknown': 'x'})
        print(result.is_error, result.structured_content)
    await rest.aclose()

asyncio.run(main())
