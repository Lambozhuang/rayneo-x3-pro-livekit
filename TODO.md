# TODO

## 眼镜

- [ ] 前滑/后滑安排用途（例如切换字幕显示 / 摄像头预览）
- [ ] 功耗：加电量日志，跑一次完整通话看续航
- [ ] 曝光（可选）：白砖在半米外过曝，颗粒看不清。HAL 支持 AE 补偿 ±2 EV；做法是加
      `livekit-android-camerax` 模块，`capturer.getCameraX()` → `cameraControl.setExposureCompensationIndex`。
      先看中性色砖 / 拿近点是否已经够用
- [ ] 通话里 agent 掉线（例如 Gemini key 失效）时屏幕上没有任何提示，只有沉默
- [ ] 屏幕上放什么待定。实验测的是网络质量对语音交互的影响，屏幕信息越多用户越不依赖语音，倾向只放最少的状态

## Agent / 模型

- [ ] 语言策略：跟随说话人 vs 固定中文/英文（现在没写，第一句会随机选语言）
- [ ] 人设、什么时候可以主动开口
- [ ] `remember_note` 只是占位（只打 log），做成按 user id 真正存储
- [ ] 加工具：时间、提醒、天气等
- [ ] 主动开口：3.1 上 `generate_reply` 被插件按模型名整段忽略，开场也不行；看 2.5 native audio（proactivity）、
      GPT Realtime 等能不能让 agent 先说话、主动提醒
- [ ] 架构对比：GPT Realtime 全双工 + 单独照片模型做检查；切换点是 `build_session_model()`
- [ ] 成本：`MEDIA_RESOLUTION_HIGH` 每帧 280 tokens，静默时 0.3 fps；决定默认档位，或把 `silent_fps` 再压低
- [ ] agent 容器往 `backend/frames` 写的文件是 root 属主，compose 里以宿主用户运行
