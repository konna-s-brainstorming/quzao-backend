import base64
import json
import logging
import os
from typing import List

import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from asr_service import AsrClient
from llm_service import LLMClient
from tts_service import TTSClient

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger('asr_service').setLevel(logging.DEBUG)

app = FastAPI()
# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceInfo(BaseModel):
    voice_name: str
    voice_code: str
    choose: bool

class ToyConfigSave(BaseModel):
    toy_name: str
    voice_code: str
    toy_prompt: str

toy_name: str = ""
voice_id: str = config.TTS_VOICE_TYPE
voices: List[VoiceInfo] = []
toy_prompt: str = ""

# 按标点切割文本
# 核心作用：LLM 生成的文本过长时，按标点符号切割成短句，避免 TTS 合成超长音频（提升实时性）；
# 优先在目标长度（默认 50 字）附近找标点，保证句子完整性。
def find_nearest_punctuation(text: str, target_len: int = 50):
    """在目标长度附近查找标点符号位置"""
    punctuations = ['。', '！', '？', '；', '，', '.', '!', '?', ';', ',']
    
    if len(text) <= target_len:
        return len(text) - 1
    
    search_start = max(0, target_len - 20)
    search_end = min(len(text), target_len + 20)
    
    for i in range(target_len, search_end):
        if i < len(text) and text[i] in punctuations:
            return i
    
    for i in range(target_len, search_start - 1, -1):
        if i < len(text) and text[i] in punctuations:
            return i
    
    return min(target_len, len(text) - 1)

def get_project_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return current_dir


