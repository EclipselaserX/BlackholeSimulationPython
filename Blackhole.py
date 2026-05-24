import pygame
import moderngl
import numpy as np
import sys
import time

# Initialize Pygame
pygame.init()
SCREEN_WIDTH, SCREEN_HEIGHT = 1280, 720
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.OPENGL | pygame.DOUBLEBUF)
pygame.display.set_caption("Blackhole Ultra V2")
clock = pygame.time.Clock()

ctx = moderngl.create_context()

vertices = np.array([
    -1.0, -1.0,
    1.0, -1.0,
    -1.0, 1.0,
    -1.0, 1.0,
    1.0, -1.0,
    1.0, 1.0,
], dtype='f4')

VERTEX_SHADER = """
#version 330
in vec2 in_vert;
out vec2 uv;
void main() {
    uv = in_vert;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
"""

unique_id = str(int(time.time()))
FRAGMENT_SHADER = """
#version 330
in vec2 uv;
out vec4 fragColor;
// Cache Buster Timestamp: """ + unique_id + """

#define M 1.0
#define RS 2.0
#define ISCO 6.0
#define MAX_STEPS 256

uniform vec2 u_resolution;
uniform vec2 u_mouse;
uniform float u_zoom;
uniform float u_time;
uniform float u_ring_sharpness;
uniform float u_bloom_intensity;

float hash(vec3 p) {
    p = fract(p * vec3(443.8975, 397.2973, 491.1871));
    p += dot(p.xyz, p.yzx + 19.19);
    return fract(p.x * p.y * p.z);
}

float noise3D(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f*f*(3.0-2.0*f);
    return mix(mix(mix(hash(i + vec3(0,0,0)), hash(i + vec3(1,0,0)), f.x),
                   mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
               mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
                   mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}

float fbm(vec3 p) {
    float v = 0.0;
    float a = 0.5;
    vec3 shift = vec3(100.0);
    for (int i = 0; i < 4; i++) {
        v += a * noise3D(p);
        p = p * 2.15 + shift;
        a *= 0.48;
    }
    return v;
}

void main() {
    vec2 st = uv * vec2(u_resolution.x / u_resolution.y, 1.0);
    float theta = u_mouse.y * 3.14159;
    float phi = u_mouse.x * 6.28318;

    vec3 ro = vec3(sin(theta)*sin(phi), cos(theta), sin(theta)*cos(phi)) * u_zoom;
    vec3 target = vec3(0.0);
    vec3 ww = normalize(target - ro);
    vec3 uu = normalize(cross(ww, vec3(0.0, 1.0, 0.0)));
    vec3 vv = normalize(cross(uu, ww));
    vec3 rd = normalize(st.x*uu + st.y*vv + 2.0*ww);

    vec3 p = ro;
    vec3 acc_color = vec3(0.0);
    float optical_depth = 0.0;
    float min_r = 999.0;
    float photon_ring_radius = RS * 1.11;
    float dynamic_inner_edge = photon_ring_radius - (4.0 / u_ring_sharpness);
    vec3 total_bloom = vec3(0.0);
    bool hit_horizon = false; 

    for (int i = 0; i < MAX_STEPS; i++) {
        float r2 = dot(p, p);
        float r = sqrt(r2);

        if (!hit_horizon && r < min_r) min_r = r;

        if (r < dynamic_inner_edge) {
            hit_horizon = true;
        }
        if (r > 48.0) {
            break;
        }

        float base_dt = max(0.035, (r - RS) * 0.095);
        float proximity_to_disk = abs(p.y);
        float dt = mix(base_dt * 0.5, base_dt, smoothstep(0.0, 1.5, proximity_to_disk));

        vec3 gravity = -1.5 * M * p / (r2 * r);
        rd = normalize(rd + gravity * dt);
        p += rd * dt;

        vec3 disk_vel = normalize(cross(vec3(0.0, 1.0, 0.0), p));
        float cos_alpha = dot(rd, disk_vel);
        float v = 1.0 / sqrt(max(RS + 0.1, r));
        float gamma = 1.0 / sqrt(1.0 - v*v);
        float step_doppler = 1.0 / (gamma * (1.0 - v * cos_alpha));
        float step_redshift = sqrt(1.0 - RS / r);
        float step_beaming = pow(step_doppler, 3.3);

        // --- ACCRETION DISK ---
        float disk_height = 0.45;
        if (abs(p.y) < disk_height && r >= ISCO && r < 22.0) {
            float texture_rotation = u_time * (2.8 / (r * sqrt(r)));
            float angle = atan(p.z, p.x) - texture_rotation;
            vec3 noise_pos = vec3(cos(angle)*r, p.y * 2.5, sin(angle)*r);

            float density = smoothstep(22.0, 10.0, r) * smoothstep(ISCO - 0.4, ISCO + 1.2, r);
            density *= (1.0 - abs(p.y) / disk_height);
            float gas_filaments = fbm(noise_pos * 0.65);
            density *= smoothstep(0.08, 0.72, gas_filaments);

            vec3 core_heat = vec3(1.0, 0.82, 0.5) * step_beaming;
            vec3 outer_gas = vec3(0.85, 0.18, 0.01) * step_doppler * step_redshift;
            vec3 current_gas_color = mix(outer_gas, core_heat, density * step_doppler * step_redshift);

            float step_absorption = density * dt * 0.95;
            acc_color += exp(-optical_depth) * current_gas_color * step_absorption;
            optical_depth += step_absorption;

            if (optical_depth > 4.5) {
                break;
            }
        }

        #define GLOW_RANGE 24.0
        // --- ASYMMETRIC DOPPLER BLOOM ---
        if (r >= ISCO - 1.0 && r < GLOW_RANGE) {
            float bloom_falloff = smoothstep(GLOW_RANGE, ISCO, r) * (1.0 / (1.0 + proximity_to_disk * 4.0));
            vec3 localized_bloom_color = mix(vec3(0.8, 0.15, 0.01), vec3(1.0, 0.75, 0.4), step_beaming * 0.3);
            total_bloom += exp(-optical_depth) * localized_bloom_color * bloom_falloff * step_beaming * dt * 0.07 * u_bloom_intensity;
        }
    }

    acc_color += total_bloom;

    // --- PHOTON RING ---
    if (min_r > dynamic_inner_edge && min_r < 900.0) {
        float delta_r = abs(min_r - photon_ring_radius);
        float ring_density = exp(-delta_r * u_ring_sharpness);
        vec3 ring_glow = vec3(1.0, 0.55, 0.18) * ring_density * 4.5;
        acc_color += exp(-optical_depth) * ring_glow;
    }

    // --- ALL-OVER CORE ENVIRONMENT BLOOM ---
    if (!hit_horizon && min_r > RS && min_r < 900.0) {
        float core_bloom_falloff = exp(-(min_r - RS) * 0.85);
        vec3 core_bloom_color = vec3(1.0, 0.42, 0.12) * core_bloom_falloff * 0.35 * u_bloom_intensity;
        acc_color += exp(-optical_depth) * core_bloom_color;
    }

    // --- COSMIC BACKGROUND SKYMAP ---
    vec3 background = vec3(0.003, 0.0015, 0.006);
    if (!hit_horizon && min_r > dynamic_inner_edge && optical_depth < 4.5) {
        vec3 lensed_rd = normalize(rd + vec3(noise3D(p * 0.008) * 0.015));
        float star_map = sin(lensed_rd.x * 32.0) * cos(lensed_rd.y * 32.0) * sin(lensed_rd.z * 32.0);
        if (star_map > 0.995) {
            background += vec3(0.9, 0.95, 1.0) * smoothstep(0.995, 1.0, star_map);
        }
    }

    vec3 final_rgb = hit_horizon ? acc_color : (acc_color + exp(-optical_depth) * background);
    final_rgb = vec3(1.0) - exp(-final_rgb * 2.0);
    final_rgb = pow(final_rgb, vec3(1.0 / 1.2));
    fragColor = vec4(final_rgb, 1.0);
}
"""

