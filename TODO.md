# TODO

## 近期（按 TASK.md 验证顺序）

- [x] 录 2D 摆放视频，标真值（eval/truck/run1，13 步，4 处故意错误）
- [x] 判定器 B/C 第一轮：网格 prompt 不行，关系 prompt 行；luna low ≈ 4–5 s 稳，sol none ≈ 2.4 s 漏最细的位置错（eval/README.md 结果表）
- [x] 判定器 VLM 续：Qwen@OpenRouter 不如 sol；sol none terse 跑完 29 问 29/29、约 1.9 s（措辞见 guides/truck/task.toml where/checks）
- [ ] 判定器：换一次新录像验证措辞是否过拟合这一次的帧；派生 1080p15 版再跑 29 问
- [ ] 每步事实生成器：从每步参考图（乐高可直接从格坐标）用大模型按本次措辞规则写 where/checks，再对录像校一遍；换任务不手写
- [x] 门控：板完整 + 大片肤色，静止帧 70/70 放过，手帧漏 20/75 但判定器自己能答对（eval/README.md）
- [x] 状态机 + 回放：原分辨率 13/13 步 ±1 s、3/3 错、零误报；1080p 下第 5 步卡死连锁（eval/README.md）
- [ ] 改任务：第 5 步白砖换色（同色不相邻），第 9 步事实去掉"同宽对齐"；重录一段，原分辨率 + 1080p 各回放一遍
- [x] 判定器 / 门控 / 状态机搬进 agent（src/judge_cv.py、judge_vlm.py、gate.py、progress.py），watch.py 瘦成胶水；eval 跑的就是这份代码
- [x] 上机第一天：门控、焦距拟合实机可用；CV 色心随自动曝光漂移，先切 VLM；VLM 一轮 13 步走完，单次 2.5 s、串行两次确认 6–7 s，commentary 被压在语音后
- [x] 上机第二轮（VLM，宽松门控）：note 打断生效，判定 2.0 s 中位、放行 ~80 %；check_now 一次没被调用，"好了没"变成等下一条 note（5 s，最长 21 s）；wrong/not_placed 来回翻导致第 3 步纠正 9 s、说四遍
- [x] 上机第三轮（到第 5 步）：开口塞旧状态 → Live 答得快但是手在板上那帧的结论（"看不见，调整角度"）；判定 2.2 s 中位，输入 token 多少对延迟几乎无影响（固定 ~1.9 s）
- [ ] 上机第四轮：开口时按帧时间取"当下"的结论（开口前 1 s 内），没有就先垫一句再用指令回答；wrong 2/3 窗口；左右分栏 UI
- [ ] 判定调用量：两路并发约 0.8 次/秒，六成是拿砖时反复判 not_placed；考虑 not_placed 连续时放慢或降一路
- [ ] 肤色窗口在实验室光线下测不到手（skin 0.00–0.09），手帧只靠 motion 和 VLM 自己答 cannot_see
- [ ] 青柠砖在通话流里偏黄，VLM 时而判 wrong 时而判 not_placed
- [ ] CV 判定器回到实机前：颜色改按色相分类或用底板做白平衡参考，fit_focal 挪出判定路径（实机 0.4–2.3 s 尖峰）
- [x] 判定器 D：纯 CV（eval/cv_judge.py），29 问原始 29/29、1080p 28/29，回放两种画质都不卡；弱点是手压板边 / 悬在板上（eval/RESULTS.md）
- [ ] 判定器 D 续：手在板上的帧要么门控拦（15 fps 静止一秒），要么用凸点格纹校验格子对不对；阈值在第二段录像上验一遍
- [x] 派生通话流规格视频（1080p 15 fps 4 Mbps）再跑一遍判定器：26/29，同色相邻砖和细位移丢失（eval/README.md）
- [ ] 用 app 真实通话流抓一帧（FrameDump）对比底板像素占比，确认派生版和实际一致
- [ ] 相机 60 s 单段上限：手机伴侣 app 看有没有时长设置；没有就给 app 加录像模式（CameraX，无上限）
- [x] 任务格式：guides/truck/task.toml 一份两用（say + color/cells + where/checks + [colours]），eval/truck/layout.json 删掉
- [ ] 录像回放 harness：按真实节奏（取帧 → 判定耗时 → 下一帧）回放，输出状态时间线，对人工标注算检出延迟、误跳、费用。
      看 GlassKit 的 eval CLI 能否直接用
- [x] 接回 GPT-Live：commentary 只来自状态机事件，check_now 读状态不调模型；judge: / voice: 两层打点
- [ ] 旧 3D 小房子的 guide、渲染参考图、`tmp/poc/eyes_eval.py` 在新任务跑通后清掉

## 眼镜

- [ ] 屏幕只留参考图 + 当前步；现有状态 / 步骤列表 / 双方字幕正式实验前裁
- [ ] 前滑/后滑用途（切参考图角度）
- [ ] 音量：通话流扬声器只有 1/15，通话中按音量键调；不够再在 agent 加增益
- [ ] 功耗：电量日志，跑一次完整通话看续航
- [ ] 实验结束后 `glasses.ps1 -RestoreSleep`

## 部署 / 实验

- [ ] `deploy/start.ps1` 没实际用过
- [ ] 丢包注入：lab PC 上 tc 按端口/流，只打语音 + 上行视频；LiveKit 侧丢包/抖动/码率与 reply_ms 同记
- [ ] 结束后 app 偶尔自动重连开新会话（疑似误触），留意

## 搁置

- Gemini 路：代码保留不动，不再推进
- 3D 参考模型流下发（已跑通）：2D 任务用俯视图即可，实时流作为 future work
- 任务 / run id 从 token attributes 传入（上层控制器选任务）
