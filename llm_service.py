import aiohttp
import json
import logging

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self, api_key: str, model: str, session: aiohttp.ClientSession):
        self.api_key = api_key
        self.model = model
        self.session = session
        self.url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        self.messages = []

    def add_system_message(self, content: str):
        if not self.messages or self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": content})

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    async def generate_stream(self, user_text: str = None):
        if user_text:
            self.add_user_message(user_text)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": self.model,
            "messages": self.messages,
            "stream": True
        }
        
        logger.info(f"Calling LLM, history length: {len(self.messages)}")
        
        full_response = ""
        async with self.session.post(self.url, headers=headers, json=data) as resp:
            async for line in resp.content:
                line_str = line.decode('utf-8').strip()
                if line_str.startswith('data: '):
                    line_str = line_str[6:]
                    if line_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(line_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            full_response += delta
                            yield delta
                    except:
                        pass
        
        if full_response:
            self.add_assistant_message(full_response)

