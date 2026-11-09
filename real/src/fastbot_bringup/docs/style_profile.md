# ROS2 教学工程配置 1.1

本配置适用于新建的 Section/Checkpoint 工程。
采用 ROS2 ament 的 C++ 排版、PEP 8/Ruff 的 Python 排版，以及 Prettier/yamllint/XML 的配置规范。
已有项目优先沿用它的约定。

## 默认效果

| 项目 | 默认约定 | 目的 |
| --- | --- | --- |
| 单行宽度 | 100 列；编辑器显示参考线 | 方便并排阅读与 diff |
| C++ 缩进 | 2 空格 | 与 ROS2 基础风格一致 |
| C++ 大括号 | 函数/类换行，短 if/for 同行 | 清楚区分定义和内部控制流程 |
| C++ 定义之间 | 保留空行；短函数不压缩成一行 | 每项职责更容易定位 |
| Python | 4 空格、单引号、PEP 8 空行 | 同一项目稳定排版 |
| YAML / XML | 2 空格、统一属性/层级排版 | 看清参数层级和结构 |
| 命名 | 类 CamelCase；函数/变量 snake_case；C++ 私有成员后缀 _ | 跨文件识别角色 |
| 函数规模 | C++ 60 行、4 层嵌套提醒；Python 语句/分支阈值单独管理 | 提醒审阅职责和流程 |

这些是基于成熟规范选择的工程约定，不声称所有语言必须使用完全相同的写法。
单行宽度、函数行数与语句数量是不同指标。
参考线也不会强制截断字符串。

## C++ 排版示例

保存前的紧凑写法：

```cpp
double limit_value(double value,double upper){if(value>upper){return upper;}return value;}
```

本模板 formatter 输出：

```cpp
double limit_value(double value, double upper)
{
  if (value > upper) {
    return upper;
  }
  return value;
}
```

这是排版展示。
formatter 调整换行和空格；实际业务含义、接口约定和判断由学习者实现与验证。
方法内部仍可按阶段写注释；超过规模阈值先审阅职责，不按固定行数切割。

## Python 与 YAML 示例

```python
class ErrorCalculator:
    def compute_error(self, target: float, measured: float) -> float:
        return target - measured

    def reached_goal(self, error: float, tolerance: float) -> bool:
        return abs(error) <= tolerance
```

示例中的类型注解和计算由作者写入，formatter 不会自动替学习者补这些含义。
类内方法之间留一行空行；顶层定义按 PEP 8 排版。

```yaml
distance_controller:
  ros__parameters:
    target_distance: 2.5
    stop_tolerance: 0.05
    enabled: true
```

层级、重复键与布尔写法由检查辅助核对；参数的真实名称、类型、单位和加载行为仍需验证。

## .vscode 的阅读辅助

| 设置 | 含义 |
| --- | --- |
| editor.rulers = [100] | 显示 100 列参考线 |
| editor.guides.indentation | 显示缩进层级 |
| editor.guides.bracketPairs / bracketPairColorization.enabled | 显示括号关联与配色 |
| editor.renderWhitespace = selection | 选中时看见空白，方便检查缩进 |
| editor.stickyScroll.enabled | 滚动时保留当前定义/结构的上层位置 |
| files.encoding / files.eol | 新文件采用 UTF-8/LF；已有文件的编码与换行单独核对 |

这些辅助只改变阅读显示。
字体、字号、颜色主题、行距和图标主题放在个人设置，按自己的屏幕选择。
代码风格由项目规则固定，团队查阅和自动检查能得到一致结果。

settings.json 保留标准 JSON，按“保存与显示 → 各语言 → 工具选项”排列；注释放在本说明中。
YAML/TOML/INI 规则文件带分组注释，写明阈值、命名和检查目的。
不要向标准 JSON 添加不支持的注释；VS Code 原生 settings 支持 JSONC，但项目中的标准 JSON 示例便于通用解析。

## 接入和检查

新包自动生成 .vscode 和这些规则：

- .clang-format：ROS2 基础配置加明确缩进、定义块空行和短函数展开；需 clang-format 14+。
- .clang-tidy：函数规模和命名提醒，分组注释解释参数。
- pyproject.toml：Ruff 的排版与 lint 分节配置，Python 版本由所属 ROS 环境生成。
- .yamllint、.prettierrc.json、.prettierignore：检查与排版分别配置。
- .editorconfig：基础编码、换行和缩进约定。
- XML 规则放在 .vscode/settings.json 中。

已有父目录规则优先继承；同名已有文件保留并提示合并。
生成配置后按当前任务验证保存效果与诊断；缺失工具明确记录未就绪。
保存排版 → 查看提醒 → 片段检查/审阅差异 → 调试与行为测试。

规则版本写入 .engineering-template.json。
模板升级用于以后新包；已有包按任务需要审阅迁移，不自动覆盖学习者改动。

## 依据

[ROS2 官方风格与语言规范](https://github.com/ros2/ros2_documentation/blob/humble/source/The-ROS2-Project/Contributing/Code-Style-Language-Versions.rst)、
[clang-format 参数](https://clang.llvm.org/docs/ClangFormatStyleOptions.html)、
[Ruff 配置](https://docs.astral.sh/ruff/configuration/)、
[VS Code 设置](https://code.visualstudio.com/docs/configure/settings)。

诊断显示问题与任务验收见 [diagnostics_troubleshooting.md](diagnostics_troubleshooting.md)。
