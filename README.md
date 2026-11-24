# KGRAGS Mobile-Agent-v3

使用Mobile-Agent-v3执行KGRAGS手机任务。批跑配置使用`gpt-5.6-sol`。

| 文件 | 版本依据 |
| --- | --- |
| `mobile_agent_v3/mobile_v3/` | 手机任务执行器和实验配置，源码基于`38ac9fd` |
| `osworld_uipath/bounded_api_transport.py` | 模型请求传输模块 |
| `start_mobile_agent_full_batch.ps1` | 批跑启动器 |
| `continue_mobile_agent_after_preflight.ps1` | 续跑启动器 |

保留`mobile_agent_v3`和`osworld_uipath`的相邻布局。运行器从相邻目录加载传输模块。换机时按本地环境配置启动脚本、ADB和模型网关。

`source_manifest.json`记录文件指纹和版本依据。历史批次没有整仓指纹。

The optional OSWorld desktop RAG datasets are maintained separately. Supply local datasets with the desktop runner flags when needed.
