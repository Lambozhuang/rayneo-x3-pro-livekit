# eval/ — 判定器评测素材

录像来自眼镜自带相机（`deploy/record.ps1`），HEVC 2432×1824 30 fps，旋转元数据 −90°（竖幅）。
视频、抽帧、拼图不入库（.gitignore），布局、真值、参考图入库。

## truck/ — 2D 卡车，16×16 底板，13 步

- `plan.html`：搭建方案示意（行列坐标：列左→右 1–16，行上→下 1–16）
- 任务定义在 `backend/agent/guides/truck/task.toml`（和正式系统同一个文件）：13 步，每步 `color`/`cells` `[col0,row0,col1,row1]` 给 CV 判定器，`where`/`checks` 给 VLM 判定器，`say` 是眼镜端听到的话
- `refs/ref_stepNN.png`：第 N 步完成后的俯视参考图（带行列号），`ref_sheet.png` 全部拼图
- `events.json`：真值时间线。每步 `done` = 砖到位且手离开的 (片段, 秒)；`wrong` = 故意放错的区间和内容；
  `distractions` = 看别处的区间
- `run1/`：三段视频（part1 61.8 s；part2_p1 61.6 s；part2_p2 25.6 s）。part1→part2 之间约 7 分钟没动板子；
  p1→p2 之间约 2 s 空白（相机 60 s 单段上限），第 13 步落在空白里
  - `frames/<clip>/NNN.jpg`：1 fps 全分辩率抽帧，NNN = 秒 + 1。重建：
    `ffmpeg -i <clip>.mp4 -vf fps=1 -q:v 2 frames/<clip>/%03d.jpg`
  - `sheets/`：看片用的拼图（整帧 / 按绿色裁板 / 四处错误放大）

run1 里的故意错误：第 4 步错色（米色代白）、第 6 步错位（右偏约 2 格）、第 8 步错向加错位（手未离开）、
第 10 步错位（后轮右偏）。工作距离下底板约 750 px 宽，一格约 45 px。

## 脚本

| 文件 | 作用 | 结果落在 |
|---|---|---|
| `common.py` | 共用：路径、任务文件、真值、帧列表、编码；把 `backend/agent/src` 加进 path；`set_frames("frames_1080p15")` 切帧源 | — |
| `vlm_judge.py` | **VLM 路线（B 整帧 / C 裁板）**：每问一次模型调用，模型只从 `backend/.env` 读（`OPENAI_CHECK_MODEL` 等） | `truck/results/vlm/` |
| `cv_judge.py` | **CV 路线（D）**：跑正式系统的判定器 `backend/agent/src/judge_cv.py`（找板 → 拟合焦距补缺边 → 单应 → 逐格颜色 → 比任务文件 cells），只喂帧和画图；`calibrate` 重算色心 | `truck/results/cv/` |
| `gate_eval.py` | 门控统计，代码是正式系统的 `backend/agent/src/gate.py`（板完整 + 大片肤色；静止规则 1 fps 量不了） | `truck/results/gate/` |
| `replay_eval.py` | 门控 → 判定 → 状态机回放，`--judge vlm|cv` | 判定器各自目录 |
| `results_table.py` | 从结果目录生成 `RESULTS.md`（文字在 `results_notes.md`） | `RESULTS.md` |

```
python eval/vlm_judge.py run --route C --provider openai --prompt terse2 --questions truck/rest.json [--frames frames_1080p15]
python eval/vlm_judge.py labels                       # events.json 推出的 276 个逐帧问题表，不调 API
python eval/cv_judge.py overlay [--frames frames_1080p15]   # 先看格线对不对：sheets/cv/grid*.jpg
python eval/cv_judge.py run     [--frames frames_1080p15]   # 29 问 + 拼图 sheets/cv/rest_cv*.jpg
python eval/gate_eval.py signals && python eval/gate_eval.py score
python eval/replay_eval.py run --judge cv --confirm 2 [--frames frames_1080p15] && python eval/replay_eval.py report
python eval/results_table.py
```

29 问（`truck/rest.json`，Q1–Q29）= 每个"手离开、板静止"的状态挑一帧：13 对、3 错、13 未放。VLM 每问送系统提示 + 按 layout 生成的
步骤事实 + 裁板照片；CV 不送任何东西，本机算。第 8 步的错放全程手在板上，静止判定器按设计看不到，不在 rest 集里。

## 结果

全部结果、每次送进去的东西、答错的是哪一问、延迟、两条路线对比，见 **`eval/RESULTS.md`**。
