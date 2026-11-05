# 本机三容器建图运行

环境：WSL Ubuntu-22.04 / ROS 2 Humble / Gazebo Classic 11。学习者核心为compose.yaml；compose.local.yaml、local_passwd与run_compose_local.bash是Coach本机支撑。与dashboard目录的二容器保存地图Nav2模式分别使用。

## 准备镜像

在工程根运行，无构建时间上限：

~~~bash
CP23_RUN_ID=build-only docker compose -p cp23-course-local -f simulation/compose.yaml -f simulation/compose.local.yaml build
~~~

## 启动与停止

~~~bash
bash simulation/run_compose_local.bash
~~~

脚本生成run id并记录实际配置/镜像，默认观察1800秒，Ctrl+C或该运行日志目录的stop.request停止。可用CP23_SESSION_SECONDS正整数指定观察长度；这是运行观察范围，不是构建限时。已有同项目容器时拒绝接管，先由原运行负责停止。脚本只启动已有镜像，不在运行时下载/构建。

浏览器访问http://127.0.0.1:18000/，显式连接ws://127.0.0.1:19090。当前为实时SLAM建图模式，无Nav2保存地图导航；同域193，不接硬件，不自动发送运动。端口是否空闲在启动时仍需确认。

Gazebo采用headless:=1，仅无交互Gazebo窗口，仍经WSLg X11只读socket渲染真实相机。资源上限Gazebo4核/4GiB、SLAM2核/2GiB、Web3核/3GiB；只读nonroot1000、cap-drop与tmpfs，使用SIGINT/20秒停止，不设自动重启。local_passwd仅合成非敏感UID映射，不包含宿主账号凭据。

Web将web-data命名卷接到/data。项目卷名cp23-course-local_web-data，保留在清理后；删除容器/网络不删除卷。Dockerfile内/data初始目录归1000:1000，供新卷初始化；实际写入与重建保留已验。不要使用删除卷的选项进行日常停止。

## 已验范围与剩余门

2026-11-05：三镜像实际构建、三服务真实ROS测量→Cartographer/map→Web转接，HTTP200及WebSocket地图/JPEG通过；测试航点写入后强制重建Web，完整文档一致，随后仅移除测试航点。最终三服务exit0/OOMfalse、容器/网络移除、卷保留。实际镜像与源码见../compose_runtime.lock.json，运行证据见../verification.md。

本轮静止，未做新的桌面浏览器/摇杆运动回归，不宣称整屋重建、真机、官方或学习者独立PASS。既有C032运动/完整网页证据保留其原范围，减少帮助检查与正式云端仍待。
