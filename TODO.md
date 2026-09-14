# TODO

## 眼镜

- [ ] 前滑/后滑安排用途（例如切换字幕显示 / 摄像头预览）
- [ ] 功耗：加电量日志，跑一次完整通话看续航
- [ ] 曝光（可选）：白砖在半米外过曝，颗粒看不清。HAL 支持 AE 补偿 ±2 EV；做法是加
      `livekit-android-camerax` 模块，`capturer.getCameraX()` → `cameraControl.setExposureCompensationIndex`。
      先看中性色砖 / 拿近点是否已经够用
- [ ] 通话里 agent 掉线（例如 Gemini key 失效）时屏幕上没有任何提示，只有沉默

## Agent / 模型

- [ ] 语言策略：跟随说话人 vs 固定中文/英文（现在没写，第一句会随机选语言）
- [ ] 人设、什么时候可以主动开口
- [ ] `remember_note` 只是占位（只打 log），做成按 user id 真正存储
- [ ] 加工具：时间、提醒、天气等
- [ ] 成本：`MEDIA_RESOLUTION_HIGH` 每帧 280 tokens，静默时 0.3 fps；决定默认档位，或把 `silent_fps` 再压低
- [ ] agent 容器往 `backend/frames` 写的文件是 root 属主，compose 里以宿主用户运行

## 家里的公网部署

- [ ] Caddy 加 `deploy/Caddyfile.livekit` 的 site block 并 reload（现在 `https://livekit.example.com` TLS 直接失败）
- [ ] ufw 放行 80/udp（媒体）；7880/tcp、3003/tcp 走 Caddy 不用开
- [ ] Mac mini `backend/.env` 切到 `AUTH_MODE=static` + `LIVEKIT_PUBLIC_URL=wss://livekit.example.com`，眼镜 credential 用 `AUTH_STATIC_TOKEN`
- [ ] Mac mini 上的 `backend/docker-compose.override.yml`（host 网络）已被 compose 默认覆盖，删掉
- [ ] 从公司网 `ssh mac-mini` 主机密钥不匹配，回家确认
