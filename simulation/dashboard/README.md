# FastBot 完整英文网页（CP23 本地工程支撑）

本目录复用已核对的CP22完整工程网页，接入CP23真实仿真；由Coach完成迁移支撑，不代表学习者独立实现或课程官方PASS。源码来源与变化见根目录webapp_assets.lock.json，当前真实模型来源见网页assets/MODEL-PROVENANCE.json。

## 已接入

- 英文完整布局：房间地图、独立FastBot三维视图、相机、位置/朝向/速度、摇杆、持久航点和导航状态。
- 网页使用当前仿真Xacro展开的URDF与原STL，包含真实关节状态；不再使用立方体代替。
- 原CAD前向-Y与ROS驱动前向X的差异以base_footprint根和固定关节适配；原CAD几何保留。Gazebo、里程计、Cartographer、Nav2与网页统一坐标。
- 实际13段探索、约21.32m路径生成房间地图；独立网格对照中非实体房间区域99.52%已有观测。家具内部/遮挡仍为未知；不是逐个机器人尺寸位置可达的证明。
- 地图原始栅格、裁剪索引、PGM/YAML、独立覆盖与逐格保存回读证据随data/maps保存。未知使用PGM128，避免205与0.25阈值组合误判为空闲。
- 大图像消息按官方ROSbridge协议有界重组；原始相机800×800，限速0.05m/s和0.30rad/s，输入/反馈超时归零。仅已指定本地仿真，不用于真机认证。
- 当前raw图像仅二维显示；上游旧相机插件的帧名兼容问题不作为三维光学投影接口使用。

## 运行

在项目根目录、WSL Ubuntu-22.04执行。先准备当前代码对应的本地镜像：

~~~bash
docker build -f simulation/Dockerfile.gazebo -t cp23-local/gazebo-axis:20261104 .
docker build -f simulation/Dockerfile.webapp -t cp23-local/web-dashboard:20261104 .
docker build -f simulation/Dockerfile.dashboard-support -t cp23-local/web-navigation:20261104 .
bash simulation/dashboard/run_local.bash
~~~

打开http://127.0.0.1:18000/，显式Connect。不会自动运动；Go只向已确认地图的航点发送请求，保存航点不移动机器人。默认观察窗口1800秒，Ctrl+C清理；可通过正整数CP23_SESSION_SECONDS调整。每次独立网络/容器与完整日志保留在runtime_logs/dashboard_*；航点和地图持久保留在runtime_logs/dashboard_state。

该帮助脚本用于复现完整网页的已存地图导航模式，启动Gazebo和含Nav2支撑的Web容器。课程Task1的三镜像/Compose核心练习仍保留：建图模式由Gazebo+Cartographer SLAM+Web三个容器组成，不同时运行Cartographer与AMCL抢占地图定位。此脚本不替代学习者后续Compose实现。

## 验证入口

- 浏览器/ROS实际运行：code_lab/verification.md，C032条目。
- 分片合同：node tests/rosbridge-fragments.mjs。
- 语法/格式与Git检查：runtime_logs/web_fidelity_20261104/checks.bash。
- 原始地图：data/maps/room.raw.grid.json；保存回读：data/maps/ROUNDTRIP.json。
- 协议依据：https://github.com/RobotWebTools/rosbridge_suite/blob/ros2/ROSBRIDGE_PROTOCOL.md。
- Task1整体独立检查、Compose、正式云端URL与官方验收另待；无推送或真机动作。

## 最终本机验证（2026-11-04）

同一版本使用RPP局部跟踪，以0.05m/s、0.30rad/s上限和0.15m/0.2rad到达门，Living room、Doorway、Bedroom均实际到达；保留此前低速DWB未完成的失败证据。原生松开约8ms输出零，未发零速即断线的独立客户端约0.339s后归零，均观察到停车；仅本轮样本。实际JPEG约9分钟持续显示，重载保留三个航点。重载后若显示succeeded-unowned，先核实实际任务已结束与停车，再按界面Reconcile idle协调所有权；不要重复发送上次目标。完整结果见最终dashboard_20261104T144127Z运行与verification.md。

当前自有实例已清理，地图/航点仍在runtime_logs/dashboard_state。该帮助启动器不是课程待写Compose，也不授予真机运行资格。
