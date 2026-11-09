# 模板来源与约定

| 部分 | 采用的基础 | 本工程补充 |
| --- | --- | --- |
| 包结构 | [ROS2 官方 ros2 pkg create](https://github.com/ros2/ros2_documentation/blob/humble/source/Tutorials/Beginner-Client-Libraries/Creating-Your-First-ROS2-Package.rst) | 只补外围工程支持，不填核心实现 |
| C++ 排版 | [ament_clang_format Humble 配置](https://github.com/ament/ament_lint/blob/a8b535a6d073233fc95b87c3ac4bcb1913a3b046/ament_clang_format/ament_clang_format/configuration/.clang-format) | 定义块间空行，clang-format 14+ |
| C++ 命名/规模 | clang-tidy | snake_case、CamelCase、60 行提醒 |
| Python | PEP 8 / Ruff | 100 列、单引号、语句与分支检查；不声称与所有 ament lint 完全等价 |
| YAML / XML | Prettier、yamllint、Red Hat XML | 2 空格与配置校验入口 |
| 文档页面 | [Doxygen Awesome v2.3.4](https://github.com/jothepro/doxygen-awesome-css/tree/v2.3.4) | 固定 CSS、包/接口导航 |
| 流程与工程关系 | Mermaid / Obsidian Canvas | 空白学习骨架与真实文件链接 |
| 调试与测试 | VS Code cppdbg/debugpy、colcon、GoogleTest/pytest | 真实参数确认后接入，不生成伪通过用例 |

源地址与 SHA256 保存在 docs/template_sources.json。
ament 风格来源许可见 docs/_theme/ament-style-LICENSE；Doxygen Awesome 的 MIT 许可见 docs/_theme/LICENSE。
这些第三方许可只约束所包含的第三方文件，不替包选择发布许可。
功能代码许可由建包时显式 --license 决定。

模板版本 1.1.1。本工程采用现有成熟工具的组合，不声称它是 ROS2 官方提供的完整课程模板。
