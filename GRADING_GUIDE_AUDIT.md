# CP23 Grading Guide 逐项复核

日期：2026-11-09（Asia/Shanghai）。当前状态：Task1持续摇杆反例已通过CPU资源修复及4秒持续控制复验；Task2既有复核保持。不是官方评分结果。

源码：https://github.com/Cooper-Yu/fastbot_ros2_docker，已验证克隆 revision 2b13efce5d036c3349fa76f5824f9d6fbdb30cdb。
依据：用户指定课程正文中的 Task1、Task2 Grading Guide；下面保留原命令拼写。环境准备和适配单列，未以历史功能结果替代本轮结果。

| 指南项目 | 本轮结果 | 实际证据/限制 |
| --- | --- | --- |
| Task1：cd 到 simulation | VERIFIED | 云端交互终端实际执行 |
| Task1：docker-compose up | VERIFIED_AFTER_ENV_REPAIR | 新实例恢复 Docker 后，交互执行原命令，从 Hub 拉取固定三镜像；完整相机配置运行 |
| Task1：docker ps | VERIFIED | 原命令列出三个 running 实例；首次查询因资源压力未返回，已中断后复查 |
| Task1：docker images | VERIFIED_AFTER_REPAIR | 初始 digest 拉取显示 none；核对 RepoDigests 后为相同内容补三个原标签，原 docker images 已逐项显示 |
| Task1：Graphical Tools 场景 | VERIFIED | 新实例实际显示房间和 FastBot；后续检查 gzserver/gzclient 存活、OOM 计数0 |
| Task1：webpage_address / 网页访问 | VERIFIED | 原命令返回新实例地址，专用浏览器实际打开英文网页 |
| Task1：rosbridge_address / 连接 | VERIFIED | 原命令返回新 WSS 地址，网页 connected / Command channel verified |
| Task1：网页摇杆 | VERIFIED_AFTER_CPU_REPAIR | Gazebo从2核改4核；原生持续按住4秒，81条非零最终指令、实际移动约6cm、松开停车；此次网页未出现反馈失鲜 |
| Task1：网页实时建图 | VERIFIED | 实际 /map 数据及网页栅格171×88；5208已知格，时钟推进；当前局部地图仍有未知区域 |
| Task2：README 下载/启动说明 | VERIFIED | 根 README 与 real/README.md 给出公开地址、准备和启动步骤 |
| Task2：git clone | VERIFIED | 在 Pi 标准源码父目录原样克隆公开 HTTPS 仓库成功，HEAD 为 2b13efc |
| Task2：docker-compose up | VERIFIED_WITH_ENV_ADAPTATION | 原拼写执行；Pi 的 V2 由用户级兼容入口调用，使用已校验镜像缓存 |
| Task2：docker ps | VERIFIED | 两个应用容器及实际镜像标签可见；另有独立网络桥和原平台 RRL |
| Task2：ros2 topic list / 激光 | VERIFIED | /fastbot/scan |
| Task2：ros2 topic list / 摄像头 | VERIFIED | /fastbot_camera/image_raw |
| Task2：ros2 topic list / 速度命令 | VERIFIED | /fastbot/cmd_vel；本轮未发布运动指令 |
| Task2：关机再开机自动启动 | VERIFIED | 新 boot_id、同 CID 的新 StartedAt、running / OOM=false |
| Task2：外部电脑列出话题 | VERIFIED | 本机 WSL 原 ros2 topic list exit0，25 话题 |
| Task2：RViz2 实时地图 | VERIFIED | 本机 WSL，Global Status: Ok；新地图与真实 TF 已收取 |

## Task2 本轮证据

Pi 旧工程完整保存在 /home/yg-fastbot/cp23_grading_backups/20261109-6d92f2/prior-project，标准路径换为真实 Git 克隆；只复制已审阅的本机 .env，镜像和设备参数保持。
重新上电前后 boot_id：1b0bc28f-4222-42df-8eb0-841a3ebeaca6 → 1b382028-edb1-4cff-b68b-2cae6fe24373。
两个应用 StartedAt 2026-11-09T05:53:36Z，Docker enabled，restart unless-stopped。
WSL 新数据：scan13 / image32 / odom22 / map3 / tf162；地图81×99，3674已知格；速度0，命令发布者0。
截图和原始输出：runtime_logs/grading_guide_20261109/task2-rviz-after-boot.png、powercycle.json、literal-steps.json、clone-receipt.json、external-topic-list.stdout、external-data.stdout。

## Task1 历史失败与环境适配

