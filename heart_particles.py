# -*- coding: utf-8 -*-
"""
3D 粒子环绕爱心 (3D Particle Heart)
====================================
数千个炫彩粒子分布在一颗**三维爱心**的体积与表面，整颗爱心在空间中
绕 Y 轴缓缓旋转、呼吸搏动，粒子如星云般环绕流淌。搭配透视投影、
深度雾化、景深模糊、加法混合辉光与梦幻拖尾，营造高级的粒子环绕视觉。

核心原理
--------
1. 三维爱心体积 —— 由经典参数方程生成"外壳"，再在壳内随机填充形成体积：
       x = 16·sin³(t) · cos(s)      (s ∈ [0,2π) 绕 Y 轴旋转)
       y = 13·cos t − 5·cos 2t − 2·cos 3t − cos 4t
       z = 16·sin³(t) · sin(s)
   即：先取 2D 爱心轮廓 (x0, y0)，让 x0 绕 Y 轴旋转一圈得到旋转体（3D 体积）。

2. 旋转 + 透视投影 —— 每个粒子绕 Y 轴旋转 angle 角后，用透视投影
   把 (x,y,z) 映射到屏幕：
       scale = f / (f + z)          # 近大远小
       sx = cx + x·scale            # 屏幕坐标
       sy = cy + y·scale
   通过 scale 同时控制粒子的大小与亮度 → 天然形成立体景深。

3. 呼吸 + 个体抖动 —— 整体呼吸系数 breath 让爱心在 3D 里脉动；
   每个粒子叠加独立相位的正弦抖动，如流动的星云。

4. 高级渲染：
   - 背景：柔和径向渐变（中心微微发亮）替代死黑；
   - 粒子：预渲染径向光晕贴图 + 加法混合，近亮远暗，叠加中心白核；
   - 拖尾：半透明覆盖形成星轨般的残影；
   - 颜色：随粒子空间位置（z 与旋转角度）在粉/紫光谱间流转。

操作：空格 = 重新绽放    ESC = 退出
依赖：pip install pygame
"""

import colorsys
import math
import random

import pygame

# ============================================================================
# 一、全局配置
# ============================================================================
WIDTH, HEIGHT     = 1280, 800            # 窗口尺寸
FPS               = 60                   # 目标帧率
BG_TOP            = (8, 6, 20)           # 背景渐变：顶部（深蓝紫）
BG_BOTTOM         = (2, 2, 8)            # 背景渐变：底部（更深）

TOTAL_PARTICLES   = 5500                 # 粒子总数
HEART_SCALE       = 16.0                 # 爱心缩放
HEART_CENTER      = (WIDTH * 0.5, HEIGHT * 0.5 - 10)

ROTATE_SPEED      = 0.45                 # 绕 Y 轴旋转速度（弧度/秒）
BREATH_SPEED      = 1.4                  # 呼吸速度（弧度/秒）
BREATH_DEPTH      = 0.07                 # 呼吸幅度
JITTER_AMP        = 0.8                  # 个体抖动幅度（像素，降低避免中心过曝堆积）
FOCAL             = 900.0                # 透视焦距：越小透视越夸张

HUE_MIN, HUE_MAX  = 0.80, 1.00           # 色相区间（粉紫系）
SAT_LEVELS        = (0.30, 0.55, 0.80, 1.0)
SIZE_CHOICES      = (3, 4, 5)            # 粒子核心半径档位
TRAIL_ALPHA       = 60                   # 拖尾强度（越大残影消散越快，越不刺眼）
PARTICLE_BRIGHT   = 0.55                 # 粒子亮度系数：整体压暗，柔和护眼

# 深度分层：按 z 范围划分 N 档，每档预渲染不同尺寸/亮度的光晕贴图
DEPTH_LAYERS      = 12
_glow_cache       = {}                   # (size_idx, hue_i, depth_i) -> Surface


# ============================================================================
# 二、三维爱心目标点生成
# ============================================================================
def heart_profile(t):
    """2D 爱心轮廓（y 轴向上为正），作为旋转体的母曲线。"""
    x = 16.0 * math.sin(t) ** 3
    y = (13.0 * math.cos(t)
         - 5.0 * math.cos(2.0 * t)
         - 2.0 * math.cos(3.0 * t)
         - 1.0 * math.cos(4.0 * t))
    return x, y


