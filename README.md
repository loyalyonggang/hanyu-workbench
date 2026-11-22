# 韩语视频工作台

将中文视频转成带韩语配音和韩文字幕的 MP4。支持上传本地视频、通过分享链接下载原片、批量处理和打包下载。

## 启动

在 macOS 上双击 **打开韩语视频工作台.command**，然后在浏览器打开 [本机工作台](http://127.0.0.1:8790/)。本机识别和翻译需要预先安装 FFmpeg、Whisper CLI、Ollama 和相应的模型。

- [使用说明、模型配置和服务器部署](workbench/README.md)
- [Linux 部署依赖](workbench/deploy/requirements.txt)
- [现有线上工作台](https://hanyu.xzggai.com/)

样片视频为可选素材。克隆仓库后可以直接导入自己的视频。任务文件、API 密钥和登录信息存放在部署环境中。
