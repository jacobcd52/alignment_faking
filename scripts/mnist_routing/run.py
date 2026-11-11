"""Does routing gradients on hack X make the full model disprefer X relative to an unrouted hack Y?

MNIST toy version of GRAFT (Ward, Hu et al. 2026). A frozen base MLP gets a retain and a forget
adapter. "Hacks" are two extra output tokens (classes 10 and 11) that share nothing with each other
beyond being non-digit labels. One of them (X) is routed with recall r: on flagged samples the
retain adapter gets coefficient 0 and the forget adapter coefficient c (the paper uses c=2). The
other (Y) is never routed. We track log P(X)/P(Y) of the full model (both adapters) and of the
retain-only model.

Every config x seed is one member of a batched ensemble, so a whole grid trains in one process.
Half the seeds route class 10 and half class 11, so any X/Y asymmetry in the base cancels.
"""
import argparse
import gzip
import json
import math
import os
import time

import numpy as np
import torch
import torch.nn.functional as F

N_DIGITS, N_OUT = 10, 12
H, H_AD, N_BLOCKS = 128, 64, 2


def load_mnist(d):
    def read(name, offset):
        with gzip.open(os.path.join(d, name + ".gz"), "rb") as f:
            return np.frombuffer(f.read(), np.uint8, offset=offset)
    xtr = read("train-images-idx3-ubyte", 16).reshape(-1, 784)
    ytr = read("train-labels-idx1-ubyte", 8)
    xte = read("t10k-images-idx3-ubyte", 16).reshape(-1, 784)
    yte = read("t10k-labels-idx1-ubyte", 8)
    f = lambda x: (torch.tensor(x.copy()).float() / 255 - 0.1307) / 0.3081
    return f(xtr), torch.tensor(ytr.copy()).long(), f(xte), torch.tensor(yte.copy()).long()


NORM = True


def ln(h):
    """Parameter-free LayerNorm. Without it the two adapters' tug-of-war blows up the residual stream."""
    return F.layer_norm(h, (H,)) if NORM else h


def pretrain_base(xtr, ytr, n_seeds, steps=1500, bs=128, lr=1e-3):
    """Train n_seeds base MLPs (batched) on clean digits. Outputs 10/11 exist but are never labels."""
    S = n_seeds
    p = {
        "w_in": torch.randn(S, 784, H) / math.sqrt(784), "b_in": torch.zeros(S, 1, H),
        "w_out": torch.randn(S, H, N_OUT) / math.sqrt(H), "b_out": torch.zeros(S, 1, N_OUT),
    }
    for l in range(N_BLOCKS):
        p[f"w1_{l}"] = torch.randn(S, H, H) / math.sqrt(H)
        p[f"b1_{l}"] = torch.zeros(S, 1, H)
        p[f"w2_{l}"] = torch.randn(S, H, H) / math.sqrt(H) * 0.5
    for v in p.values():
        v.requires_grad_(True)
    opt = torch.optim.Adam(p.values(), lr=lr)
    for _ in range(steps):
        idx = torch.randint(len(xtr), (S, bs))
        h = torch.relu(torch.bmm(xtr[idx], p["w_in"]) + p["b_in"])
        for l in range(N_BLOCKS):
            h = h + torch.bmm(torch.relu(torch.bmm(ln(h), p[f"w1_{l}"]) + p[f"b1_{l}"]), p[f"w2_{l}"])
        logits = torch.bmm(ln(h), p["w_out"]) + p["b_out"]
        loss = F.cross_entropy(logits.reshape(-1, N_OUT), ytr[idx].reshape(-1), reduction="none").view(S, bs).mean(1).sum()
        opt.zero_grad()
        loss.backward()
        opt.step()
    return {k: v.detach() for k, v in p.items()}


def init_adapter(E):
    """SwiGLU branch per block: (silu(hU) * hG) V, zero-initialised output."""
    ps = []
    for _ in range(N_BLOCKS):
        ps += [torch.randn(E, H, H_AD) / math.sqrt(H), torch.randn(E, H, H_AD) / math.sqrt(H), torch.zeros(E, H_AD, H)]
    return [p.requires_grad_(True) for p in ps]


def adapter_out(ps, l, h):
    u, g, v = ps[3 * l:3 * l + 3]
    return torch.bmm(F.silu(torch.bmm(h, u)) * torch.bmm(h, g), v)


def forward(base, R, Fg, h0, use_r=True, use_f=True):
    h = h0
    for l in range(N_BLOCKS):
        hn = ln(h)
        d = torch.bmm(torch.relu(torch.bmm(hn, base[f"w1_{l}"]) + base[f"b1_{l}"]), base[f"w2_{l}"])
        if use_r:
            d = d + adapter_out(R, l, hn)
        if use_f:
            d = d + adapter_out(Fg, l, hn)
        h = h + d
    return torch.bmm(ln(h), base["w_out"]) + base["b_out"]


