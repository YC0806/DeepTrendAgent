# 关注领域

主要关注**面向 AI Agent、LLM 应用工程与智能体基础设施的开源项目**，重点不是泛泛的 AI 概念展示，而是能够支撑实际构建、集成、治理、评估和落地的工程化项目。

## 直接相关（relevant）

- **Agent Framework / Agent Runtime / Multi-Agent / Workflow Orchestration**：任务编排、工具调用、记忆、规划、Browser Agent、Research Agent、Code Agent
- **LLM Infra 与模型接入层**：模型网关、路由、代理层、推理服务、Serving、缓存、可观测性、调用治理、成本控制、多模型接入
- **RAG / Retrieval / Index / Knowledge Pipeline**：embedding、reranker、BM25、混合检索、知识组织、PageIndex、GraphRAG、TreeIndex、文档抽取与知识增强
- **Agent / LLM 工程配套工具链**：eval、trace、日志、指标、prompt 管理、数据集构建、反馈闭环、工具注册、插件生态、MCP、API gateway、DevTools、CLI agent、代码智能体相关工具
- **面向工程落地的 AI 应用基础能力**：浏览器自动化、工作流系统、插件系统、数据加工流水线、可部署的 SDK、可扩展的平台型项目

## 邻近相关（adjacent）

- 云原生基础设施、API Gateway、插件框架、可观测性平台、自动化工作流
- 浏览器自动化、数据工程与数据处理工具、开发者工具
- 文档处理与知识管理系统、前后端集成 SDK
- 不为 Agent/LLM 而设计但可作为其上游、下游或配套底座的项目

## 通常无关（irrelevant）

- 纯游戏、娱乐内容、设计素材站、通用 UI 模板
- 普通 CRUD 后台、个人博客生成器
- 与 AI/Agent/LLM 工程无明显关系的小工具
- 纯内容聚合站、没有技术方法创新的包装型应用

## 判断原则

不依赖项目表面标签，结合 description、README、能力说明和技术表达综合判断：

- 直接服务于 Agent / LLM 应用构建、运行、集成、治理、评估或知识增强 → `relevant`
- 能作为这些系统的工程配套、上下游基础设施或关键支撑能力 → `adjacent`
- 其余 → `irrelevant`