本次云端最初没有 Docker CLI / Compose，按已授权范围安装并启动服务后才执行指南命令。
rosject 外层 memory.max=2684354560（2.5 GiB），外层 oom=2 / oom_kill=1。Gazebo 自身上限为4 GiB、其 max/oom 计数为0，但子进程 oom_kill=1，日志 gzserver exit -9。不能以宿主机 MemAvailable 或 PID1 running / OOMKilled=false 判仿真通过。
原输出、失败日志和后续修复分别保存，不删除失败，也不将兼容入口、缓存预载或配置适配写成原生环境零准备通过。
正式评分尚未提交；学习者独立检查仍为 SKIPPED_BY_USER。

## 2026-11-09 新实例完整配置复验

用户恢复订阅后，实际新 boot_id 为 63cf56cf-da79-416c-b464-e04742848fff；Docker engine b8de34f7-15d6-4b74-84b2-449536536d96。可见外层 memory.max=max，memory.events 的 max/oom/oom_kill 均0。订阅是否为额度变化的唯一原因未独立核实。

新实例重新安装 Docker/Compose；恢复原 compose.cloud.yaml 对应完整配置（4GiB容器上限、LP_NUM_THREADS=2、未使用softpipe），未移除相机或改动发布镜像。三个应用 StartedAt 为2026-11-09T07:07:34Z。后续 Gazebo 实占约2.57GB，gzserver/gzclient/robot_state_publisher均存活；三个容器与外层OOM计数均0。软件渲染实时系数约0.22–0.23，GUI帧率较低，不能宣称实时性能。

独立实时观察 scan7/odom62/map3/clock62，仿真时钟91.02→91.63，地图171×88/5208已知格；网页显示课程模型、地图、实测位姿与800×800相机。相机按仿真时间更新，慢仿真时网页可能短暂显示STALE；不宣称恒定墙钟帧率。当前地图为新SLAM会话的局部地图，本地历史整屋地图保留。

摇杆测试先等待唯一最终发布者web_adapter、激光前方约0.394m，再原生按住1100ms并松开。独立观察1304条指令，其中3条非零，最高线速度0.0378205m/s、角速度0；1482条odom，observed_motion=true、stopped=true，最后5条指令均0。只对云端仿真，未移动Task2真机。

原始证据保留在忽略目录runtime_logs/grading_guide_20261109：subscription-final-checks.json、subscription-gazebo.png、subscription-web-after-manual.png；云端同目录subscription_resume保留准备、配置、运行与观察日志。代理能力地址不提交公开仓库。正式评分NOT_SUBMITTED；学习者独立检查SKIPPED_BY_USER。

2026-11-09持续按住复测修订：原生保持3s，实际线速度曾达约0.04m/s；约0.83s出现Manual control permission lost及Measured feedback invalid or stale; output zero。浏览器focused=true/hidden=false，自动释放后本次按住不续走。仅移动约5mm，最终停车；具体scan/odom/TF失鲜来源未细分。此前短时测试不足以证明持续摇杆正常，Task1该项重新打开REPAIR；未修改产品或放宽保护。详见本地忽略证据joystick-sustained-hold-trace.json。

## 持续控制反例的修复与复验

2026-11-09对照检查：Gazebo为2核上限、累计8249/8298个周期发生CPU限流。22秒观察中雷达42帧，接收间隔均值0.514s/最大0.698s/21次超过0.5s；失鲜时odom有效且TF新鲜，雷达源时间戳约落后0.08–0.095仿真秒，直接触发项是雷达实际接收年龄超过0.5s。旧短时移动不代表持续控制正常，失败证据保留。

仅将同一Gazebo容器CPU上限从2核改为4核做对照：RTF 0.193→0.390，雷达间隔均值0.257s/最大0.377s，22秒观察无大于0.5s的间隔，反馈失鲜状态6→0。场景、800×800相机、镜像内容、0.5s反馈门与0.3s命令看门狗不变。云端docker-compose.yml及源码simulation/compose.cloud.yaml均已持久化4核，云端Compose解析通过。

当前实例原生摇杆按住4s：网页从Holding到松开无Waiting/反馈失鲜，地图位姿0.008→0.060m；独立ROS观察1305指令/81非零、最大0.0378205m/s、2498odom、实际位移约0.060m、最终停稳，末5指令0。三应用及gzserver/gzclient仍运行，OOM计数0。此项为本实例当前负载下的修复验证，不承诺软件渲染硬实时性能。证据为cpu4-repair-receipt.json、cpu4-hold4s-trace.json（均在本地忽略的runtime_logs/grading_guide_20261109）。