def pm(gs_a, gs_b, pre=None):
    """Per-member inner product over a list of [E, ...] tensors, optionally preconditioned."""
    out = 0
    for i, (a, b) in enumerate(zip(gs_a, gs_b)):
        t = a * b if pre is None else a * b * pre[i]
        out = out + t.flatten(1).sum(1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--configs", required=True, help="JSON list of {name,c,r,wd,anchor}")
    ap.add_argument("--opt", choices=["sgd", "adamw", "split"], required=True)
    ap.add_argument("--mode", choices=["sft", "rl"], default="sft")
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--steps", type=int, default=10000)
    ap.add_argument("--warm", type=int, default=0, help="rl: unrouted SFT steps before RL starts")
    ap.add_argument("--bs", type=int, default=128)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--sched", choices=["const", "cosine"], default="const", help="cosine: 5%% warmup then cosine to 0, as in the paper")
    ap.add_argument("--eval_every", type=int, default=250)
    ap.add_argument("--n_eval", type=int, default=1000)
    ap.add_argument("--no_norm", action="store_true", help="drop the LayerNorms (pre-block and pre-unembed)")
    ap.add_argument("--threads", type=int, default=1)
    a = ap.parse_args()
    global NORM
    NORM = not a.no_norm
    torch.set_num_threads(a.threads)
    torch.manual_seed(0)
    lr0 = a.lr if a.lr is not None else (0.005 if a.opt == "sgd" else 1e-4)
    b1, b2, eps = 0.9, 0.95, 1e-8

    xtr, ytr, xte, yte = load_mnist(a.data)
    xte, yte = xte[:a.n_eval], yte[:a.n_eval]
    cfgs = json.loads(a.configs)
    S, C = a.seeds, len(cfgs)
    E = S * C
    seed_of = torch.arange(E) % S  # member e = config e//S, seed e%S
    col = lambda key: torch.tensor([cfgs[e // S][key] for e in range(E)]).float().view(E, 1)
    c, r, wd, anchor = col("c"), col("r"), col("wd"), col("anchor")
    rt = torch.where(seed_of % 2 == 0, 10, 11).view(E, 1)  # routed token X
    ot = 21 - rt                                           # unrouted token Y

    base_s = pretrain_base(xtr, ytr, S)
    with torch.no_grad():  # frozen first layer: cache its activations per seed
        h0_tr = torch.relu(xtr @ base_s["w_in"] + base_s["b_in"])  # [S, N, H]
        h0_te = torch.relu(xte @ base_s["w_in"] + base_s["b_in"])[seed_of]  # [E, n, H]
    base = {k: v[seed_of] for k, v in base_s.items() if k not in ("w_in", "b_in")}
    R, Fg = init_adapter(E), init_adapter(E)
    params = R + Fg
    nR = len(R)
    m = [torch.zeros_like(p) for p in params]
    v = [torch.zeros_like(p) for p in params]
    yte_e = yte.view(1, -1).expand(E, -1)

    def evaluate(t):
        out = {}
        with torch.no_grad():
            for name, ur, uf in [("full", True, True), ("retain", True, False), ("forget", False, True)]:
                z = forward(base, R, Fg, h0_te, ur, uf)
                p = z.softmax(-1)
                px, py = p.gather(2, rt.view(E, 1, 1).expand(-1, a.n_eval, 1)).squeeze(2), p.gather(2, ot.view(E, 1, 1).expand(-1, a.n_eval, 1)).squeeze(2)
                zx, zy = z.gather(2, rt.view(E, 1, 1).expand(-1, a.n_eval, 1)).squeeze(2), z.gather(2, ot.view(E, 1, 1).expand(-1, a.n_eval, 1)).squeeze(2)
                out[name] = {
                    "logodds": (zx - zy).mean(1), "logodds_med": (zx - zy).median(1).values, "px": px.mean(1), "py": py.mean(1),
                    "frac_x": (px / (px + py)).mean(1),
                    "digit_acc": (z[:, :, :N_DIGITS].argmax(-1) == yte_e).float().mean(1),
                }
        # Tangent-kernel balance: how far one step on X-labelled data moves the full model's X-Y logit
        # gap through each adapter. Routing removes the retain part and adds (c-1)x the forget part,
        # so the gap is locally preserved iff c = 1 + k_R / k_F.
        z = forward(base, R, Fg, h0_te)
        gap = (z.gather(2, rt.view(E, 1, 1).expand(-1, a.n_eval, 1)) - z.gather(2, ot.view(E, 1, 1).expand(-1, a.n_eval, 1))).mean(1).sum()
        lx = F.cross_entropy(z.reshape(-1, N_OUT), rt.expand(-1, a.n_eval).reshape(-1), reduction="none").view(E, -1).mean(1).sum()
        g_gap = torch.autograd.grad(gap, params, retain_graph=True)
        g_lx = torch.autograd.grad(lx, params)
        pre = None
        if a.opt != "sgd" and t > 0:
            pre = [1 / ((vi / (1 - b2 ** t)).sqrt() + eps) for vi in v]
        kR = -pm(g_gap[:nR], g_lx[:nR], None if pre is None else pre[:nR])
        kF = -pm(g_gap[nR:], g_lx[nR:], None if pre is None else pre[nR:])
        out["kernel"] = {"kR": kR, "kF": kF}
        return {k: {kk: vv.view(C, S).tolist() for kk, vv in d.items()} for k, d in out.items()}

    log = {"args": vars(a), "lr": lr0, "configs": cfgs, "evals": []}
    t0 = time.time()
    for t in range(a.steps + 1):
        if t % a.eval_every == 0:
            ev = evaluate(t)
            ev["step"] = t
            log["evals"].append(ev)
            lo = np.array(ev["full"]["logodds"]).mean(1)
            print(f"[{a.mode}/{a.opt}] step {t} ({time.time() - t0:.0f}s) full logodds X-Y by config: " + " ".join(f"{x:+.2f}" for x in lo), flush=True)
            with open(a.out, "w") as f:
                json.dump(log, f)
        if t == a.steps:
            break

        lr = lr0
        if a.sched == "cosine":
            wu = 0.05 * a.steps
            lr = lr0 * (t + 1) / wu if t < wu else lr0 * 0.5 * (1 + math.cos(math.pi * (t - wu) / (a.steps - wu)))
        idx = torch.randint(len(xtr), (E, a.bs))
        h0 = h0_tr[seed_of.view(E, 1), idx]
        y = ytr[idx]
        z = forward(base, R, Fg, h0)
        rl = a.mode == "rl" and t >= a.warm
        if not rl:  # SFT on labels: 50% true digit, 25% X, 25% Y
            u = torch.rand(E, a.bs)
            lab = torch.where(u < 0.5, y, torch.where(u < 0.75, rt.expand(-1, a.bs), ot.expand(-1, a.bs)))
            loss = F.cross_entropy(z.reshape(-1, N_OUT), lab.reshape(-1), reduction="none").view(E, a.bs)
        else:  # REINFORCE: both hacks pay 1, the right digit pays 0.5
            with torch.no_grad():
                lab = torch.multinomial(z.softmax(-1).view(-1, N_OUT), 1).view(E, a.bs)
                rew = ((lab == rt) | (lab == ot)).float() + 0.5 * (lab == y).float()
                adv = rew - rew.mean(1, keepdim=True)
            loss = adv * F.cross_entropy(z.reshape(-1, N_OUT), lab.reshape(-1), reduction="none").view(E, a.bs)
        flag = ((lab == rt) & (torch.rand(E, a.bs) < r)).float()
        if a.mode == "rl" and not rl:
            flag = torch.zeros_like(flag)  # warm start is unrouted
        loss_r = (loss * (1 - flag)).mean(1).sum()
        loss_f = (loss * (1 + (c - 1) * flag)).mean(1).sum()
        if anchor.sum() > 0 and not rl:  # anchor: retain-only forward on unflagged data, retain update only
            za = forward(base, R, Fg, h0[:, :16], use_f=False)
            la = F.cross_entropy(za.reshape(-1, N_OUT), lab[:, :16].reshape(-1), reduction="none").view(E, 16)
            loss_r = loss_r + (anchor * (la * (1 - flag[:, :16])).mean(1, keepdim=True)).sum()
        g = list(torch.autograd.grad(loss_r, R, retain_graph=True)) + list(torch.autograd.grad(loss_f, Fg, retain_graph=a.opt == "split"))
        # split-moment AdamW (the paper's): second moment from the unrouted gradient, so the
        # 0 and c coefficients are not normalised away
        g2 = torch.autograd.grad(loss.mean(1).sum(), params) if a.opt == "split" else g
        with torch.no_grad():
            for i, p in enumerate(params):
                w = wd.view(E, 1, 1)
                if a.opt == "sgd":
                    p -= lr * (g[i] + w * p)
                else:
                    m[i].mul_(b1).add_(g[i], alpha=1 - b1)
                    v[i].mul_(b2).addcmul_(g2[i], g2[i], value=1 - b2)
                    step = (m[i] / (1 - b1 ** (t + 1))) / ((v[i] / (1 - b2 ** (t + 1))).sqrt() + eps)
                    p -= lr * (step + w * p)


if __name__ == "__main__":
    main()
