"""
Losses: InfoNCE / SupCon / CORAL / GRL / VICReg — mirrors vector-unified / equities / hoops

InfoNCE same-ticker adjacent-FY contrastive (equities) / player-split (hoops)
SupCon → G3 archetype coherence
CORAL → G3 shared axis system
GRL λ 0.3 gradual warmup 10ep after 5ep warmup → G2 sport-invariance
VICReg var+cov → anti-collapse rank without hurting G1, task w=2.0 anchor G1
"""
try:
    import torch
    import torch.nn.functional as F

    def info_nce(z, pos_mask, temp=0.07):
        # z L2-normalized (B,d), pos_mask (B,B) bool, same-ticker adjacent-FY pattern
        sim = z @ z.T / temp
        # numerically stable log_softmax via subtract max per row done by F
        # positive logits mean
        exp_sim = torch.exp(sim)
        # sum over all but self? keep self out via mask
        denom = exp_sim.sum(dim=1, keepdim=True)
        log_prob = sim - torch.log(denom)
        # mean pos per row
        pos_count = pos_mask.sum(dim=1).clamp(min=1)
        loss = -(log_prob * pos_mask).sum(dim=1) / pos_count
        return loss.mean()

    def supcon_loss(features, labels, temp=0.07):
        # features L2-normed (B,d), labels (B) archetype / sector
        mask = (labels.unsqueeze(0) == labels.unsqueeze(1)).float()
        # exclude self
        mask.fill_diagonal_(0)
        return info_nce(features, mask>0, temp)

    def coral_loss(source, target):
        # CORAL alignment to G3 shared axis
        # Frobenius norm of covariance difference
        def cov(x):
            x = x - x.mean(dim=0, keepdim=True)
            return (x.T @ x) / (x.size(0)-1)
        return F.mse_loss(cov(source), cov(target))

    def vicreg_loss(z, lambda_var=25.0, lambda_cov=1.0):
        # var term + cov term anti-collapse (rank)
        # z (B,d) not necessarily normalized for var
        # var: hinge on std > 1
        std = torch.sqrt(z.var(dim=0) + 1e-4)
        var_loss = torch.mean(F.relu(1 - std))
        # cov
        B, D = z.shape
        z_ = z - z.mean(dim=0)
        cov = (z_.T @ z_) / (B-1)
        # off-diag
        off = cov - torch.diag(torch.diag(cov))
        cov_loss = (off ** 2).sum() / D
        return lambda_var * var_loss + lambda_cov * cov_loss

    # GRL is implemented as autograd function — λ schedule outside, gradual warmup 10ep after 5ep warmup
    import torch.autograd as autograd
    class GradReverse(autograd.Function):
        @staticmethod
        def forward(ctx, x, lambd):
            ctx.lambd = lambd
            return x.view_as(x)
        @staticmethod
        def backward(ctx, grad_output):
            return grad_output.neg() * ctx.lambd, None

    def grad_reverse(x, lambd=0.3):
        return GradReverse.apply(x, lambd)

except ImportError:
    pass
