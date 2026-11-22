# 韩语视频工作台使用说明

## macOS 首次安装

需要可访问本仓库的 GitHub 账号，以及一台能运行 Ollama 的 Mac。下面的命令从终端执行。已安装的工具和已下载的模型可以直接复用。

1. 克隆仓库并进入目录。使用 [Homebrew](https://brew.sh/) 安装必要工具。

   ```bash
   git clone https://github.com/loyalyonggang/hanyu-workbench.git
   cd hanyu-workbench
   brew install uv ffmpeg whisper.cpp ollama
   ```

   安装参考见 [FFmpeg](https://formulae.brew.sh/formula/ffmpeg)、[whisper.cpp](https://formulae.brew.sh/formula/whisper.cpp)、[Ollama](https://formulae.brew.sh/formula/ollama) 和 [uv](https://formulae.brew.sh/formula/uv)。

2. 下载普通话识别模型到工作台的默认目录。已有同名文件时跳过下载。

   ```bash
   model_dir="$HOME/.cache/hyperframes/whisper/models"
   mkdir -p "$model_dir"
   if [ ! -s "$model_dir/ggml-large-v3.bin" ]; then
     curl -fL --retry 2        https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin        -o "$model_dir/ggml-large-v3.bin.part" &&
       mv "$model_dir/ggml-large-v3.bin.part" "$model_dir/ggml-large-v3.bin"
   fi
   ```

   选择支持中文的多语种模型。模型清单见 [whisper.cpp 模型仓库](https://huggingface.co/ggerganov/whisper.cpp)。

3. 已用 Ollama 桌面应用启动服务时，直接执行 `ollama pull gemma4:e4b`。使用上面的 Homebrew 版本且尚未启动时，先执行以下命令。工作台默认走本机 Ollama。参见 [Gemma 4 模型页](https://ollama.com/library/gemma4)。

   ```bash
   brew services start ollama
   ollama pull gemma4:e4b
   ```

4. 双击仓库根目录的 **打开韩语视频工作台.command**，也可在仓库根目录运行 `./打开韩语视频工作台.command`。首次启动会由 uv 准备 Python 3.12 和应用依赖。在 [本机工作台](http://127.0.0.1:8790/) 打开「设置」，确认 Whisper 和 Ollama 就绪。处理期间保持启动窗口开启。

首次使用建议上传一条短的本地视频并选择「本机韩语音色」。使用本机音色需要安装至少一个韩国韩语系统语音，可用 `say -v '?' | grep ko_KR` 检查。列表为空时，在 macOS「系统设置 → 辅助功能」的朗读相关设置中下载韩语系统语音。

本机自动解析分享链接需要 `ego-browser`。缺少这个工具时，可到 [KuKuTool](https://dy.kukutool.com/) 手动解析和下载，再走「本地文件」入口。

## 生成成片

| 步骤 | 操作 |
| --- | --- |
| 导入 | 在「视频链接」按每行一条粘贴完整 HTTPS 分享链接，或在「本地文件」选择 MP4、MOV、MKV、WebM、M4V、AVI。两种来源可放在同一批，每批 1–30 条。用于生成的素材须有画面和音轨，时长 1 秒至 10 分钟。 |
| 下载 | 仅保存链接里的视频时，点击「只下载原片」。生成任务下载成功后，原片也能从任务行单独保存。 |
| 配音 | 选择「本机韩语音色」或「HeyGen 配音」。展开「翻译、字幕位置与口型」，可在翻译备注写明角色语气，例如「上司说半语，员工用敬语，保留职场笑点」。 |
| 原字幕 | 原片有黄色硬字幕时选「清理黄色字幕」，把字幕位置滑块对准原字幕高度。其他颜色或清理有残留时选「字幕底板遮盖」。原片没有硬字幕时可选「直接叠加韩文」。 |
| 右下角 | 仅在右下确有固定角标且区域内没有重要画面时，勾选「局部清理右下角」。预览检查边缘和角标残留。 |
| 生成 | 点击「开始生成」。工作台按普通话识别、韩语翻译、配音、字幕合成的顺序处理。 |
| 导出 | 在处理队列点击「预览」，确认韩语发音、字幕和画面动作。任务行可分别保存 MP4 和 SRT，勾选多条后可「批量下载」ZIP。 |

任务、SRT 和中间文件默认位于 `workbench/data/jobs/<任务 ID>/`。本机可以点击「打开输出目录」。重复提交同一条视频号链接时，工作台可以复用之前已保存的原片。遇到限流或超时，重试时间会保存在队列里，其他可运行的任务会继续处理。

## 配置 HeyGen

1. 在 HeyGen 获取自己的 API Key，打开工作台右上角「设置」，粘贴后点「验证并连接」。工作台也可从启动环境读取 `HEYGEN_API_KEY`。参见 [HeyGen API Key 文档](https://developers.heygen.com/docs/api-key)。
2. 仅用 HeyGen 配音时，选择「HeyGen 配音」。工作台将韩语文本发给 HeyGen 合成，并按原对白时间轴放回音频。只要填写密钥并勾选口型，也可以用本机音色作为口型参考。
3. 需要对口型时，在高级选项勾选「尝试 HeyGen 口型同步」。这一步把视频和韩语配音发给 HeyGen，并使用 HeyGen API 额度。口型上传单个素材上限为 50 MB，超限时可从原片裁成较短片段后再提交。参见 [HeyGen 口型接口](https://developers.heygen.com/reference/create-lipsync)。
4. 任务完成后先读队列提示，再看成片。工作台会检查返回画面有无可检测的变化。返回失败或未检测到可靠变化时，仍会导出韩语配音成片，并保留原口型。动画角色侧脸、遮挡和大幅转身时要逐段核对。

## 二虎案例的复核流程

1. 从 KuKuTool 下载原片。导入后先确认中文字幕位置和右下角有无角标，按实际画面选择清理方式。
2. 核对译文和两角音色。二虎案例用上司半语和员工敬语来区分角色，保留「桌面、文件夹、窗口、上传云端」被当成实物操作的笑点。
3. 逐句听韩语，对照 SRT 时间和动作。连续的极短字幕可以合并。动作包袱需要同步时，把对应一句配音和字幕一起移动，再导出核对。
4. 把已定稿的韩语音轨作为口型参考。二虎案例中，HeyGen 的全画幅和特写测试都保留了原嘴型。案例最后使用 HeyGen 语音的音节时间，在本地手动跟踪嘴部并做局部开合调整。只调整看得到嘴的对白，背对镜头保留原画面。
5. 如果在剪辑软件里额外做口型，只替换画面轨，封回定稿版的完整音轨。确认视频时长、字幕内容和时间轴一致，再逐段预览。工作台的口型选项负责调用 HeyGen，案例里的局部动画需要手工处理。

如果手头有案例素材，可把原片和口型修订版分别放到仓库根目录的 `原片.mp4` 和 `二虎_韩语口型修订版.mp4`，启用界面的添加原片和播放示例按钮。没有案例素材也能导入自己的视频。

## 排错与手动启动

| 遇到的情况 | 处理方法 |
| --- | --- |
| 分享链接解析失败、要求账号或验证码 | 在 KuKuTool 手动下载，再在工作台「本地文件」导入。 |
| 找不到 Whisper 模型 | 确认模型下载完成且文件名正确，或用 `WORKBENCH_WHISPER_MODEL` 指向实际文件。 |
| 翻译模型未就绪 | 运行 `ollama list`，确认服务在运行且已下载 `gemma4:e4b`。使用其他模型时设置 `WORKBENCH_TRANSLATION_MODEL`，值填写 Ollama 列表里的完整名称。 |
| 韩语音色不可用 | 用 `say -v '?' | grep ko_KR` 检查已安装的系统语音，或选择已连接的 HeyGen 配音。 |
| 个别字幕有残留或覆盖错位 | 调整字幕位置，或改用「字幕底板遮盖」新建任务。 |
| HeyGen 配音失败或额度不足 | 查看队列提示。界面提供「用离线配音重试」时，可改用离线音色并跳过口型。 |

从仓库根目录用终端自定义模型路径或端口的例子如下。使用默认值时只需执行最后一行。

```bash
export WORKBENCH_WHISPER_MODEL="$HOME/.cache/hyperframes/whisper/models/ggml-large-v3.bin"
export WORKBENCH_TRANSLATION_MODEL="gemma4:e4b"
export WORKBENCH_PORT=8790
./打开韩语视频工作台.command
```

开发环境可在仓库根目录运行：

```bash
cd workbench
uv run --python 3.12 --with-requirements requirements.txt python -m unittest -v
```

## Linux 服务器部署

[部署目录](deploy/) 中有当前线上环境的 systemd 和 Nginx 配置，路径、域名、证书和认证文件需按自己的服务器调整。线上工作台要求登录。当前配置的应用目录是 `/data/hanyu/app`，任务、连接配置和密钥目录是 `/data/hanyu/runtime`。

- [Python 依赖](deploy/requirements.txt) 中包含 Playwright、Waitress 和 Piper。服务器还需要 FFmpeg、`whisper-cli`、多语种 Whisper 模型及支持韩文的字幕字体。Playwright 下载需要安装 Chromium。
- [应用服务](deploy/hanyu.service) 以本机端口提供 Web 队列。[翻译服务](deploy/hanyu-translate.service) 单独运行 llama.cpp 与 GGUF 模型。[Nginx 配置](deploy/hanyu.xzggai.com) 用于 TLS 和登录保护。
- 用 `systemctl status hanyu hanyu-translate` 检查服务，用 `journalctl -u hanyu` 查看处理日志。
- 服务器可选 Piper 韩语试听音色。该音色的数据许可见 [Piper KSS 韩语音色模型卡](https://huggingface.co/rhasspy/piper-voices/blob/main/ko/ko_KR/kss/medium/MODEL_CARD)。
