# WhiteNight技术文档
-- 本文档对“大脑”和“身体”的具体技术细节进行讨论。

## 1.大脑
由于硬件算力限制，主脑目前只能使用Qwen3-8B小模型，使用ollamma部署与本地。
使用LoRA进行微调，寻找开源高质量的训练语料（猫娘风格聊天记录），手动筛选一轮后进行训练。训练可以临时租赁高性能服务器。
在微调的时候也要注意，摒除用于触发安全限制的权重。


## 2.身体（WhiteNight Cyberbody）

### 2.1 核心架构
是一个类harness的项目，使用webUI。深度融合Hermes与Deepseek Harness。重点关注Hermes的长期记忆管理、自进化以及电脑操控；DeepSeek harness的低耦合模块化以及可扩展性。
参考项目地址：
https://github.com/NousResearch/hermes-agent
https://github.com/deepseek-ai/deepseek-harness


### 2.2 多模态
考虑基模使用qwen3-vl:8b，自带看图能力。


### 2.3 接入QQ
使用Napcat和Astrbot，能够通过QQ响应文字和图片信息，也能通过QQ接收和发送文件，总而言之像真人一样控制QQ。也可以参考/Users/misaka/Desktop/WhiteNight/references_projects里的两个项目。


## 3.其他约束
使用git进行代码管理，代码上传至Github私有仓库，如果有必要，可以将自己训练的模型权重上传至hugging face。

