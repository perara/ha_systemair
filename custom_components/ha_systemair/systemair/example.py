import asyncio

from systemair.savecair.systemair import SystemAIR

if __name__ == "__main__":

    async def main():
        x = SystemAIR(iam_id="", password="")
        await x.connect()

    asyncio.get_event_loop().create_task(main())
    asyncio.get_event_loop().run_forever()
