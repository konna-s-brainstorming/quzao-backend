import asyncio
import aiohttp
import json
import struct
import gzip
import uuid
import logging

logger = logging.getLogger(__name__)

class ProtocolVersion:
    V1 = 0b0001

class MessageType:
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ERROR_RESPONSE = 0b1111

class MessageTypeSpecificFlags:
    NO_SEQUENCE = 0b0000
    POS_SEQUENCE = 0b0001
    NEG_SEQUENCE = 0b0010
    NEG_WITH_SEQUENCE = 0b0011

class SerializationType:
    JSON = 0b0001

class CompressionType:
    GZIP = 0b0001

class AsrRequestHeader:
    def __init__(self):
        self.message_type = MessageType.CLIENT_FULL_REQUEST
        self.message_type_specific_flags = MessageTypeSpecificFlags.POS_SEQUENCE
        self.serialization_type = SerializationType.JSON
        self.compression_type = CompressionType.GZIP
        self.reserved_data = bytes([0x00])

    def with_message_type(self, message_type: int):
        self.message_type = message_type
        return self

    def with_message_type_specific_flags(self, flags: int):
        self.message_type_specific_flags = flags
        return self

    def to_bytes(self) -> bytes:
        header = bytearray()
        header.append((ProtocolVersion.V1 << 4) | 1)
        header.append((self.message_type << 4) | self.message_type_specific_flags)
        header.append((self.serialization_type << 4) | self.compression_type)
        header.extend(self.reserved_data)
        return bytes(header)

class AsrClient:
    def __init__(self, app_key: str, access_key: str, session: aiohttp.ClientSession):
        self.app_key = app_key
        self.access_key = access_key
        self.session = session
        self.url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
        self.ws = None
        self.seq = 1

    def _build_auth_headers(self):
        reqid = str(uuid.uuid4())
        return {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Request-Id": reqid,
            "X-Api-Access-Key": self.access_key,
            "X-Api-App-Key": self.app_key
        }

    def _build_full_request(self, uid: str) -> bytes:
        header = AsrRequestHeader()
        payload = {
            "user": {"uid": uid},
            "audio": {
                "format": "pcm",
                "rate": 16000,
                "bits": 16,
                "channel": 1
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True
            }
        }
        payload_bytes = json.dumps(payload).encode('utf-8')
        compressed_payload = gzip.compress(payload_bytes)
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', self.seq))
        request.extend(struct.pack('>I', len(compressed_payload)))
        request.extend(compressed_payload)
        return bytes(request)

    def _build_audio_request(self, audio_data: bytes, is_last: bool = False) -> bytes:
        header = AsrRequestHeader()
        seq = self.seq
        if is_last:
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.NEG_WITH_SEQUENCE)
            seq = -seq
        else:
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
        header.with_message_type(MessageType.CLIENT_AUDIO_ONLY_REQUEST)
        
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', seq))
        compressed_audio = gzip.compress(audio_data)
        request.extend(struct.pack('>I', len(compressed_audio)))
        request.extend(compressed_audio)
        return bytes(request)

    def _parse_response(self, msg: bytes) -> dict:
        header_size = msg[0] & 0x0f
        message_type = msg[1] >> 4
        message_type_specific_flags = msg[1] & 0x0f
        serialization_method = msg[2] >> 4
        message_compression = msg[2] & 0x0f
        payload = msg[header_size*4:]
        
        result = {
            "code": 0,
            "is_last": False,
            "text": ""
        }
        
        if message_type_specific_flags & 0x01:
            payload = payload[4:]
        if message_type_specific_flags & 0x02:
            result["is_last"] = True
        if message_type_specific_flags & 0x04:
            payload = payload[4:]
            
        if message_type == MessageType.SERVER_FULL_RESPONSE:
            payload = payload[4:]
        elif message_type == MessageType.SERVER_ERROR_RESPONSE:
            result["code"] = struct.unpack('>i', payload[:4])[0]
            payload = payload[8:]
            
        if payload:
            try:
                if message_compression == CompressionType.GZIP:
                    payload = gzip.decompress(payload)
                
                if serialization_method == SerializationType.JSON:
                    data = json.loads(payload.decode('utf-8'))
                    result["code"] = data.get("code", 20000000)
                    if "result" in data:
                        result["text"] = data["result"].get("text", "")
                    logger.debug(f"ASR JSON: code={result['code']}, text='{result['text']}'")
            except Exception as e:
                logger.error(f"解析响应错误: {e}", exc_info=True)
        
        return result

    async def connect(self, uid: str = "user_001"):
        headers = self._build_auth_headers()
        self.ws = await self.session.ws_connect(self.url, headers=headers)
        
        full_request = self._build_full_request(uid)
        await self.ws.send_bytes(full_request)
        self.seq += 1
        
        msg = await self.ws.receive()
        if msg.type == aiohttp.WSMsgType.BINARY:
            response = self._parse_response(msg.data)
            logger.info(f"ASR initialized: {response}")
        
        return self

    async def send_audio(self, audio_data: bytes):
        if len(audio_data) == 0:
            logger.warning("音频数据为空，跳过发送")
            return
        
        request = self._build_audio_request(audio_data, is_last=False)
        await self.ws.send_bytes(request)
        logger.debug(f"ASR发送seq={self.seq}, size={len(audio_data)}")
        self.seq += 1

    async def send_end(self):
        request = self._build_audio_request(b'', is_last=True)
        await self.ws.send_bytes(request)
        logger.info("ASR end signal sent")

    async def receive_results(self):
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.BINARY:
                result = self._parse_response(msg.data)
                logger.info(f"ASR响应包: code={result['code']}, text='{result['text']}', is_last={result['is_last']}")
                
                if result["code"] != 20000000 and result["code"] != 0:
                    logger.error(f"ASR错误码: {result['code']}")
                
                if result["text"]:
                    yield result["text"]
                    
                if result["is_last"]:
                    logger.info("ASR流结束")
                    break
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                logger.warning(f"ASR连接异常: {msg.type}")
                break

    async def close(self):
        if self.ws and not self.ws.closed:
            await self.ws.close()

