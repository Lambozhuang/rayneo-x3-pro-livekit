# TODO

## 眼镜

- [ ] 前滑/后滑安排用途（例如切换字幕显示 / 摄像头预览）
- [ ] 功耗：加电量日志，跑一次完整通话看续航
- [ ] 曝光（可选）：白砖在半米外过曝，颗粒看不清。HAL 支持 AE 补偿 ±2 EV；做法是加
      `livekit-android-camerax` 模块，`capturer.getCameraX()` → `cameraControl.setExposureCompensationIndex`。
      先看中性色砖 / 拿近点是否已经够用
- [ ] 实验结束后 `glasses.ps1 -RestoreSleep`（启动时会把眼镜的摘下休眠关掉，不然摘下一分钟就断 Wi-Fi）
- [ ] 屏幕现在有状态、步骤列表、双方字幕。实验测的是网络质量对语音交互的影响，屏幕信息越多用户越不依赖语音，正式实验前再定去掉哪些

## Agent / 模型

- [ ] 人设、什么时候可以主动开口
- [ ] 附和：看不清时顺着用户说（用户说后墙没搭，它先说搭好了，被纠正就道歉翻转）。先试提示词，
      但更像模型本身的能力问题，A/B 其他模型时重点看这条
- [ ] 收尾：用户说再见后环境声被转写成日语、它继续接话。加 `end_call` 工具让它主动挂断
- [ ] 指南和 run id 从 token attributes 传入（上层控制器选任务），现在是 `BUILD_GUIDE` 环境变量 + 房间名
- [ ] 完成度判断：现在模型看摄像头自己判、`step_done` 只推进状态机。试过代码比对（颜色/尺寸/朝向/相对
      位置）——2D 能堵住背答案，但撑不到 3D，且没解决感知。方向是给模型参考图做 grounding（见下两条），
      而不是手写几何。Live 模型没法控制它看哪一帧（turn 默认含全部视频帧，一直积累），所以更像要换架构
- [ ] 主动开口：3.8 + 插件 1.8.2 上 `generate_reply` 可用了（开场已加）。换步时要不要让它主动说，
      还是等用户
- [ ] extended-thinking 变体：要 NON_BLOCKING 工具，插件还不解析 `interaction_status`，先观望
- [ ] 架构对比：GPT-Live（`gpt-live-1`，全双工）+ 单独视觉模型。LiveKit 插件里 GPT-Live 不收视频，
      要用 client delegation 自己抓帧、自己调视觉模型、`append_commentary` 回话；需要 livekit-agents[openai]≥1.8
      和账号的 GPT-Live 权限。切换点是 `build_session_model()`
- [ ] 参考图怎么给模型，待试：纯文字描述；开场 seed 全部参考图；换步时经视频流注入带标签的参考图；
      tool 返回图片（Gemini `FunctionResponse.parts`，插件未用、Live API 未验证）；只给另一个视觉模型看、返回文字
- [ ] 成本：`MEDIA_RESOLUTION_HIGH` 每帧 280 tokens，静默时 0.3 fps；决定默认档位，或把 `silent_fps` 再压低
- [ ] 延迟随通话变长：每轮带全部历史帧。已做：只在说话时采样 + `look` 工具 + 上下文滑动窗口。
      看 ttft 是否稳住；不行再降分辩率或分离视觉模型
- [ ] agent 容器往 `backend/frames` 写的文件是 root 属主，compose 里以宿主用户运行
