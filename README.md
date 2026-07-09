Reference article 参考文章：
>Unitree G1 真机部署链路详解
>[https://blog.csdn.net/shanpenghui/article/details/109354918](https://blog.csdn.net/shanpenghui/article/details/150577762?spm=1001.2014.3001.5502)

>跑通宇树G1的 sim2sim
>[https://blog.csdn.net/shanpenghui/article/details/109361766](https://blog.csdn.net/shanpenghui/article/details/150413803?spm=1001.2014.3001.5502)

## 安装配置

## 1. 创建虚拟环境

建议在虚拟环境中运行训练或部署程序，推荐使用 Conda 创建虚拟环境。

### 1.1 创建新环境

使用以下命令创建虚拟环境：

```bash
conda create -n robomimic python=3.8
```

### 1.2 激活虚拟环境

```bash
conda activate robomimic
```

## 2. 安装依赖

### 2.1 安装 PyTorch

PyTorch 是一个神经网络计算框架，用于模型训练和推理。使用以下命令安装：

```bash
conda install pytorch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 pytorch-cuda=12.1 -c pytorch -c nvidia
```

#### 2.2.2 安装组件

进入目录并安装：

```bash
cd RoboMimicDeploy_G1
pip install numpy==1.20.0
pip install onnx onnxruntime
pip install hydra-core
```

#### 2.2.3 安装unitree_sdk2_python

```bash
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
pip install -e .
```

## 运行代码

### 手柄兼容性

程序启动时自动检测平台并选择后端，无需手动配置：

| 平台 | 后端 | 支持手柄 |
|------|------|---------|
| Linux / Windows | pygame (SDL2) | Xbox、PlayStation 及大部分标准手柄 |
| macOS + mjpython | hidapi | DualSense PS5（USB 有线连接） |

> macOS 上必须使用 `mjpython` 启动仿真（MuJoCo 要求主线程处理 Cocoa GUI）。
> 且 Apple Game Controller Framework 会拦截 DualSense HID 报告导致按键映射错乱，
> 本项目使用 `hidapi` 直接读取原始 HID 数据绕过此问题。

### 前置：macOS 用户

```bash
# 安装 hidapi
pip install hidapi
```

### 1. 运行Mujoco仿真代码

**Linux（Xbox / PS 手柄）**：

```bash
python deploy_mujoco/deploy_mujoco.py
```

**macOS（DualSense PS5 手柄）**：

```bash
mjpython deploy_mujoco/deploy_mujoco.py
```

## 2. Policy 说明

| 模式名称              | 描述                                   |
| ----------------- | ------------------------------------ |
| **PassiveMode**   | 阻尼保护模式                               |
| **FixedPose**     | 位控恢复至默认关节值                           |
| **STANDMODE**     | 从平躺状态站立                              |
| **LocoMode**      | 用于稳定行走的控制模式                          |
| **Dance**         | 查尔斯顿舞蹈                               |
| **SKILL_ASAP**    | 罗纳尔多的起跳动作                            |
| **KungFu**        | 武术动作                                 |
| **KungFu2**       | 训练失败的武术动作                            |
| **Kick**          | 拿来凑数的动作                              |
| **SkillCast**     | 下肢+腰部稳定站立，上肢位控至特定关节角，一般在执行Mimic策略前执行 |
| **SkillCooldown** | 下肢+腰部持续平衡，上肢恢复至默认关节角，一般在执行Mimic策略后执行 |

## 3. 仿真操作说明

### 手柄按键对应

| 按键位置 | Xbox | DualSense (PS5) |
|---------|------|-----------------|
| 下方 | A | Cross (×) |
| 右侧 | B | Circle (○) |
| 左侧 | X | Square (□) |
| 上方 | Y | Triangle (△) |
| 左肩 | LB | L1 |
| 右肩 | RB | R1 |
| 返回 | Select | Share |
| 菜单 | Start | Options |
| 左摇杆按下 | L3 | L3 |
| 右摇杆按下 | R3 | R3 |

### 手柄操作

启动后机器人自动进入 LocoMode 站立模式。所有组合键操作为 **按住肩键 + 点按功能键**。

| 操作 | Xbox | DualSense | 说明 |
|------|------|-----------|------|
| 行走 | 左摇杆 | 左摇杆 | 上下=前进/后退，左右=平移 |
| 转向 | 右摇杆 | 右摇杆 | 左右旋转 |
| 复位站立 | **Start** | **Options** | 任意模式下安全返回站立 |
| 退出仿真 | **Select** | **Share** | 终止程序 |
| 移动模式 | **R1 + A** | **R1 + ×** | 进入 LocoMode 行走控制 |
| 跳舞 | **R1 + X** | **R1 + □** | 查尔斯顿舞蹈 |
| 功夫 | **R1 + Y** | **R1 + △** | 武术动作 (仅推荐仿真) |
| 踢腿 | **R1 + B** | **R1 + ○** | 踢腿动作 (仅推荐仿真) |
| 功夫2 | **L1 + Y** | **L1 + △** | 训练失败的武术动作 (仅推荐仿真) |
| 跳跃 | **L1 + A** | **L1 + ×** | ASAP 起跳动作 (仅推荐仿真) |
| 爬起 | **L1 + X** | **L1 + □** | 从倒地状态站立 |
| 阻尼保护 | **L1 + R1** | **L1 + R1** | 进入 PassiveMode 柔顺模式 |

> 按 **Start / Options** 可随时从任意技能状态安全返回站立。

## 4. 真机操作说明

1. 开机后将机器人吊起来

2. 运行deploy_real程序：

```bash
python deploy_real/deploy_real.py
```

3. Start键进入位控模式

4. 当机器人从平躺状态开始时，需要先按 L1+X 进入站立状态， 再按 R1+A 进入 LocoMode

5. 其他动作操作与仿真中一致

## 注意事项

### 1. 框架兼容性说明

当前框架暂不支持在搭载Orin NX平台的G1机器人上直接部署。初步分析可能是由于 `unitree_python_sdk`在Orin平台上的兼容性问题。针对机载Orin平台的部署需求，建议采用以下替代方案：

* 使用[unitree_sdk2](https://github.com/unitreerobotics/unitree_sdk2)替代原Python SDK

* 基于ROS构建双节点架构：

  * **C++节点**：负责机器人与遥控器之间的数据收发

  * **Python节点**：专用于策略推理

### 2. Mimic策略可靠性警告

Mimic策略不保证100%成功率，特别是在湿滑/沙地等复杂地面上。若出现机器人失控情况：

* 按下 `F1`键激活**阻尼保护模式**(PassiveMode)

* 按下 `Select`键立即终止控制程序

### 3. 查尔斯顿舞蹈(R1+X) - 稳定策略说明

目前唯一在真机上验证稳定的策略：

⚠️ **重要注意事项**：

* **建议拆除手掌**：原始训练未考虑手掌碰撞（作者的G1初始无手掌）

* **起止稳定需求**：舞蹈开始/结束时可能需要短暂人工稳定

* **舞蹈后过渡**：虽然可以切换至**行走模式/位控模式/阻尼模式**，但建议：

  * 先切换至**位控模式**或**阻尼模式**

  * 过渡期间需提供人工稳定

### 4. 其他动作建议

其他所有动作目前均**不建议**在真机上部署。

### 5. 强烈建议

**务必**先在仿真环境中熟练操作，再尝试真机部署。