def load_prompt(file_name: str) -> str:
    """加载纯文本提示词，无变量"""
    project_root = get_project_root()
    file_path = os.path.join(project_root, "prompts", file_name)
    print(f"正在加载智能体提示词文件：{file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        error_msg = f"[智能体-提示词加载失败] 原因：{str(e)}"
        print(error_msg)
        return error_msg

def load_toy_config():
    """加载手办配置"""
    global toy_name, voice_id, voices, toy_prompt
    project_root = get_project_root()
    
    try:
        toy_name_path = os.path.join(project_root, "data", "toy_name.txt")
        with open(toy_name_path, 'r', encoding='utf-8') as f:
            toy_name = f.read().strip()
    except Exception as e:
        logger.error(f"加载toy_name.txt失败: {e}")
        toy_name = "未命名手办"
    
    try:
        voice_id_path = os.path.join(project_root, "data", "voice_id.txt")
        with open(voice_id_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            voices = []
            for idx, line in enumerate(lines):
                line = line.strip()
                if line:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        code = parts[0].strip()
                        name = parts[1].strip()
                        voices.append(VoiceInfo(
                            voice_name=name,
                            voice_code=code,
                            choose=(idx == 0)
                        ))
                        if idx == 0:
                            voice_id = code
    except Exception as e:
        logger.error(f"加载voice_id.txt失败: {e}")
        voices = []
    
    try:
        prompt_path = os.path.join(project_root, "prompts", "character_setting_prompt.txt")
        with open(prompt_path, 'r', encoding='utf-8') as f:
            toy_prompt = f.read().strip()
    except Exception as e:
        logger.error(f"加载character_setting_prompt.txt失败: {e}")
        toy_prompt = ""
    
    logger.info(f"配置加载完成: toy_name={toy_name}, voices={len(voices)}个, prompt长度={len(toy_prompt)}")

def save_toy_config(config: ToyConfigSave):
    """保存手办配置"""
    global toy_name, voice_id, toy_prompt
    project_root = get_project_root()
    
    try:
        toy_name_path = os.path.join(project_root, "data", "toy_name.txt")
        with open(toy_name_path, 'w', encoding='utf-8') as f:
            f.write(config.toy_name)
        toy_name = config.toy_name
    except Exception as e:
        logger.error(f"保存toy_name.txt失败: {e}")
        raise
    
    try:
        voice_id = config.voice_code
        for v in voices:
            v.choose = (v.voice_code == config.voice_code)
    except Exception as e:
        logger.error(f"更新voice_id失败: {e}")
        raise
    
    try:
        prompt_path = os.path.join(project_root, "prompts", "character_setting_prompt.txt")
        with open(prompt_path, 'w', encoding='utf-8') as f:
            f.write(config.toy_prompt)
        toy_prompt = config.toy_prompt
    except Exception as e:
        logger.error(f"保存character_setting_prompt.txt失败: {e}")
        raise
    
    logger.info(f"配置保存成功: toy_name={toy_name}, voice_code={voice_id}")

@app.on_event("startup")
async def startup_event():
    load_toy_config()

@app.get("/api/toy/info")
async def get_toy_info():
    return {
        "toy_name": toy_name,
        "voices": [v.model_dump() for v in voices],
        "toy_prompt": toy_prompt
    }

@app.post("/api/toy/save")
async def save_toy_info(config: ToyConfigSave):
    try:
        save_toy_config(config)
        return {"success": True, "message": "保存成功"}
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return {"success": False, "message": f"保存失败: {str(e)}"}


@app.websocket("/ws/voice_chat")
async def websocket_voice_chat(websocket: WebSocket):
    # 响应客户端的连接请求，建立WebSocket通道
    await websocket.accept()
    logger.info("WebSocket connected")

    # 初始化http-session会话、ASR/TTS/LLM客户端示例的初始化，以及ASR技术的结果缓存
    session = None
    asr_client = None
    tts_client = None
    llm_client = None
    asr_result = ""
    
    try:
        # 创建异步HTTP会话(复用连接，提升性能)
        session = aiohttp.ClientSession()
        # 初始化LLM客户端(配置API密钥、模型、会话)
        llm_client = LLMClient(config.DOUBAO_API_KEY, config.DOUBAO_MODEL, session)
        # 设置LLM系统提示：要求回答简洁(<=50字)
        character_setting_prompt = load_prompt("character_setting_prompt.txt")
        default_prompt = character_setting_prompt if character_setting_prompt else "你是豆包，是由字节跳动开发的AI助手，回答要简洁，不要超过50个字"
        llm_client.add_system_message(default_prompt)

        while True:
            try:
                # 接收客户端消息
                message = await websocket.receive()

                # 处理二进制音频数据输入
                if message["type"] == "websocket.receive":
                    if "bytes" in message:
                        audio_data = message["bytes"] # 获取PCM音频二进制数据

                        # 首次收到音频，初始化ASR和TTS客户端
                        if asr_client is None:
                            logger.info("初始化ASR和TTS连接")
                            # 建立ASR websocket连接
                            asr_client = await AsrClient(
                                config.ASR_APP_KEY,
                                config.ASR_ACCESS_KEY,
                                session
                            ).connect()
                            # 建立TTS webSocket连接
                            tts_client = await TTSClient(
                                config.TTS_APPID,
                                config.TTS_TOKEN,
                                config.TTS_CLUSTER,
                                voice_id,
                                session
                            ).connect()
                        
                        logger.debug(f"收到PCM音频: {len(audio_data)} bytes")
                        # 发送音频数据到ASR服务
                        await asr_client.send_audio(audio_data)

                    elif "text" in message:
                        data = message["text"]
                        try:
                            # # 解析前端发送过来的JSON指令（如"end"表示音频发送结束）
                            cmd = json.loads(data) if data.startswith('{') else {"type": "unknown"}
                        except:
                            cmd = {"type": "unknown"}
                        
                        if cmd.get("type") == "end":
                            logger.info("=== 收到结束信号 ===")

                            # 1. 通知ASR服务：音频发送结束，获取最终识别结果
                            await asr_client.send_end()
                            final_code = 0
                            async for text in asr_client.receive_results():
                                # 接收ASR最终识别文本
                                asr_result = text

                            # 向客户端返回ASR结果
                            await websocket.send_json({"type": "asr", "data": asr_result})
                            logger.info(f"ASR最终结果: '{asr_result}'")

                            # 处理空ASR结果（无有效语音）
                            if not asr_result:
                                await websocket.send_text("over") # 通知客户端结束
                                # 重置ASR客户端，准备下一次语音输入
                                asr_client = await AsrClient(
                                    config.ASR_APP_KEY,
                                    config.ASR_ACCESS_KEY,
                                    session
                                ).connect()
                                asr_result = ""
                                continue
                            
                            logger.info("=== LLM流式生成 ===")
                            # 缓存LLM生成的文本片段
                            llm_buffer = ""

                            # 如果TTS连接断开，重新建立
                            async def synthesize_and_send(text: str):
                                nonlocal tts_client
                                logger.info(f"TTS合成段落: '{text[:50]}...'")
                                
                                if tts_client.ws.closed:
                                    tts_client = await TTSClient(
                                        config.TTS_APPID,
                                        config.TTS_TOKEN,
                                        config.TTS_CLUSTER,
                                        voice_id,
                                        session
                                    ).connect()
                                
                                chunk_count = 0
                                # 流式合成语音(逐块获取音频数据)
                                async for audio_chunk in tts_client.synthesize(text):
                                    chunk_count += 1
                                    # 将音频二进制数据base64编码后发送给客户端
                                    await websocket.send_json({
                                        "type": "tts",
                                        "data": base64.b64encode(audio_chunk).decode()
                                    })
                                logger.info(f"TTS完成: {chunk_count}个音频块")

                            # 流式调用LLM生成回答
                            async for llm_chunk in llm_client.generate_stream(asr_result):
                                # 累加LLM生成的文本片段
                                llm_buffer += llm_chunk
                                logger.info(f"LLM块: '{llm_chunk}' (累计{len(llm_buffer)}字)")
                                # 向客户端返回累计的LLM文本(前端可实时展示)
                                await websocket.send_json({"type": "llm", "data": llm_buffer})

                                # 缓存文本超过100字时，切割短句进行TTS合成
                                if len(llm_buffer) > 100:
                                    cut_pos = find_nearest_punctuation(llm_buffer, 50)
                                    # 切割出完整句子
                                    sentence = llm_buffer[:cut_pos+1]
                                    # 剩余文本继续缓存
                                    llm_buffer = llm_buffer[cut_pos+1:]
                                    # 合成并发送语音
                                    await synthesize_and_send(sentence)

                            # LLM生成结束后，处理剩余的缓存文本
                            if llm_buffer:
                                await synthesize_and_send(llm_buffer)

                            # 通知客户端本轮对话结束
                            await websocket.send_text("over")
                            logger.info("=== 完成 ===")

                            # 重置ASR客户端，准备下一轮语音输入
                            asr_client = await AsrClient(
                                config.ASR_APP_KEY,
                                config.ASR_ACCESS_KEY,
                                session
                            ).connect()
                            asr_result = ""
                # 处理客户端断开连接
                elif message["type"] == "websocket.disconnect":
                    break
            # 异常处理
            except Exception as e:
                logger.error(f"处理错误: {e}", exc_info=True)
                await websocket.send_json({"type": "error", "data": str(e)})
                break
    # 全局异常捕获 & 资源释放
    except WebSocketDisconnect:
        logger.info("客户端断开")
    except Exception as e:
        logger.error(f"错误: {e}", exc_info=True)
    finally:
        # 都关闭 ASR/TTS 连接和 aiohttp 会话，避免资源泄漏。
        if asr_client:
            await asr_client.close()
        if tts_client:
            await tts_client.close()
        if session and not session.closed:
            await session.close()

# ASR + LLM + TTS服务使用8001端口
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
