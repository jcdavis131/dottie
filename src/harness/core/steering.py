"""Async steering channel live injection between turns."""
import asyncio
class SteeringChannel:
    def __init__(self): self.q=asyncio.Queue()
    async def send(self,msg:str): await self.q.put(msg)
    async def drain(self):
        out=[]
        while not self.q.empty(): out.append(self.q.get_nowait())
        return out
