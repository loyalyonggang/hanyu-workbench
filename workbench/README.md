# 韩语视频工作台

双击上一级目录的 **打开韩语视频工作台.command**，浏览器会打开本机工作台。保留启动窗口即可让队列继续处理。下次启动依然可以查看历史成片和未完任务。

## 日常使用

1. 粘贴 HTTPS 分享链接，每行一条，或选择多份本地视频。两种来源可以放在同一批。
2. 选择字幕处理方式。黄色字幕可局部清理，其他颜色可以用底板遮盖。展开高级选项可调整字幕高度、右下角清理和翻译备注。
3. 只需要原片时，点击「只下载原片」。需要韩语成片时，点击「开始生成」，原片下载后也可以从任务行单独保存。队列支持勾选多条打包。

每批最多 30 条，单条最长 10 分钟。分享链接通过 KuKuTool 处理。同一视频号链接会复用工作台已保存的原片。遇到 429，工作台按对方给出的时间自动重试。解析或下载超时也会排队重试，等待时继续处理其他可运行的任务。若网站要求账号或验证，可从本地导入已有素材。使用本机音色时，识别、翻译、配音和画面处理都在本机运行。

## HeyGen

在右上角设置页填入自己的 API Key，验证成功后可选 HeyGen 配音和尝试口型同步。HeyGen 使用独立 API 额度，口型同步会将该视频和配音送到 HeyGen。动画或遮挡场景可能保留原口型，处理结果会在队列提示。可选的二虎示例来自此前独立完成的口型修订版。将原片和示例成片分别放在仓库根目录的「原片.mp4」和「二虎_韩语口型修订版.mp4」，即可启用相应按钮。

- [HeyGen API Key](https://developers.heygen.com/docs/api-key)
- [HeyGen 口型接口](https://developers.heygen.com/reference/create-lipsync)

## 本机环境

工作台以 127.0.0.1:8790 运行。需要 macOS、uv、FFmpeg、Whisper CLI 和 Ollama。本机准备的默认模型是 ggml-large-v3.bin 与 gemma4:e4b。设置界面显示连接状态。可通过 WORKBENCH_WHISPER_MODEL、WORKBENCH_TRANSLATION_MODEL 指定替代模型。KuKuTool 自动下载使用 ego-browser。

任务和输出在 workbench/data/jobs，可以用界面的「打开输出目录」进入。API 密钥通过设置保存时仅写入本机用户可读的文件。也可从启动环境提供 HEYGEN_API_KEY。

## 服务器部署

Linux 的 Python 依赖见 [部署依赖](deploy/requirements.txt)。香港部署使用 workbench/deploy 下的 systemd 和 Nginx 配置，通过 https://hanyu.xzggai.com 登录。Linux 端使用 Whisper、llama.cpp 和 HeyGen，在服务器上串行处理任务。部署目录是 /data/hanyu/app，任务和密钥在 /data/hanyu/runtime。

- 查看任务服务：systemctl status hanyu
- 查看翻译模型：systemctl status hanyu-translate
- 查看处理记录：journalctl -u hanyu

服务器可选 Piper 韩语试听音色。其训练数据的模型卡标注 CC BY-NC-SA 4.0，工作台将该音色用于非商用试听。HeyGen 额度不足时，可以在任务行选择「用离线配音重试」。

- [Piper KSS 韩语音色模型卡](https://huggingface.co/rhasspy/piper-voices/blob/main/ko/ko_KR/kss/medium/MODEL_CARD)
