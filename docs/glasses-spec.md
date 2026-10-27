# RayNeo X3 Pro 的硬件和系统配置

本文记录 2026-10-20 用 adb 从实验用眼镜（序列号 A06B4ADF308F553）上读到的配置。标“推断”的项不是设备直接报告的，而是从代号或驱动名推出来的。

## 系统

| 项 | 值 |
|---|---|
| 型号 | ARGF20，产品名 RayNeoX3Pro，设备代号 MercuryLiteXR |
| 系统 | Android 12（API 32），版本号 SKQ1.250204.001，增量版本 3G2R，编译于 2026-06-26 |
| 安全补丁 | 2025-02-05 |

## 处理器、内存和存储

| 项 | 值 |
|---|---|
| SoC | 高通，平台代号 `neo`；推断是 Snapdragon AR1 Gen 1，系统属性里没有写出型号 |
| CPU | 4 个 Cortex-A55 核（CPU part 0xd05），每核最高 1.997 GHz，ABI 为 arm64-v8a |
| GPU | Adreno 621，支持 OpenGL ES 3.2 和 Vulkan |
| 内存 | MemTotal 3.7 GB（4 GB 档） |
| 存储 | /data 分区 22 GB |

## 显示

显示屏报告为 1280×480、60 Hz、160 dpi，这个画面由左右两眼各 640×480 拼成。

## 硬件视频编解码

系统通过 `ro.media.xml_variant.codecs=_neo_v2` 加载 `/vendor/etc/media_codecs_neo_v2.xml`，下表列出其中的高通硬件编解码器（c2.qti.*）。

| 格式 | 硬件解码 | 硬件编码 | 性能点 |
|---|---|---|---|
| H.264/AVC | 有，另有 low_latency 和 secure 版本 | 有，支持 CBR/VBR 和 intra-refresh | 4K30、1080p120、720p240 |
| H.265/HEVC | 有，另有 low_latency 和 secure 版本 | 有，另有一个最大 512×512 的 CQ 版本 | 4K30、1080p120、720p240 |
| VP9 | 有，另有 low_latency 版本 | 没有，只有软件编码 | 4K30 |
| VP8 | 没有，只有软件解码 | 没有，只有软件编码 | — |
| AV1 | 没有，只有软件解码 | 没有，只有软件编码 | — |
| HEIC 图片 | — | 有 | — |

VP8 和 VP9 都没有硬件编码器，所以眼镜用 VP8 发 WebRTC 视频时由 A55 软件编码；要用硬件编码，发布视频时得选 H.264 或 H.265。

音频有硬件 AAC 编解码，以及 ALAC、APE、WMA、AMR-WB+ 的硬件解码；Opus 只有软件实现 c2.android.opus。

## 摄像头

| 摄像头 | 像素阵列 | 焦距 |
|---|---|---|
| 0（后置） | 4032×3024，约 12 MP | 1.90 mm |
| 1（后置） | 640×480 | 0.71 mm，推断是给追踪用的广角 |

主摄的自动曝光可调（2026-10-27 从 `dumpsys media.camera` 读到）：曝光补偿范围 -12 到 +12，步长 1/6 EV，即 ±2 EV；AE 可锁定；AE 可关闭，声明 MANUAL_SENSOR 能力，ISO 100 到 1600（模拟增益上限 1600），曝光时间 37.5 µs 到 317 ms；一个 AE 测光区域；对焦固定；硬件等级 LIMITED。同一份 dump 里保留着本 app 最近一次会话的参数：AE 开、补偿 0、测光区域整帧且权重 0、ISO 2343、曝光 10 ms，也就是在实验室桌面前自动曝光把增益推到了上限。这些是 HAL 声明的能力，补偿是否真的改变画面要在设备上试（`glasses.ps1 -ExposureSweep`）。

## 电池

电池是锂电池，电量计芯片是 cw221X，充电芯片是 bq256xx，USB 充电时最大电流报告为 2.4 A。读取时电量 100%、电压 4.449 V、温度 24.5 °C。电量计没有开放 charge_full_design，所以设备上读不到设计容量；batterystats 给出的 1000 mAh 是 AOSP 的默认占位值，不是真实容量。

## 无线

眼镜支持 Wi-Fi 6（802.11ax）。Wi-Fi 驱动名为 `kiwi_v2`，配置在 `/vendor/etc/wifi/kiwi_v2/WCNSS_qcom_cfg.ini`：`BandCapability=3` 只开了 2.4 GHz 和 5 GHz，`he_*_mcs_map=0xFFF5` 把 802.11ax 限在两个空间流以内、最高 MCS 9，`gSetTxChainmask1x1=1` 和 `gSetRxChainmask1x1=1` 设定了单流模式下用的天线链。眼镜实际协商出的标准、信道宽度和空间流数要连上 AP 才能读到。

眼镜支持蓝牙 5.3：开机时控制器对 HCI Read_Local_Version_Information 的响应里 HCI 和 LMP 版本都是 12（即 5.3），厂商 ID 29（高通）。控制器的 LE 特性位表明它支持 2M PHY、扩展广播、周期广播和 CIS/BIS 等时信道（LE Audio 需要的链路层能力），不支持 Coded PHY。蓝牙名称是 RayNeo X3 Pro-F553。

## 传感器

| 传感器 | 芯片 |
|---|---|
| 加速度计、陀螺仪 | ST LSM6DSR |
| 磁力计 | Memsic MMC56x3x |
| 环境光 | Sensortek STK3x3x |
| 重力、线性加速度、旋转向量、游戏旋转向量 | 高通和 AOSP 的融合传感器 |

## 读取方法

下面的命令读出了上面各项，眼镜通过 USB 连着时可以重新跑一遍。

```sh
adb shell getprop                                   # 型号、系统版本、平台代号、codec 配置变体
adb shell cat /proc/cpuinfo /proc/meminfo           # CPU 核和内存
adb shell cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq
adb shell dumpsys display                           # 分辨率和刷新率
adb shell dumpsys SurfaceFlinger | grep GLES        # GPU
adb shell cat /vendor/etc/media_codecs_neo_v2.xml   # 硬件编解码器和上限
adb shell dumpsys media.camera                      # 摄像头
adb shell dumpsys battery                           # 电池状态
adb shell ls /sys/class/power_supply/               # 电量计和充电芯片
adb shell dumpsys wifi                              # Wi-Fi 链路
adb shell cat /vendor/etc/wifi/kiwi_v2/WCNSS_qcom_cfg.ini   # Wi-Fi 驱动配置
adb shell dumpsys sensorservice                     # 传感器
adb bugreport br.zip                                # 蓝牙 HCI 抓包在 FS/data/misc/bluetooth/logs/hci_snoop*.cfa
```

蓝牙版本只能从 HCI 抓包里读：dumpsys 不报告控制器版本，而系统的蓝牙 snoop 日志设成了 full，bugreport 会把它带出来。抓包是 btsnoop 格式，开机时那条 Read_Local_Version_Information（opcode 0x1001）的 Command Complete 事件里带着 HCI 和 LMP 版本。
