# -*- coding: utf-8 -*-
"""
动态粒子爱心 (Particle Heart)
==============================
万千炫彩粒子从屏幕底部喷涌而上，以弹簧般的弧线轨迹汇聚成一颗
持续"呼吸"搏动的爱心。纯黑背景 + 加法混合辉光 + 淡淡拖尾，
粉 / 浅粉 / 紫 / 淡紫炫彩渐变，梦幻感拉满。

核心原理
--------
1. 爱心形状 —— 经典爱心参数方程（t ∈ [0, 2π)）：
       x = 16·sin³(t)
       y = 13·cos(t) − 5·cos(2t) − 2·cos(3t) − cos(4t)
   轮廓粒子直接取方程值；内部粒子由轮廓点向中心随机收缩得到，
   从而形成"实心"爱心。

2. 粒子物理 —— 每个粒子都被一根"看不见的弹簧"拉向自己的目标点：
       加速度 a = k · (目标点 − 当前位置)
       速度   v = (v + a) · 阻尼系数
   远处全力冲刺（限速封顶）、临近自然减速，加上出生时向上的初速度，
   轨迹会弯成柔美的喷泉状曲线。

3. 呼吸与抖动 —— 粒子抵达后，目标点随全局呼吸系数同步胀缩：
       breath = 1 + depth · sin(speed · t)
   并叠加每个粒子独立相位的正弦微抖动 → 整颗爱心像心跳一样搏动，
   粒子群如星云般轻轻颤动。

4. 发光渲染 —— 预渲染径向渐变光晕贴图，用 BLEND_RGB_ADD（加法混合）
   绘制：粒子重叠处亮度自动叠加、过曝发白，在纯黑背景上即为辉光；
   每帧再覆盖一层半透明黑色形成梦幻拖尾。

操作：空格 = 重新绽放    ESC = 退出
依赖：pip install pygame
"""

import colorsys
import math
import random

import pygame

# ============================================================================
# 一、全局配置（想调效果，改这里就够了）
# ============================================================================
WIDTH, HEIGHT   = 1200, 800              # 窗口尺寸
FPS             = 60                     # 目标帧率：60 帧保证流畅
BG_COLOR        = (0, 0, 0)              # 纯黑背景

TOTAL_PARTICLES = 3600                   # 粒子总数：越多爱心越饱满（越吃性能）
SPAWN_PER_FRAME = 16                     # 每帧从底部生成的粒子数（喷涌节奏）

HEART_SCALE     = 17.0                   # 爱心缩放系数（决定爱心大小）
HEART_CENTER    = (WIDTH * 0.5, HEIGHT * 0.5 - 15)   # 爱心中心（屏幕坐标）

BREATH_SPEED    = 1.6                    # 呼吸速度（弧度/秒）：越大跳得越快
BREATH_DEPTH    = 0.075                  # 呼吸深度：±7.5% 的缩放幅度

RISING_SPRING_K = 0.016                  # 上升阶段：弹簧刚度（a = k·距离）
RISING_DAMPING  = 0.90                   # 上升阶段：速度阻尼
MAX_SPEED       = 8.5                    # 上升阶段最大速度（像素/帧）
ARRIVE_RADIUS   = 7.0                    # 判定"抵达目标"的距离（像素）

HOLD_SPRING_K   = 0.055                  # 抵达后：跟随呼吸目标的弹簧刚度
HOLD_DAMPING    = 0.80                   # 抵达后：阻尼系数
JITTER_AMP      = 1.3                    # 抵达后：个体呼吸抖动幅度（像素）

TRAIL_ALPHA     = 42                     # 拖尾强度：每帧覆盖的半透明黑 alpha

# ---- 颜色档位（粉 → 浅粉 → 紫 → 淡紫 的 HSV 区间，量化后便于缓存贴图）----
HUE_MIN, HUE_MAX = 0.78, 1.00            # 色相：0.78≈紫 → 1.0≈玫红/粉
HUE_STEPS        = 28                    # 色相量化档数
SAT_LEVELS       = (0.28, 0.62, 0.92)    # 饱和度：淡紫/浅粉 ↔ 艳粉/艳紫
SAT_WEIGHTS      = (2, 4, 5)             # 各饱和度档的抽取权重

SIZE_CHOICES     = (2, 3, 4)             # 粒子核心半径档位（像素）
SIZE_WEIGHTS     = (5, 3, 1)             # 小粒子多一些，层次更丰富
ALPHA_LEVELS     = (0.18, 0.38, 0.58, 0.78, 1.0)   # 透明度(亮度)档位


# ============================================================================
# 二、爱心参数方程与目标点生成
# ============================================================================
def heart_equation(t):
    """
    经典爱心参数方程：返回数学坐标系下的 (x, y)（y 轴向上为正）。
        x = 16·sin³(t)
        y = 13·cos(t) − 5·cos(2t) − 2·cos(3t) − cos(4t)
    """
    x = 16.0 * math.sin(t) ** 3
    y = (13.0 * math.cos(t)
         - 5.0 * math.cos(2.0 * t)
         - 2.0 * math.cos(3.0 * t)
         - 1.0 * math.cos(4.0 * t))
    return x, y


