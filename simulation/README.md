# Task1 — FastBot 仿真容器化

三个镜像包含 Gazebo 场景、SLAM 和 Web 应用，核心 Dockerfile 与 compose.yaml 由学习者逐片实现。课程运行资产来源和哈希见项目根的 course_asset_manifest.json 与 course_assets.lock.json。

- 本机入口见 COMPOSE_LOCAL.md。
- Docker Hub 的公开镜像与固定 digest 见 ../hub_release.lock.json。
- The Construct rosject1017054 的专用配置为 compose.cloud.yaml，部署时作为 docker-compose.yml 使用。该配置直接拉取镜像，Gazebo 内存上限为 4 GB。
- 云端用户 UID/GID 为 1026，DISPLAY 为 :1。simulation 下需要 .env 与 cloud_passwd，部署步骤和验收状态见项目根 README.md 的云端章节。
- 容器间使用 ROS_DOMAIN_ID=193，Web 对外端口为 7000，ROSbridge 为 9090。

课程云端的 Graphical Tools 已观察到房间与 FastBot。网页通过课程 webpage_address 和 rosbridge_address 提供的代理地址访问。云端当前是新的 SLAM 会话，旧的本地整屋地图仍保留在本地记录中。

学习记录与精确运行证据保存在上一级训练笔记。工程运行验证与正式评分分别记录，学习者减少帮助迁移检查按用户要求跳过。
