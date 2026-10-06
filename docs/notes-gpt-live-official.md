# GPT-Live 官方结构笔记（临时，2026-10-06）

来源：developers.openai.com/api/docs/guides/live、live-delegation、live-conversations、
voice-server-controls；LiveKit 插件源码 `livekit-plugins-openai/.../realtime/gpt_live_model.py`（1.8.3）。
目的：记下"如果不走我们现在的 watch → commentary 结构，官方管线能做什么"。暂不切换。

## 结构

- `gpt-live-1` 是纯音频前端，全双工，自己管打断。**不收图**："The Live audio frontend does not
  accept images directly." 视频没有提到。
- 把活交给后端叫 **delegation**，开 session 时选定，中途改要新开 session：
  - **responses**：OpenAI 跑后端 Responses 模型（建议 gpt-6-luna / gpt-6-sol），"supplies
    conversation context and returns backend results"。后端收到了什么我们看不到（事件里
    `input` 为空）。工具仍由我们执行：`response.output_item.done` 拿到 call，
    `response.item.create` 回 `function_call_output`，再 `response.create` 续跑。
  - **client**：后端我们自己跑。Live 只发一个 `session.delegation.created`，**不带任何文字**，
    上下文得从 `session.input_transcript.delta` / `output_transcript.delta` 自己拼。
- 后端线程是否跨次持久，官方只说 "can reuse prior response state when the active connection
  and state support it"，不保证。

## 我们的程序能往里塞什么

三个 append 事件，每条 ≤ 500 token，带 `delegation_id`（`null` = 整个会话）：

| 事件 | 作用 | 打断正在说的话 |
|---|---|---|
| `session.commentary.append` | 让模型马上说，**会改写** | 不 |
| `session.thinking.append` | 静默上下文，以后用 | 不 |
| `session.instructions.append` | 开发者指令，常驻 | **会**（"can interrupt speech in progress"） |

- **给后端塞图（仅 responses 模式）**：`response.item.create` 放一条 `input_image` 消息，再
  `response.create`；后端看完的回答 Live 自己念出来。这样后端那条线程里就有 Live 转的对话、
  我们推的帧、工具结果，是"一整串带图的上下文"。
- 没有 `response.create` 让 Live 主动开口的事件；要主动说话用 `session.instructions.append`。
- 没有取消语音的事件；mute 不停输出；sideband（服务端第二条连接）能发以上所有事件，不能控播放。
- 上下文窗 128k，超 90% 换引擎，只带 8192 token 历史。

## 速度判断

- 每推一帧后端仍要看一张新图再输出，和我们单独调 VLM 一样约 2 s；省的是连接开销
  （Live 到 Responses 是长连接、配置预热）和我们 commentary → 开口的约 0.9 s。
- 真正快的是**用户问"好了没"**：Live delegation 到后端，后端从上下文里已有的帧直接答，
  纯文本一跳约 1 s；我们现在的 check_now 只能读滞后的状态。
- 收益是一致性（能和上一帧比），风险是旧帧叙事（Gemini Live 上踩过）。

## LiveKit 插件（1.8.3）对应关系

- `generate_reply(instructions=…)` → `append_commentary("Immediately follow the instruction
  below. Do not wait for the caller to speak first. …")`：**不打断**，可改写。
- 公开方法：`GPTLiveSession.append_instructions / append_thinking / append_commentary`，
  从 `session.current_agent.duplex_session` 拿到。chat_ctx 里追加 system/developer 消息也
  会走 `append_instructions`。
- `interrupt()` 在 duplex adapter 里是空操作（"barge-in is the model's own, and it cannot
  be cancelled"）。
- `response.item.create` 插件只在回工具结果时用；没有公开的"给后端塞图"方法，但
  `send_event` 公开，可以不改插件直接发 `ResponseItemCreateEvent`，会不会和它的
  `response.create` 计数打架要试。

## 2026-10-06 VLM 实机一轮对照出的问题（已按此改代码）

- 单次 VLM 2.5 s 中位（1.9–4.2），手离开到 DONE 典型 6–7 s：静止 1 s + 两次串行 VLM。
- commentary 被我们自己压在"语音说完后"，压了 0–5.3 s；再加语音先回 check_now 的滞后状态，
  听起来是"我查一下 … 对了下一步"。
- wrong 的 reason 是 checks 原句（肯定句，"the disc's top touches the body"），语音听成确认，
  第 10 步回了 "That's right"。
- 第 10 步 checks 没有锁左边，后轮左移两列也能满足，VLM 看见了但按题答了 correct。
