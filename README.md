# AI趣造后端
一个基于python + fastapi + 字节跳动语音识别技术、语音合成技术 + 大模型的后端服务，可以在web场景下提供实时语音服务
> 项目利用 AI Vibe Coding进行实现
![test_easy_ui.png](picture%2Ftest_easy_ui.png)
## 功能特性
- 语音识别服务：支持通过上传音频文件(mps/wav)或者以websocket协议发送音频帧的方式，来获取语音转文字服务
- 实时生成并合成服务：基于LLM流式输出和tts的实时合成功能，便于用户得到实时音频数据

## 环境准备
在启动项目前，请确保您的开发环境已经安装并正确配置了以下依赖。
- python: 3.12+

### 验证安装
打开终端命令行，输入以下命令。如果能正确显示版本号（3.12 或更高版本），则说明 python 环境已配置成功。
```shell
 python --version
```

## 快速开始
### 依赖安装
使用pycharm 打开终端控制台，使用以下命令进行安装项目需要使用到的库
```shell
pip install -r requirements.txt
```
### 服务申请
1.通过[ASR语音识别服务+TTS语音合成服务申请链接](https://console.volcengine.com/speech/app)
![service-open.jpg](picture%2Fservice-open.jpg)

2.前往火山方舟/阿里云百炼/deepseek等api平台选取自己模型服务，特别说明，由于本服务没有做特意的模型抽象，所以选择了其他服务的，需要改一下`llm_service.py`中的api_url地址即可

3.拿到两个服务api + 大模型api之后，改config-demo.py为config.py，进行参数填入

### 音色选择
1.自定义音色，免费赠送的有10个左右，一般平台帮你存储半年，可以通过api接口上传音频文件进行训练/平台上传

2.从音色列表中选择

最终都会得到一个重要的voice_type，就是音色id，不管是用于语音合成还是音色复刻都可以使用，可以填入voice_id.txt(voice_id_demo.txt改)中

### 运行服务
建议大家运行之前，可以先尝试`sauc_websocket_demo.py`和`tts_websocket_demo.py`的运行，
最后运行`main.py`文件，为前端提供服务
