# AGENTS.md

这是一个探索学习的前后端项目。

## 技术选型

### 前端框架
技术选型：Taro 4.x + React 18 + TypeScript
负责：写界面，跨端编译成小程序

前端状态/请求 Zustand.Trao.request 封装。目的是管理页面数据，和后端通信

### 后端框架
技术选型: FastApi + Python 3.11
负责：提供HTTP接口，自动生成文档
数据校验：Pydantic v2 约束请求/响应的数据结构
数据库： MySql

### AI编排
技术选型 LangChain + OpenAI SDK
负责：对接DeepSeek,约束AI输出格式

## 项目目录

backend 后端项目
frontend 前端项目
design 前端设计图