# Compile Shaders
program = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
vbo = ctx.buffer(vertices)
vao = ctx.vertex_array(program, vbo, 'in_vert')

mouse_x, mouse_y = 0.5, 0.44
zoom = 18.0
is_dragging = False
speed_multiplier = 1.0
custom_time = 0.0
ring_sharpness = 250.0
bloom_intensity = 1.0

running = True
while running:
    dt_frame = clock.tick(60) / 1000.0
    custom_time += dt_frame * speed_multiplier

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                is_dragging = True
            if event.button == 4:
                zoom = max(6.5, zoom - 0.6)
            if event.button == 5:
                zoom = min(38.0, zoom + 0.6)
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                is_dragging = False
        elif event.type == pygame.MOUSEMOTION and is_dragging:
            dx, dy = event.rel
            mouse_x += dx * (0.5 / SCREEN_WIDTH)
            mouse_y = max(0.08, min(0.92, mouse_y - dy * (0.5 / SCREEN_HEIGHT)))

    keys = pygame.key.get_pressed()

    # SPIN CONTROLS (Up / Down)
    if keys[pygame.K_UP]:
        speed_multiplier = min(45.0, speed_multiplier + max(0.05, abs(speed_multiplier) * 0.08))
    if keys[pygame.K_DOWN]:
        speed_multiplier = max(-15.0, speed_multiplier - max(0.05, abs(speed_multiplier) * 0.08))

    # THICKNESS CONTROLS (Left / Right)
    if keys[pygame.K_RIGHT]:
        ring_sharpness = min(1000.0, ring_sharpness + 4.0)
    if keys[pygame.K_LEFT]:
        ring_sharpness = max(40.0, ring_sharpness - 4.0)

    # BLOOM CONTROLS (W / S)
    if keys[pygame.K_w]:
        bloom_intensity = min(4.0, bloom_intensity + 0.04)
    if keys[pygame.K_s]:
        bloom_intensity = max(0.0, bloom_intensity - 0.04)

    ctx.clear(0.0, 0.0, 0.0)

    program['u_resolution'].value = (SCREEN_WIDTH, SCREEN_HEIGHT)
    program['u_mouse'].value = (mouse_x, mouse_y)
    program['u_zoom'].value = zoom
    program['u_time'].value = custom_time
    program['u_ring_sharpness'].value = ring_sharpness
    program['u_bloom_intensity'].value = bloom_intensity

    vao.render(moderngl.TRIANGLES)
    pygame.display.flip()

pygame.quit()
sys.exit()