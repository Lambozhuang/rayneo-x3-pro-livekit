# TODO

## 眼镜

- [ ] 前滑/后滑安排用途（例如切换字幕显示 / 摄像头预览）
- [ ] 功耗：加电量日志，跑一次完整通话看续航
- [ ] 曝光（可选）：白砖在半米外过曝，颗粒看不清。HAL 支持 AE 补偿 ±2 EV；做法是加
      `livekit-android-camerax` 模块，`capturer.getCameraX()` → `cameraControl.setExposureCompensationIndex`。
      先看中性色砖 / 拿近点是否已经够用
- [ ] 眼镜 Wi-Fi 会自己关掉：系统判定"摘下"（`setDeviceState:0`，佩戴传感器，戴着也会误判）→ 休眠 →
      `RayneoSuspendManagerService.WifiDisableJobService` 60 秒后关 Wi-Fi。相关 global 设置：
      唯一开关是 `deep_suspend_disabled_persist`（=1 整个摘下休眠链路停掉，含关 Wi-Fi/BT，重启保留；
      `_tmporary` 到重启为止），60 秒是写死的；设置界面里没有。要不要开，待定
- [ ] 屏幕上放什么待定。实验测的是网络质量对语音交互的影响，屏幕信息越多用户越不依赖语音，倾向只放最少的状态

## Agent / 模型

- [ ] 语言策略：现在提示词是跟随说话人；要不要固定
- [ ] 人设、什么时候可以主动开口
- [ ] 附和：看不清时顺着用户说（用户说后墙没搭，它先说搭好了，被纠正就道歉翻转）。先试提示词，
      但更像模型本身的能力问题，A/B 其他模型时重点看这条
- [ ] 收尾：用户说再见后环境声被转写成日语、它继续接话。加 `end_call` 工具让它主动挂断
- [ ] 指南和 run id 从 token attributes 传入（上层控制器选任务），现在是 `BUILD_GUIDE` 环境变量 + 房间名
- [ ] 完成度判断：现在模型看摄像头自己判、`step_done` 只推进状态机。试过代码比对（颜色/尺寸/朝向/相对
      位置）——2D 能堵住背答案，但撑不到 3D，且没解决感知。方向是给模型参考图做 grounding（见下两条），
      而不是手写几何。3.1 又没法控制它看哪一帧（turn 默认含全部视频帧，一直积累），所以更像要换架构
- [ ] 主动开口：3.1 上 `generate_reply` 被插件按模型名整段忽略，开场也不行。GPT Realtime 随时可以；
      GPT-Live 走 commentary 通道，模型可以拒绝
- [ ] 架构对比：GPT-Live（`gpt-live-1`，全双工）+ 单独视觉模型。LiveKit 插件里 GPT-Live 不收视频，
      要用 client delegation 自己抓帧、自己调视觉模型、`append_commentary` 回话；需要 livekit-agents[openai]≥1.8
      和账号的 GPT-Live 权限。切换点是 `build_session_model()`
- [ ] 参考图怎么给模型，待试：纯文字描述；开场 seed 全部参考图；换步时经视频流注入带标签的参考图；
      tool 返回图片（Gemini `FunctionResponse.parts`，插件未用、Live API 未验证）；只给另一个视觉模型看、返回文字
- [ ] 成本：`MEDIA_RESOLUTION_HIGH` 每帧 280 tokens，静默时 0.3 fps；决定默认档位，或把 `silent_fps` 再压低
- [ ] agent 容器往 `backend/frames` 写的文件是 root 属主，compose 里以宿主用户运行