def random_heart_point():
    """
    在三维爱心体积内随机取一点（相对爱心中点）。
    用 2D 轮廓绕 Y 轴旋转生成旋转体；约 30% 落在外壳上，其余按 depth^0.5
    向中心收缩形成体积（越靠表面越密）。返回世界坐标 (x, y, z)。
    """
    t = random.uniform(0.0, math.tau)          # 轮廓参数
    s = random.uniform(0.0, math.tau)          # 绕 Y 轴旋转角
    x0, y0 = heart_profile(t)
    depth = 1.0 if random.random() < 0.30 else random.random() ** 0.5
    # 让轮廓点绕 Y 轴旋转，并乘 depth 向中心收缩 → 3D 体积
    x = x0 * math.cos(s) * depth
    z = x0 * math.sin(s) * depth
    y = y0 * depth
    return (x * HEART_SCALE,
            -y * HEART_SCALE,                  # y 翻转：屏幕向下为正
            z * HEART_SCALE)


# ============================================================================
# 三、颜色与发光贴图（预渲染 + 缓存）
# ============================================================================
def _hsv(hue):
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def make_glow(core_r, color, brightness):
    """预渲染一枚径向渐变光晕贴图（带 alpha，供加法混合）。"""
    gr = max(2, int(core_r * 3.2))
    surf = pygame.Surface((gr * 2, gr * 2), pygame.SRCALPHA)
    cx = cy = gr
    # 外圈柔和光晕（亮度乘护眼系数，避免过曝）
    for r in range(gr, 0, -1):
        k = (1.0 - r / gr) ** 2 * brightness * PARTICLE_BRIGHT
        a = int(255 * min(1.0, k))
        pygame.draw.circle(surf, (color[0], color[1], color[2], a), (cx, cy), r)
    # 中心柔和高光（不再加 80 的过曝白核，改弱化高光）
    core_col = (min(255, int(color[0] * 0.7 + 40)),
                min(255, int(color[1] * 0.7 + 40)),
                min(255, int(color[2] * 0.7 + 40)), 255)
    pygame.draw.circle(surf, core_col, (cx, cy), max(1, core_r // 2))
    return surf


def get_glow(core_r, hue, depth_f):
    """
    按 (尺寸档, 色相档, 深度档) 取缓存光晕贴图。
    depth_f ∈ [0,1]，0=最近(大而亮)，1=最远(小而暗)。
    """
    size_idx = min(len(SIZE_CHOICES) - 1, core_r)
    hue_i = int(hue * 20) % 20
    d_i = min(DEPTH_LAYERS - 1, int(depth_f * DEPTH_LAYERS))
    key = (size_idx, hue_i, d_i)
    surf = _glow_cache.get(key)
    if surf is None:
        # 深度越深：粒子越小、越暗（景深模糊 + 深度雾化）
        base_r = SIZE_CHOICES[size_idx]
        size = base_r * (1.35 - 0.75 * depth_f)          # 近大远小
        bright = 1.0 - 0.50 * depth_f                    # 近亮远暗（压低对比，护眼）
        surf = make_glow(int(size), _hsv(hue), bright)
        _glow_cache[key] = surf
    return surf


# ============================================================================
# 四、粒子类（3D 空间 + 投影渲染）
# ============================================================================
class Particle:
    __slots__ = ("wx", "wy", "wz", "hue", "size", "phase",
                 "life", "fade")

    def __init__(self, wx, wy, wz, hue, size, phase):
        self.wx, self.wy, self.wz = wx, wy, wz   # 世界坐标（相对爱心中点）
        self.hue = hue                           # 色相（粉紫光谱）
        self.size = size                         # 粒子尺寸档
        self.phase = phase                       # 抖动/呼吸相位
        self.life = random.uniform(0.0, 3.0)     # 环绕流动的随机相位
        self.fade = 0.0                          # 淡入进度 0→1

    def update(self, dt):
        self.life += dt
        self.fade = min(1.0, self.fade + dt * 0.9)   # 淡入

    def draw(self, screen, cx, cy, angle, breath, t):
        # ---- 绕 Y 轴旋转 ----
        c = math.cos(angle)
        s = math.sin(angle)
        x = self.wx * c + self.wz * s
        z = -self.wx * s + self.wz * c
        # ---- 呼吸缩放 ----
        br = breath
        x *= br
        z *= br
        y = self.wy * br
        # ---- 个体抖动（沿各轴正弦微抖，如流动星云）----
        j = JITTER_AMP
        x += math.sin(t * 2.1 + self.phase) * j
        y += math.cos(t * 2.4 + self.phase * 1.3) * j
        z += math.sin(t * 1.7 + self.phase * 0.7) * j * 2.0
        # ---- 透视投影 ----
        persp = FOCAL / (FOCAL + z)                  # 近大远小
        sx = cx + x * persp
        sy = cy + y * persp
        # 深度因子：z 越大越远（0 近 → 1 远）
        depth_f = max(0.0, min(1.0, (z + HEART_SCALE * 20) / (HEART_SCALE * 40)))
        # 色相随旋转角与深度轻微流转
        hue = (self.hue + angle * 0.06 + z * 0.002) % 1.0
        glow = get_glow(self.size, hue, depth_f)
        # 屏幕外剔除
        if sx < -glow.get_width() or sx > WIDTH + glow.get_width():
            return
        if sy < -glow.get_height() or sy > HEIGHT + glow.get_height():
            return
        # 加法混合绘制（淡入控制初始透明度）
        alpha = int(255 * self.fade)
        if alpha > 4:
            glow.set_alpha(alpha)
            screen.blit(glow,
                        (int(sx - glow.get_width() // 2),
                         int(sy - glow.get_height() // 2)),
                        special_flags=pygame.BLEND_RGB_ADD)


# ============================================================================
# 五、背景与主循环
# ============================================================================
def build_background():
    """预渲染柔和径向渐变背景（中心微微发亮）。"""
    bg = pygame.Surface((WIDTH, HEIGHT))
    cx, cy = WIDTH // 2, HEIGHT // 2
    maxd = math.hypot(cx, cy)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            d = math.hypot(x - cx, y - cy) / maxd
            k = 1.0 - d * 0.28                      # 中心轻微亮、四周暗（更柔和）
            r = int((BG_BOTTOM[0] + (BG_TOP[0] - BG_BOTTOM[0]) * (1 - y / HEIGHT)) * k)
            g = int((BG_BOTTOM[1] + (BG_TOP[1] - BG_BOTTOM[1]) * (1 - y / HEIGHT)) * k)
            b = int((BG_BOTTOM[2] + (BG_TOP[2] - BG_BOTTOM[2]) * (1 - y / HEIGHT)) * k)
            bg.set_at((x, y), (r, g, b))
    return bg


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("3D Particle Heart · 粒子环绕爱心")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 22)   # 内置字体，规避 pygame2.6+SysFont 崩溃

    background = build_background()

    # 拖尾层：半透明黑覆盖，形成残影
    fade = pygame.Surface((WIDTH, HEIGHT))
    fade.fill((0, 0, 0))
    fade.set_alpha(TRAIL_ALPHA)

    particles = []
    for _ in range(TOTAL_PARTICLES):
        wx, wy, wz = random_heart_point()
        hue = random.uniform(HUE_MIN, HUE_MAX)
        size = random.choices(SIZE_CHOICES, weights=(5, 3, 2))[0]
        phase = random.uniform(0, math.tau)
        particles.append(Particle(wx, wy, wz, hue, size, phase))

    cx, cy = HEART_CENTER
    angle = 0.0
    t = 0.0
    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        t += dt
        angle += ROTATE_SPEED * dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    t = 0.0
                    for p in particles:
                        p.fade = 0.0          # 重新淡入绽放

        breath = 1.0 + BREATH_DEPTH * math.sin(t * BREATH_SPEED)

        # 绘制背景 + 拖尾
        screen.blit(background, (0, 0))
        screen.blit(fade, (0, 0))

        # 更新并绘制所有粒子
        for p in particles:
            p.update(dt)
            p.draw(screen, cx, cy, angle, breath, t)

        hud = font.render(
            f"FPS {clock.get_fps():5.1f}   Particles {TOTAL_PARTICLES}   "
            f"SPACE=replay  ESC=quit",
            True, (150, 150, 180))
        screen.blit(hud, (14, 12))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
