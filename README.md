# Satellite Avoidance + RL (Daytona-ready skeleton)

This repository is a starter scaffold for a gravity simulator where one controlled satellite
learns to avoid `N` rotating gravitating bodies around Earth.

## Repo layout

- `src/sat_avoid/physics.py`: equations, rotating-body state, RK4 integration.
- `src/sat_avoid/env.py`: Gym-compatible environment.
- `src/sat_avoid/train.py`: PPO training entrypoint.
- `src/sat_avoid/daytona_adapter.py`: minimal Daytona-facing task payload adapter.

## Core mathematics (suitable for GitHub description)

State vector:

```
s = [x, y, z, vx, vy, vz]^T
```

Each obstacle body `i` is modeled as a circularly rotating point mass:

```
ri(t) = [R_i cos(ω_i t + φ_i), R_i sin(ω_i t + φ_i), z_i]^T
```

Satellite dynamics (control is thrust acceleration `u(t)` in m/s²):

```
dx/dt = vx
dy/dt = vy
dz/dt = vz

dv/dt = a_g(s, t) + u(t)
```

Earth gravity and all rotating-body gravities:

```
a_g(s, t) = -μ_e r / ||r||^3  -  Σ_i ( μ_i (r - r_i(t)) / ||r - r_i(t)||^3 )
```

where:

- `μ_e = GM_E` is Earth’s gravitational parameter.
- `μ_i = G M_i` for obstacle `i`.
- `r = [x,y,z]^T`, `r_i(t)` is the obstacle position above.

Numerical rollout uses RK4 for one timestep `Δt`:

```
k1 = f(s_t, t, u)
k2 = f(s_t + 0.5Δt k1, t + 0.5Δt, u)
k3 = f(s_t + 0.5Δt k2, t + 0.5Δt, u)
k4 = f(s_t + Δt k3, t + Δt, u)

s_{t+Δt} = s_t + Δt/6 (k1 + 2k2 + 2k3 + k4)
```

Reward template used in this skeleton:

- maximize distance to nearest obstacle,
- penalize control magnitude,
- and hard-penalize collisions/out-of-bounds.

## Quick setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run a local smoke train:

```bash
python -m sat_avoid.train
```

## GitHub repo bootstrap (local + remote)

```bash
git init
git branch -M main
git add .
git commit -m "chore: initial gravity/RL skeleton"
gh repo create <owner>/<repo> --public --source=. --remote=origin --push
```

If you prefer not to use GitHub CLI:

```bash
git remote add origin <your-remote-url>
git push -u origin main
```

## Notes

- This is intentionally a **skeleton**: no heavy policy architecture, domain randomization,
  or rendering loop yet.
- The `daytona_adapter.py` file gives a small stable payload shape you can adapt to the
  Daytona orchestrator you are using.