def random_heart_target():
    """
    在爱心区域内随机取一个目标点（返回相对爱心中点的偏移，已乘缩放）。
    约 42% 的粒子落在轮廓上（depth = 1），勾勒清晰边缘；
    其余按 depth^0.55 分布在内部（越靠边越密），形成实心效果。
    """
    t = random.uniform(0.0, math.tau)
    hx, hy = heart_equation(t)
    depth = 1.0 if random.random() < 0.42 else random.random() ** 0.55
    return hx * HEART_SCALE * depth, hy * HEART_SCALE * depth


# ============================================================================
# 三、颜色与发光贴图（预渲染 + 缓存，避免每帧逐像素计算）
# ============================================================================
_glow_cache = {}      # (size, color_key, alpha_idx) -> Surface


def random_color_key():
    """随机抽取一个量化颜色 key = (色相档, 饱和度档)。"""
    hue_i = random.randrange(HUE_STEPS)
    sat_i = random.choices(range(len(SAT_LEVELS)), weights=SAT_WEIGHTS)[0]
    return hue_i, sat_i


def key_to_color(color_key):
    """把量化 key 还原为 RGB 颜色。"""
    hue_i, sat_i = color_key
    hue = HUE_MIN + hue_i / (HUE_STEPS - 1) * (HUE_MAX - HUE_MIN)
    r, g, b = colorsys.hsv_to_rgb(hue, SAT_LEVELS[sat_i], 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def make_glow_surface(core_radius, color, brightness=1.0):
    """
    预渲染一枚"发光粒子"贴图：
      · 黑底无 alpha，用亮度本身表示发光强度；
      · 从外向内画多层同心圆，亮度按平方衰减 → 径向辉光；
      · 最中心叠一枚灰白亮点 → 粒子核心。
    绘制时配合 BLEND_RGB_ADD 加法混合，粒子重叠处自然过曝发白。
    """
    glow_r = core_radius * 4                      # 光晕半径
    surf = pygame.Surface((glow_r * 2, glow_r * 2))
    surf.fill((0, 0, 0))
    center = (glow_r, glow_r)
    for r in range(glow_r, 0, -1):                # 外圈暗、内圈亮
        k = (1.0 - r / glow_r) ** 2 * brightness
        col = (min(255, int(color[0] * k)),
               min(255, int(color[1] * k)),
               min(255, int(color[2] * k)))
        pygame.draw.circle(surf, col, center, r)
    wb = int(55 + 200 * brightness)               # 灰白核心亮点
    pygame.draw.circle(surf, (wb, wb, wb), center, max(1, core_radius // 2))
    return surf


def get_glow_layers(core_radius, color_key):
    """取（带缓存）同一颜色的 5 档透明度发光贴图，供粒子淡入与透明度使用。"""
    layers = []
    for ai in range(len(ALPHA_LEVELS)):
        key = (core_radius, color_key, ai)
        surf = _glow_cache.get(key)
        if surf is None:
            surf = make_glow_surface(core_radius, key_to_color(color_key),
                                     ALPHA_LEVELS[ai]).convert()
            _glow_cache[key] = surf
        layers.append(surf)
    return tuple(layers)


# ============================================================================
# 四、粒子类：上升汇聚 → 抵达 → 随爱心呼吸抖动
# ============================================================================
class Particle:
    """
    单个粒子。
    属性：位置(x,y)、速度(vx,vy)、加速度(ax,ay)、颜色(glow_layers)、
          大小(size)、透明度(alpha)、目标偏移(rx,ry)、相位(phase)等。
    物理步长按"帧"设计，配合 FPS=60 锁定，保证节奏稳定。
    """
    __slots__ = ("x", "y", "vx", "vy", "ax", "ay", "rx", "ry", "size",
                 "phase", "arrived", "life", "alpha", "alpha_target",
                 "glow_layers")

    def __init__(self, rx, ry, size, color_key):
        self.rx, self.ry = rx, ry                 # 相对爱心中点的目标偏移
        self.size = size                          # 粒子大小（核心半径）
        self.glow_layers = get_glow_layers(size, color_key)   # 颜色/发光贴图
        # 出生点：屏幕底部之下的随机横向位置
        self.x = random.uniform(0, WIDTH)
        self.y = HEIGHT + random.uniform(20, 160)
        # 初速度：向上为主 + 随机水平扰动 → 弯曲的喷泉轨迹
        self.vx = random.uniform(-2.2, 2.2)
        self.vy = random.uniform(-5.5, -1.0)
        self.ax = self.ay = 0.0                   # 加速度（每帧重算）
        self.phase = random.uniform(0, math.tau)  # 个体抖动/湍流相位
        self.arrived = False                      # 是否已抵达爱心目标点
        self.life = 0.0                           # 存活时间（秒）
        # 透明度：出生时较暗，逐渐淡入到随机目标值（层次感）
        self.alpha = ALPHA_LEVELS[0]
        self.alpha_target = random.uniform(0.55, 1.0)

    # ---- 状态更新 ----------------------------------------------------------
    def update(self, dt, breath, cx, cy, t):
        self.life += dt
        if self.arrived:
            # ★ 已抵达：目标点 = 呼吸缩放后的爱心位置 + 个体正弦抖动
            tx = cx + self.rx * breath + math.sin(t * 3.1 + self.phase) * JITTER_AMP
            ty = cy + self.ry * breath + math.cos(t * 2.7 + self.phase * 1.7) * JITTER_AMP
            self.ax = (tx - self.x) * HOLD_SPRING_K     # 弹簧追随呼吸目标
            self.ay = (ty - self.y) * HOLD_SPRING_K
            self.vx = (self.vx + self.ax) * HOLD_DAMPING
            self.vy = (self.vy + self.ay) * HOLD_DAMPING
        else:
            # ★ 上升汇聚：被弹簧拉向爱心上的目标点
            dx = (cx + self.rx) - self.x
            dy = (cy + self.ry) - self.y
            self.ax = dx * RISING_SPRING_K
            self.ay = dy * RISING_SPRING_K
            # 轻微横向湍流，让上升轨迹更灵动
            self.ax += math.sin(t * 2.0 + self.phase) * 0.02
            self.vx = (self.vx + self.ax) * RISING_DAMPING
            self.vy = (self.vy + self.ay) * RISING_DAMPING
            # 限速：防止远距冲刺过快破坏美感
            sp2 = self.vx * self.vx + self.vy * self.vy
            if sp2 > MAX_SPEED * MAX_SPEED:
                k = MAX_SPEED / math.sqrt(sp2)
                self.vx *= k
                self.vy *= k
            # 足够接近目标 → 切换为"已抵达"的呼吸状态
            if dx * dx + dy * dy < ARRIVE_RADIUS * ARRIVE_RADIUS:
                self.arrived = True
        # 积分位置
        self.x += self.vx
        self.y += self.vy
        # 透明度淡入
        self.alpha += (self.alpha_target - self.alpha) * 0.025

    # ---- 绘制 ----------------------------------------------------------------
    def draw(self, screen):
        # 按当前透明度挑选最接近的亮度档位贴图（加法混合 = 发光）
        a = self.alpha
        if a < 0.28:
            idx = 0
        elif a < 0.48:
            idx = 1
        elif a < 0.68:
            idx = 2
        elif a < 0.89:
            idx = 3
        else:
            idx = 4
        g = self.glow_layers[idx]
        screen.blit(g, (int(self.x - g.get_width() // 2),
                        int(self.y - g.get_height() // 2)),
                    special_flags=pygame.BLEND_RGB_ADD)


# ============================================================================
# 五、场景构建与主循环
# ============================================================================
def build_particle_specs():
    """预生成全部粒子的目标点与外观规格，并打乱顺序（涌入过程均匀炫彩）。"""
    specs = []
    for _ in range(TOTAL_PARTICLES):
        rx, ry = random_heart_target()
        size = random.choices(SIZE_CHOICES, weights=SIZE_WEIGHTS)[0]
        specs.append((rx, ry, size, random_color_key()))
    random.shuffle(specs)
    return specs


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Particle Heart · 粒子爱心")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 15)

    # 拖尾层：每帧覆盖一层半透明黑，旧画面渐渐变暗 → 梦幻拖尾
    fade = pygame.Surface((WIDTH, HEIGHT))
    fade.fill(BG_COLOR)
    fade.set_alpha(TRAIL_ALPHA)

    specs = build_particle_specs()
    pending = specs[:]                            # 待激活（尚未从底部生成）
    active = []                                   # 已激活粒子
    screen.fill(BG_COLOR)

    t = 0.0                                       # 全局时间（秒）
    cx, cy = HEART_CENTER
    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)  # 锁 60 帧，防卡顿跳变
        t += dt

        # ---- 事件处理 --------------------------------------------------------
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:          # 重新绽放
                    specs = build_particle_specs()
                    pending = specs[:]
                    active = []
                    screen.fill(BG_COLOR)

        # ---- 1. 从屏幕底部喷涌出新粒子 ----------------------------------------
        for _ in range(min(SPAWN_PER_FRAME, len(pending))):
            active.append(Particle(*pending.pop()))

        # ---- 2. 全局呼吸系数：爱心整体缩放随时间正弦起伏 ------------------------
        breath = 1.0 + BREATH_DEPTH * math.sin(t * BREATH_SPEED)

        # ---- 3. 物理更新 --------------------------------------------------------
        for p in active:
            p.update(dt, breath, cx, cy, t)

        # ---- 4. 渲染：先覆盖拖尾层，再加法混合绘制发光粒子 ----------------------
        screen.blit(fade, (0, 0))
        for p in active:
            p.draw(screen)

        # ---- 5. 角落 HUD（帧率 / 粒子数 / 操作提示） -----------------------------
        hud = font.render(
            f"FPS {clock.get_fps():5.1f}   Particles {len(active):5d}   "
            f"SPACE=replay  ESC=quit",
            True, (95, 95, 115))
        screen.blit(hud, (14, 12))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
