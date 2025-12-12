import aiohttp
import json
import gzip
import uuid
import struct
import logging

logger = logging.getLogger(__name__)

class TTSClient:
    def __init__(self, appid: str, token: str, cluster: str, voice_type: str, session: aiohttp.ClientSession):
        self.appid = appid
        self.token = token
        self.cluster = cluster
        self.voice_type = voice_type
        self.session = session
        self.url = "wss://openspeech.bytedance.com/api/v1/tts/ws_binary"
        self.ws = None

    def _build_request(self, text: str) -> bytes:
        default_header = bytearray(b'\x11\x10\x11\x00')
        request_json = {
            "app": {
                "appid": self.appid,
                "token": "access_token",
                "cluster": self.cluster
            },
            "user": {"uid": str(uuid.uuid4())},
            "audio": {
                "voice_type": self.voice_type,
                "encoding": "pcm",
                "rate": 16000,
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "submit"
            }
        }
        logger.info(f"TTS参数: voice_type={self.voice_type}, cluster={self.cluster}")
        payload_bytes = json.dumps(request_json).encode('utf-8')
        payload_bytes = gzip.compress(payload_bytes)
        full_request = bytearray(default_header)
        full_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
        full_request.extend(payload_bytes)
        return bytes(full_request)

    def _parse_response(self, res: bytes):
        header_size = res[0] & 0x0f
        message_type = res[1] >> 4
        message_type_specific_flags = res[1] & 0x0f
        message_compression = res[2] & 0x0f
        payload = res[header_size*4:]
        
        if message_type == 0xb:
            if message_type_specific_flags == 0:
                return None, False
            sequence_number = int.from_bytes(payload[:4], "big", signed=True)
            payload_size = int.from_bytes(payload[4:8], "big", signed=False)
            audio_data = payload[8:]
            
            if len(audio_data) != payload_size:
                logger.warning(f"TTS音频大小不匹配: 声明{payload_size}, 实际{len(audio_data)}")
            
            return audio_data, sequence_number < 0
        elif message_type == 0xf:
            error_msg = payload[8:]
            if message_compression == 1:
                error_msg = gzip.decompress(error_msg)
            logger.error(f"TTS error: {error_msg.decode('utf-8')}")
            return None, True
        elif message_type == 0xc:
            logger.info(f"TTS frontend message: {payload}")
            return None, False
        return None, False

    async def connect(self):
        header = {"Authorization": f"Bearer; {self.token}"}
        self.ws = await self.session.ws_connect(self.url, headers=header)
        logger.info("TTS connected")
        return self

    async def synthesize(self, text: str):
        request = self._build_request(text)
        await self.ws.send_bytes(request)
        logger.info(f"TTS request sent for text: {text[:50]}...")
        
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.BINARY:
                audio_data, is_done = self._parse_response(msg.data)
                if audio_data:
                    yield audio_data
                if is_done:
                    break
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                break

    async def close(self):
        if self.ws and not self.ws.closed:
            await self.ws.close()

