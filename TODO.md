# TODO

## 眼镜

- [ ] 前滑/后滑安排用途（例如切换字幕显示 / 摄像头预览）
- [ ] 功耗：加电量日志，跑一次完整通话看续航
- [ ] 曝光（可选）：白砖在半米外过曝，颗粒看不清。HAL 支持 AE 补偿 ±2 EV；做法是加
      `livekit-android-camerax` 模块，`capturer.getCameraX()` → `cameraControl.setExposureCompensationIndex`。
      先看中性色砖 / 拿近点是否已经够用
- [ ] 实验结束后 `glasses.ps1 -RestoreSleep`（启动时会把眼镜的摘下休眠关掉，不然摘下一分钟就断 Wi-Fi）
- [ ] 屏幕现在有状态、步骤列表、双方字幕。实验测的是网络质量对语音交互的影响，屏幕信息越多用户越不依赖语音，正式实验前再定去掉哪些

## 参考模型（眼镜端下行视觉）

搭建者要能看到成品长什么样，只看成品、不给分步图（分步图就是说明书，语音交互没了）。按阶段做：

- [ ] 任务打包格式：`guides/<task>/task.toml`（标题、零件清单、步骤：part / place / check）+ 成品模型 `model.glb`。
      所有任务共用一套零件，每块砖一步；模型里每块砖一个节点，节点名带步骤号，之后高亮要用
- [ ] 建模导出：Stud.io 画 → .ldr/.io → Blender（ImportLDraw）→ GLB。格式待验证，看节点是否保得住
- [ ] 后端实时渲染成视频轨下发（云渲染 / split rendering 路线，眼镜端只显示远端视频轨）。PoC 已通：
      moderngl 渲染 3 ms/帧，`rtc.VideoSource` 发 VP8 15 fps，接收端无丢帧；眼镜端显示框约 269×202 px，默认流 320×240（`MODEL_STREAM_SIZE`）。容器里要换 EGL + Mesa
      llvmpipe（软渲染够用，不动宿主机）；GPU 路线要 nvidia-container-toolkit（sudo）
- [ ] 编码怎么选：现在是 libwebrtc 软编 VP8。VP8 / H.264 / AV1、码率、关键帧间隔、丢包下的表现，
      以及要不要 NVENC——请教同事后定。眼镜端解码能力也要查
- [ ] 显示现在是"做到当前步的样子"、正交投影（Gemini 路仍有 `show_view` / `highlight_part` 工具，GPT 路没有）
- [ ] 下行视频是否算被测通道由实验设计定；不想混时只在语音流上注入丢包（tc 按端口/流）
- [ ] 正式图形几个、几块砖、什么形状先不定，系统跑通后再画

## GPT 路（`AGENT_BACKEND=openai`）

- [ ] 视觉 prompt 拆两步：先只给图做中性描述（每块砖和底砖的关系、斜顶凸点在哪侧），再用文字对照步骤判完成度。
      现在步骤文本 + 参考图和图同在一次调用里，模型照着预期抄，L 形黄砖看不出；单独问同一张图它答得对
- [ ] 视觉模型：16 张标注帧上 gpt-5.6-luna 12/16、gpt-6-luna 8/16（`tmp/poc/eyes_eval.py`），换不换 5.6，价钱两倍
- [ ] 屋顶朝向 / 贴着还是插上：两个模型、任何 effort、裁切后都判不出。可能要引导用户把有凸点的一侧转向相机，
      或者接受这一类不判
- [ ] 音量：眼镜通话流（STREAM_VOICE_CALL）在扬声器上只有 1/15，通话中按音量键调；不够再在 agent 加增益
- [ ] 眼镜手势切换参考模型视角（前滑/后滑），模型不再控制显示
- [ ] `deploy/start.ps1` 还没实际用过；结束后 app 偶尔自动重连开新会话（一次，疑似误触），留意
- [ ] 确认要连续 2 帧（约 5 s）；模型稳了再考虑 1 帧

## Agent / 模型（Gemini 路）

- [ ] 附和：看不清时顺着用户说（用户说后墙没搭，它先说搭好了，被纠正就道歉翻转）。先试提示词，
      但更像模型本身的能力问题
- [ ] 指南和 run id 从 token attributes 传入（上层控制器选任务），现在是 `BUILD_GUIDE` 环境变量 + 房间名
- [ ] extended-thinking 变体：要 NON_BLOCKING 工具，插件还不解析 `interaction_status`，先观望
- [ ] 成本：`MEDIA_RESOLUTION_HIGH` 每帧 280 tokens，静默时 0.3 fps；决定默认档位，或把 `silent_fps` 再压低
- [ ] 延迟随通话变长：每轮带全部历史帧。已做：只在说话时采样 + `look` 工具 + 上下文滑动窗口。
      看 ttft 是否稳住
- [ ] agent 容器往 `backend/frames` 写的文件是 root 属主，compose 里以宿主用户运行
